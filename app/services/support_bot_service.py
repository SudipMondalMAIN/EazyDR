"""
Support bot — calls Groq's OpenAI-compatible chat completions API
server-side (key never reaches the Flutter app). Policy/FAQ facts are
hardcoded into the system prompt so the model can't hallucinate wrong
refund windows etc. The model is instructed to reply with the literal tag
[ESCALATE] anywhere in its response whenever it can't help or the user
asks for medical advice or a human — support_chat.service looks for that
tag and flips the session to WAITING_AGENT.
"""
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("support_bot_service")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

ESCALATE_TAG = "[ESCALATE]"

# Keep this in sync with actual policy. Edit here only — nothing else in
# the codebase should hardcode support policy text.
POLICY_TEXT = f"""
- Booking: user searches a facility/doctor on the EazyDoctor app, picks a slot, and confirms. Booking fee is charged at booking time.
- Payment failed: if money was deducted but booking shows failed, it will be auto-refunded within 7 working days to the original payment method.
- Cancellation: user can cancel a booking from "My Bookings", but only up to {settings.cancellation_lock_hours} hours before the appointment — after that it's locked and cannot be self-cancelled. Cancelling deducts {settings.default_cancellation_deduction_percent}% of the booking fee by default (facility-specific rate may differ); the remaining amount is credited as EazyDoctor reward points to the user's wallet, NOT refunded in cash to the original payment method.
- Refund status (cash, payment-failed case only): processed to the original payment method within 7 working days.
- Refund status (cancellation case): credited instantly as reward points to the user's in-app wallet — check the user's reward point balance below rather than telling them to wait 7 days.
- Support contact (only give this if the user explicitly asks for phone/email/WhatsApp, or after escalation): phone {settings.support_contact_phone or 'not set'}, email {settings.support_contact_email}, WhatsApp {settings.support_contact_whatsapp or 'not set'}.
""".strip()

SYSTEM_PROMPT_TMPL = """You are EazyDoctor Support Assistant. Answer only EazyDoctor-related questions, in a short, friendly, simple tone suitable for a chat bubble (2-4 sentences max).

Language: detect the language the user is currently writing in from their most recent message and reply in that same language (e.g. Bengali, Hindi, English, Hinglish/Banglish, or any other language/script the user uses). If the user switches language mid-conversation, switch with them. The session's configured default language is {language} — use it only for the very first greeting or if the user's message is too short/ambiguous to detect a language (e.g. just "ok" or an emoji).

You may ONLY use the following facts to answer booking/payment/account/refund questions. Never invent policy details that aren't listed here:
{policy}

{booking_context}
Use the booking data above to directly answer questions like "where's my booking", "did my payment go through", "what's my refund status", "when's my appointment" — reference the specific booking (date/doctor/facility/status) instead of giving a generic answer or escalating. Only escalate if the question needs something NOT in this data (e.g. a dispute, a booking not listed here, or something requiring a human decision).

Rules you must always follow:
1. Only help with: how to book, payment issues, cancellation, refund status, account/profile questions, and general app usage.
2. NEVER give medical advice, diagnosis, medicine suggestions, or health opinions of any kind. If the user asks a health/medical question, politely tell them to consult their doctor directly, and append the literal tag {escalate_tag} at the very end of your reply so a human can also follow up.
3. If you are not confident about the answer, or the answer needs info you don't have (e.g. a specific booking ID's status, a payment dispute, account access issue), say you'll connect them to a support agent, and append {escalate_tag} at the very end.
4. If the user explicitly asks to talk to a human/agent/support executive, confirm you're connecting them, and append {escalate_tag} at the very end.
5. Never mention that you are Groq, Llama, or an AI model. You are "EazyDoctor Support".
6. Keep replies short — this is a mobile chat window, not an essay."""


def _system_prompt(language: str, booking_context: str) -> str:
    return SYSTEM_PROMPT_TMPL.format(
        language=language, policy=POLICY_TEXT, escalate_tag=ESCALATE_TAG, booking_context=booking_context
    )


async def get_bot_reply(history: list[dict], language: str, booking_context: str = "") -> tuple[str, bool]:
    """history: list of {"role": "user"|"model", "text": str}, oldest first
    (role "model" here maps to OpenAI-style "assistant"). booking_context is
    a short plain-text summary of the user's own recent bookings (status,
    payment, refund-relevant fields) so the bot can answer 'where's my
    booking' style questions directly instead of always escalating. Returns
    (reply_text_without_tag, should_escalate)."""
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY not configured — falling back to static reply")
        return (
            "Sorry, our chat assistant is temporarily unavailable. Connecting you to a support agent.",
            True,
        )

    messages = [{"role": "system", "content": _system_prompt(language, booking_context or "No booking data available.")}]
    for h in history:
        role = "assistant" if h["role"] == "model" else "user"
        messages.append({"role": role, "content": h["text"]})

    payload = {
        "model": settings.groq_model,
        "messages": messages,
        "temperature": 0.3,
        "max_completion_tokens": 300,
    }
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(GROQ_URL, json=payload, headers=headers)
        if resp.status_code >= 400:
            logger.error("Groq call failed (%s): %s", resp.status_code, resp.text)
            return ("Sorry, I couldn't process that. Connecting you to a support agent.", True)

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ("Sorry, I couldn't process that. Connecting you to a support agent.", True)

        text = (choices[0].get("message", {}).get("content") or "").strip()

        should_escalate = ESCALATE_TAG in text
        clean_text = text.replace(ESCALATE_TAG, "").strip()
        if not clean_text:
            clean_text = "Connecting you to a support agent who can help further."
        return clean_text, should_escalate
    except Exception:
        logger.exception("Groq call raised an exception")
        return ("Sorry, something went wrong. Connecting you to a support agent.", True)