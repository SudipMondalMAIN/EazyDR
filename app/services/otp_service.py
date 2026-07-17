"""
Email OTP generation/verification. Used for Signup, Login, and Forgot
Password — no OTP is ever sent by SMS/mobile. OTPs are stored in Redis
(via cache_service) keyed by purpose+email, matching the storage/cache/
notification service pattern used elsewhere in this codebase.
"""
import logging
import secrets

from app.common.exceptions import BadRequestError
from app.core.config import settings
from app.services.cache_service import cache_service
from app.services.email_service import send_otp_email

logger = logging.getLogger("otp_service")

_VALID_PURPOSES = {"signup", "login", "forgot_password"}


def _otp_key(purpose: str, email: str) -> str:
    return f"otp:{purpose}:{email.lower()}"


def _cooldown_key(purpose: str, email: str) -> str:
    return f"otp_cooldown:{purpose}:{email.lower()}"


def _generate_otp() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))


async def request_otp(email: str, purpose: str) -> None:
    if purpose not in _VALID_PURPOSES:
        raise BadRequestError("Invalid OTP purpose")

    if await cache_service.get_json(_cooldown_key(purpose, email)):
        raise BadRequestError("Please wait before requesting another OTP")

    otp = _generate_otp()
    await cache_service.set_json(_otp_key(purpose, email), otp, settings.otp_expire_minutes * 60)
    await cache_service.set_json(_cooldown_key(purpose, email), True, settings.otp_resend_cooldown_seconds)

    sent = await send_otp_email(email, otp, purpose)
    if not sent:
        logger.error("Failed to send OTP email to %s for purpose=%s", email, purpose)


async def verify_otp(email: str, otp: str, purpose: str) -> None:
    if purpose not in _VALID_PURPOSES:
        raise BadRequestError("Invalid OTP purpose")

    key = _otp_key(purpose, email)
    stored = await cache_service.get_json(key)
    if not stored or stored != otp:
        raise BadRequestError("Invalid or expired OTP")

    await cache_service.delete(key)
