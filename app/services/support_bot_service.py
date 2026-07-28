"""
Support bot — calls Groq's OpenAI-compatible chat completions API
server-side (key never reaches the Flutter app). Policy/FAQ facts are
hardcoded into the system prompt so the model can't hallucinate wrong
refund windows etc. The model is instructed to reply with the literal tag
[ESCALATE] anywhere in its response whenever it can't help or the user
asks for medical advice or a human — support_chat.service looks for that
tag and flips the session to WAITING_AGENT.

Tool calling: the bot can search doctors/facilities, create a booking, and
cancel a booking — but it NEVER touches the database directly. Every tool
call here is routed through the same validated service-layer functions
used by the app's own API routes (app.modules.facilities.service /
app.modules.bookings.service), so business rules (cancellation lock hours,
ownership checks, etc.) are enforced exactly the same way. patient_id
always comes from the authenticated chat session, never from the model.
"""
import json
import logging
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import PaymentMode
from app.modules.bookings.schemas import BookingCreate
from app.modules.facilities import service as facilities_service
from app.modules.facilities.schemas import FacilitySearchParams

logger = logging.getLogger("support_bot_service")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

ESCALATE_TAG = "[ESCALATE]"
MAX_TOOL_ROUNDS = 4

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

You have tools to search doctors/facilities, book an appointment, and cancel a booking. Rules for using them:
- Use search_doctors_facilities whenever the user wants to find a doctor, specialty, or facility/clinic — don't just tell them to search in the app, actually search for them.
- Before calling book_appointment: you must already have facility_id and doctor_id (from a prior search_doctors_facilities call in this conversation), the appointment_date, payment_mode, and the patient's name/phone/address. Ask for whatever is missing. Then, ONLY after the user has explicitly confirmed ("yes", "confirm", "book it", etc.) in their most recent message, call book_appointment with confirm=true.
- Before calling cancel_appointment: the booking must be one of the user's own bookings listed above. Tell the user which booking (doctor/date/token) you're about to cancel and what the refund will be, and ONLY after they explicitly confirm, call cancel_appointment with confirm=true.
- Never call book_appointment or cancel_appointment with confirm=true unless the user's most recent message is a clear yes/confirmation to that specific action.
- If a tool call fails or returns an error, explain the problem in plain language — don't expose raw error text.

Rules you must always follow:
1. Only help with: how to book, payment issues, cancellation, refund status, account/profile questions, and general app usage.
2. NEVER give medical advice, diagnosis, medicine suggestions, or health opinions of any kind. If the user asks a health/medical question, politely tell them to consult their doctor directly, and append the literal tag {escalate_tag} at the very end of your reply so a human can also follow up.
3. If you are not confident about the answer, or the answer needs info you don't have (e.g. a specific booking ID's status, a payment dispute, account access issue), say you'll connect them to a support agent, and append {escalate_tag} at the very end.
4. If the user explicitly asks to talk to a human/agent/support executive, confirm you're connecting them, and append {escalate_tag} at the very end.
5. Never mention that you are Groq, Llama, or an AI model. You are "EazyDoctor Support".
6. Keep replies short — this is a mobile chat window, not an essay."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_doctors_facilities",
            "description": "Search doctors and facilities/clinics by name, specialty, disease, or city/area. Returns matching facilities with their doctors, facility_id and doctor_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Doctor name, specialty, disease, or facility name to search for."},
                    "city": {"type": "string", "description": "City or area to filter by, if the user mentioned one."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Books an appointment. Only call with confirm=true after the user has explicitly confirmed the booking details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "facility_id": {"type": "string", "description": "facility_id from a prior search result."},
                    "doctor_id": {"type": "string", "description": "doctor_id from a prior search result."},
                    "appointment_date": {"type": "string", "description": "Appointment date as YYYY-MM-DD."},
                    "payment_mode": {"type": "string", "enum": ["cash", "online"], "description": "How the patient will pay."},
                    "patient_name": {"type": "string"},
                    "patient_phone": {"type": "string"},
                    "patient_address": {"type": "string"},
                    "confirm": {"type": "boolean", "description": "Must be true — only set once the user has explicitly confirmed."},
                },
                "required": ["facility_id", "doctor_id", "appointment_date", "payment_mode", "patient_name", "patient_phone", "patient_address", "confirm"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancels one of the user's own bookings. Only call with confirm=true after the user has explicitly confirmed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string", "description": "booking_id of one of the user's own bookings, from the booking data provided."},
                    "confirm": {"type": "boolean", "description": "Must be true — only set once the user has explicitly confirmed."},
                },
                "required": ["booking_id", "confirm"],
            },
        },
    },
]


def _system_prompt(language: str, booking_context: str) -> str:
    return SYSTEM_PROMPT_TMPL.format(
        language=language, policy=POLICY_TEXT, escalate_tag=ESCALATE_TAG, booking_context=booking_context
    )


