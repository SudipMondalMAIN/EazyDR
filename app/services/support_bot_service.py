"""
Support bot — calls Google AI Studio's Gemini API server-side (key never
reaches the Flutter app). Policy/FAQ facts are hardcoded into the system
prompt so the model can't hallucinate wrong refund windows etc. The model
is instructed to reply with the literal tag [ESCALATE] anywhere in its
response whenever it can't help or the user asks for medical advice or a
human — support_chat.service looks for that tag and flips the session to
WAITING_AGENT.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("support_bot_service")

GEMINI_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
)

ESCALATE_TAG = "[ESCALATE]"

# Keep this in sync with actual policy. Edit here only — nothing else in
# the codebase should hardcode support policy text.
POLICY_TEXT = f"""
- Booking: user searches a facility/doctor on the EazyDoctor app, picks a slot, and confirms. Booking fee is charged at booking time.
- Payment failed: if money was deducted but booking shows failed, it will be auto-refunded within 7 working days to the original payment method.
- Cancellation: user can cancel a booking from "My Bookings". A cancellation deduction may apply depending on how close to the appointment time it is cancelled.
- Refund status: refunds are processed to the original payment method within 7 working days.
- Support contact (only give this if the user explicitly asks for phone/email/WhatsApp, or after escalation): phone {settings.support_contact_phone or 'not set'}, email {settings.support_contact_email}, WhatsApp {settings.support_contact_whatsapp or 'not set'}.
""".strip()

SYSTEM_PROMPT_TMPL = """You are the customer support assistant for EazyDoctor, a doctor/medical facility booking app. You must reply ONLY in {language}, in a short, friendly, simple tone suitable for a chat bubble (2-4 sentences max).

You may ONLY use the following facts to answer booking/payment/account/refund questions. Never invent policy details that aren't listed here:
{policy}

Rules you must always follow:
1. Only help with: how to book, payment issues, cancellation, refund status, account/profile questions, and general app usage.
2. NEVER give medical advice, diagnosis, medicine suggestions, or health opinions of any kind. If the user asks a health/medical question, politely tell them to consult their doctor directly, and append the literal tag {escalate_tag} at the very end of your reply so a human can also follow up.
3. If you are not confident about the answer, or the answer needs info you don't have (e.g. a specific booking ID's status, a payment dispute, account access issue), say you'll connect them to a support agent, and append {escalate_tag} at the very end.
4. If the user explicitly asks to talk to a human/agent/support executive, confirm you're connecting them, and append {escalate_tag} at the very end.
5. Never mention that you are Gemini, Google, or an AI model. You are "EazyDoctor Support".
6. Keep replies short — this is a mobile chat window, not an essay."""


def _system_prompt(language: str) -> str:
    return SYSTEM_PROMPT_TMPL.format(language=language, policy=POLICY_TEXT, escalate_tag=ESCALATE_TAG)


async def get_bot_reply(history: list[dict], language: str) -> tuple[str, bool]:
    """history: list of {"role": "user"|"model", "text": str}, oldest first.
    Returns (reply_text_without_tag, should_escalate)."""
    if not settings.ai_studio_key:
        logger.warning("AI_STUDIO_KEY not configured — falling back to static reply")
        return (
            "Sorry, our chat assistant is temporarily unavailable. Connecting you to a support agent.",
            True,
        )

    contents = [{"role": h["role"], "parts": [{"text": h["text"]}]} for h in history]
    payload = {
        "system_instruction": {"parts": [{"text": _system_prompt(language)}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 300},
    }
    url = GEMINI_URL_TMPL.format(model=settings.gemini_model, key=settings.ai_studio_key)

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            logger.error("Gemini call failed (%s): %s", resp.status_code, resp.text)
            return ("Sorry, I couldn't process that. Connecting you to a support agent.", True)

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ("Sorry, I couldn't process that. Connecting you to a support agent.", True)

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()

        should_escalate = ESCALATE_TAG in text
        clean_text = text.replace(ESCALATE_TAG, "").strip()
        if not clean_text:
            clean_text = "Connecting you to a support agent who can help further."
        return clean_text, should_escalate
    except Exception:
        logger.exception("Gemini call raised an exception")
        return ("Sorry, something went wrong. Connecting you to a support agent.", True)
