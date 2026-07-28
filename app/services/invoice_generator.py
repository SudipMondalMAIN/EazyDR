"""
Invoice generation — builds a simple PDF receipt/invoice for a confirmed
booking using reportlab (already a dependency), then uploads it via
storage_service (Cloudinary/local — same abstraction used for photos) so we
get back a plain public URL. Business logic (bookings/service.py) only ever
calls `generate_and_upload_invoice`; nothing else should import reportlab
directly.
"""
import io
import logging
import uuid

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bookings.models import Booking
from app.services.storage_service import storage_service

logger = logging.getLogger("invoice_service")


def _build_invoice_pdf(
    booking: Booking,
    doctor_name: str,
    facility_name: str,
    facility_address: str,
) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4
    x = 20 * mm
    y = height - 25 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(x, y, "EazyDoctor — Booking Invoice")
    y -= 10 * mm

    c.setFont("Helvetica", 10)
    c.drawString(x, y, f"Invoice / Booking ID: {booking.id}")
    y -= 6 * mm
    c.drawString(x, y, f"Token number: #{booking.token_number}")
    y -= 6 * mm
    c.drawString(x, y, f"Status: {booking.status.value}")
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Appointment details")
    y -= 7 * mm
    c.setFont("Helvetica", 10)
    for line in [
        f"Patient: {booking.patient_name} ({booking.patient_phone})",
        f"Doctor: {doctor_name}",
        f"Facility: {facility_name}",
        f"Address: {facility_address}",
        f"Date: {booking.appointment_date}   Time: {booking.expected_time}",
    ]:
        c.drawString(x, y, line)
        y -= 6 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Payment")
    y -= 7 * mm
    c.setFont("Helvetica", 10)
    for line in [
        f"Payment mode: {booking.payment_mode.value}",
        f"Booking fee: Rs. {booking.booking_fee}",
    ]:
        c.drawString(x, y, line)
        y -= 6 * mm

    y -= 10 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(x, y, "This is a system-generated invoice and does not require a signature.")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()


async def generate_and_upload_invoice(
    db: AsyncSession,
    booking: Booking,
    doctor_name: str,
    facility_name: str,
    facility_address: str,
) -> str | None:
    """Generates the invoice PDF and uploads it, returning a public URL.
    Returns None (never raises) on any failure — invoice delivery is
    best-effort and must never break the booking flow."""
    try:
        pdf_bytes = _build_invoice_pdf(booking, doctor_name, facility_name, facility_address)
        file_obj = io.BytesIO(pdf_bytes)
        file_key = await storage_service.upload_file(
            file_obj, folder="invoices", public_id=f"invoice_{booking.id}_{uuid.uuid4().hex[:8]}"
        )
        return storage_service.get_public_url(file_key)
    except Exception:  # noqa: BLE001
        logger.exception("invoice generation/upload failed for booking %s", booking.id)
        return None