async def _run_search_doctors_facilities(db: AsyncSession, args: dict) -> dict:
    params = FacilitySearchParams(query=args.get("query"), city=args.get("city"))
    results = await facilities_service.search_facilities(db, params)
    results = results[:5]
    out = []
    for facility, distance in results:
        doctors = await facilities_service.list_doctors_for_facility(db, facility.id)
        out.append({
            "facility_id": str(facility.id),
            "facility_name": facility.name,
            "city": facility.city,
            "address": facility.address,
            "doctors": [
                {"doctor_id": str(d.id), "name": d.full_name, "specialty": d.specialty}
                for d in doctors[:8]
            ],
        })
    if not out:
        return {"results": [], "message": "No matching doctors or facilities found."}
    return {"results": out}


async def _run_book_appointment(db: AsyncSession, patient_id: uuid.UUID, args: dict) -> dict:
    if not args.get("confirm"):
        return {"error": "Booking not confirmed by user yet."}
    try:
        payload = BookingCreate(
            facility_id=uuid.UUID(args["facility_id"]),
            doctor_id=uuid.UUID(args["doctor_id"]),
            patient_name=args["patient_name"],
            patient_phone=args["patient_phone"],
            patient_address=args["patient_address"],
            appointment_date=args["appointment_date"],
            payment_mode=PaymentMode(args["payment_mode"]),
        )
        booking, _qr = await bookings_service.create_booking(db, patient_id, payload)
        return {
            "success": True,
            "booking_id": str(booking.id),
            "token_number": booking.token_number,
            "status": booking.status.value,
            "appointment_date": booking.appointment_date,
            "expected_time": booking.expected_time,
        }
    except HTTPException as exc:
        return {"error": exc.detail}
    except (KeyError, ValueError) as exc:
        return {"error": f"Invalid booking details: {exc}"}
    except Exception:
        logger.exception("bot book_appointment failed")
        return {"error": "Could not create the booking due to a system error."}


async def _run_cancel_appointment(db: AsyncSession, patient_id: uuid.UUID, args: dict) -> dict:
    if not args.get("confirm"):
        return {"error": "Cancellation not confirmed by user yet."}
    try:
        booking = await bookings_service.get_booking(db, uuid.UUID(args["booking_id"]))
        if booking.patient_id != patient_id:
            return {"error": "This booking does not belong to this user."}
        booking, refund_points, deduction_percent = await bookings_service.cancel_booking(db, booking)
        return {
            "success": True,
            "booking_id": str(booking.id),
            "status": booking.status.value,
            "refund_points": refund_points,
            "deduction_percent": deduction_percent,
        }
    except HTTPException as exc:
        return {"error": exc.detail}
    except (KeyError, ValueError) as exc:
        return {"error": f"Invalid request: {exc}"}
    except Exception:
        logger.exception("bot cancel_appointment failed")
        return {"error": "Could not cancel the booking due to a system error."}


async def _execute_tool_call(db: AsyncSession, patient_id: uuid.UUID, name: str, args: dict) -> dict:
    if name == "search_doctors_facilities":
        return await _run_search_doctors_facilities(db, args)
    if name == "book_appointment":
        return await _run_book_appointment(db, patient_id, args)
    if name == "cancel_appointment":
        return await _run_cancel_appointment(db, patient_id, args)
    return {"error": f"Unknown tool {name}"}


async def get_bot_reply(
    db: AsyncSession,
    patient_id: uuid.UUID,
    history: list[dict],
    language: str,
    booking_context: str = "",
) -> tuple[str, bool]:
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

    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for _round in range(MAX_TOOL_ROUNDS):
                payload = {
                    "model": settings.groq_model,
                    "messages": messages,
                    "tools": TOOLS,
                    "temperature": 0.3,
                    "max_completion_tokens": 400,
                }
                resp = await client.post(GROQ_URL, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.error("Groq call failed (%s): %s", resp.status_code, resp.text)
                    return ("Sorry, I couldn't process that. Connecting you to a support agent.", True)

                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    return ("Sorry, I couldn't process that. Connecting you to a support agent.", True)

                message = choices[0].get("message", {})
                tool_calls = message.get("tool_calls") or []

                if not tool_calls:
                    text = (message.get("content") or "").strip()
                    should_escalate = ESCALATE_TAG in text
                    clean_text = text.replace(ESCALATE_TAG, "").strip()
                    if not clean_text:
                        clean_text = "Connecting you to a support agent who can help further."
                    return clean_text, should_escalate

                # Model wants to call one or more tools — execute them
                # against the real service layer, then loop back with the
                # results so the model can produce its final reply.
                messages.append(message)
                for call in tool_calls:
                    fn = call.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = await _execute_tool_call(db, patient_id, name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(result),
                    })

            return ("Sorry, I couldn't complete that. Connecting you to a support agent.", True)
    except Exception:
        logger.exception("Groq call raised an exception")
        return ("Sorry, something went wrong. Connecting you to a support agent.", True)