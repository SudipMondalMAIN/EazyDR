"""
Email Service abstraction — all OTP delivery (signup/login/forgot-password)
and transactional notifications go through here via Brevo's HTTP API.
Business logic calls `email_service.send_email(...)` only; if the provider
is ever swapped, only this file changes. No SMS provider is used anywhere
in this codebase.
"""
import logging
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings

logger = logging.getLogger("email_service")

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


class EmailService(ABC):
    @abstractmethod
    async def send_email(self, to_email: str, subject: str, html_content: str) -> bool:
        ...


class BrevoEmailService(EmailService):
    async def send_email(self, to_email: str, subject: str, html_content: str) -> bool:
        payload = {
            "sender": {"name": settings.brevo_sender_name, "email": settings.brevo_sender_email},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_content,
        }
        headers = {
            "api-key": settings.brevo_api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(BREVO_SEND_URL, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error("Brevo send failed (%s): %s", resp.status_code, resp.text)
                return False
            return True
        except Exception:
            logger.exception("Brevo email send failed for %s", to_email)
            return False


class NoopEmailService(EmailService):
    """Used when BREVO_API_KEY isn't configured yet (local dev) so the app
    still boots and auth/notification flows can be tested end-to-end."""

    async def send_email(self, to_email: str, subject: str, html_content: str) -> bool:
        logger.info("NOOP email -> %s: %s\n%s", to_email, subject, html_content)
        return True


def get_email_service() -> EmailService:
    if settings.brevo_api_key:
        return BrevoEmailService()
    return NoopEmailService()


email_service = get_email_service()


async def send_otp_email(to_email: str, otp: str, purpose: str) -> bool:
    purpose_copy = {
        "signup": "Verify your email to complete signup",
        "login": "Your login verification code",
        "forgot_password": "Reset your password",
    }.get(purpose, "Your verification code")

    subject = f"EazyDoctor: {purpose_copy}"
    html_content = f"""
    <div style="font-family:Arial,sans-serif;font-size:15px;color:#222;">
      <p>{purpose_copy}.</p>
      <p style="font-size:28px;font-weight:bold;letter-spacing:4px;">{otp}</p>
      <p>This code expires in {settings.otp_expire_minutes} minutes. If you did not request this, you can ignore this email.</p>
    </div>
    """
    return await email_service.send_email(to_email, subject, html_content)


async def send_notification_email(to_email: str, subject: str, message: str) -> bool:
    """Generic transactional notification email (booking confirmation,
    cancellation, queue updates, reminders, account notices, etc.)."""
    html_content = f"""
    <div style="font-family:Arial,sans-serif;font-size:15px;color:#222;">
      <p>{message}</p>
    </div>
    """
    return await email_service.send_email(to_email, subject, html_content)
