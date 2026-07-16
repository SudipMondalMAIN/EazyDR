"""PDF generation for the Admin Booking export feature.

Kept isolated from admin/service.py so booking, payment, auth and queue
logic are never touched — this module only formats already-fetched rows.
"""
import io
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

_STYLES = getSampleStyleSheet()
_TITLE_STYLE = ParagraphStyle(
    "ExportTitle", parent=_STYLES["Heading1"], fontSize=16, spaceAfter=2, textColor=colors.HexColor("#0F172A")
)
_SUBTITLE_STYLE = ParagraphStyle(
    "ExportSubtitle", parent=_STYLES["Normal"], fontSize=9, textColor=colors.HexColor("#475569")
)
_CELL_STYLE = ParagraphStyle("Cell", parent=_STYLES["Normal"], fontSize=7.5, leading=9)
_HEADER_CELL_STYLE = ParagraphStyle(
    "HeaderCell", parent=_STYLES["Normal"], fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold"
)

_COLUMN_HEADERS = [
    "Booking ID",
    "Patient Name",
    "Phone",
    "Doctor",
    "Facility",
    "Booking Time",
    "Token #",
    "Status",
    "Payment Mode",
    "Fee",
]

# Relative column widths that sum to the printable A4 width (in mm).
_COLUMN_WIDTHS_MM = [22, 24, 20, 24, 24, 26, 12, 18, 18, 14]


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748B"))
    page_width, _ = A4
    canvas.drawRightString(page_width - 15 * mm, 10 * mm, f"Page {doc.page}")
    canvas.drawString(15 * mm, 10 * mm, "EazyDR — Admin Booking Export")
    canvas.restoreState()


def _build_filters_text(filters: dict) -> str:
    parts = []
    if filters.get("date"):
        parts.append(f"Date: {filters['date']}")
    if filters.get("date_from") or filters.get("date_to"):
        parts.append(f"Range: {filters.get('date_from') or '—'} to {filters.get('date_to') or '—'}")
    if filters.get("doctor_name"):
        parts.append(f"Doctor: {filters['doctor_name']}")
    if filters.get("facility_name"):
        parts.append(f"Facility: {filters['facility_name']}")
    if filters.get("status"):
        parts.append(f"Status: {filters['status']}")
    return " | ".join(parts) if parts else "No filters applied (all bookings)"


def generate_bookings_pdf(rows: Sequence[dict], filters: dict, generated_at: str) -> bytes:
    """Renders booking rows into a professional A4 PDF with automatic page
    breaks and page numbers. Returns the raw PDF bytes.

    `rows` is a list of plain dicts with the ten required export fields, so
    this module has no dependency on ORM/ORM-session state and can never
    accidentally mutate booking, payment, auth, or queue records.
    """
    buffer = io.BytesIO()
    page_width, page_height = A4
    margin = 15 * mm

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title="Admin Booking Export",
    )
    frame = Frame(
        margin, margin, page_width - 2 * margin, page_height - 2 * margin, id="main_frame"
    )
    doc.addPageTemplates([PageTemplate(id="export", frames=[frame], onPage=_footer)])

    story = []
    story.append(Paragraph("Admin Booking Export", _TITLE_STYLE))
    story.append(Paragraph(f"Generated: {generated_at}", _SUBTITLE_STYLE))
    story.append(Paragraph(_build_filters_text(filters), _SUBTITLE_STYLE))
    story.append(Paragraph(f"Total records: {len(rows)}", _SUBTITLE_STYLE))
    story.append(Spacer(1, 6 * mm))

    header_row = [Paragraph(h, _HEADER_CELL_STYLE) for h in _COLUMN_HEADERS]
    table_data = [header_row]

    for row in rows:
        table_data.append(
            [
                Paragraph(str(row.get("booking_id", "")), _CELL_STYLE),
                Paragraph(str(row.get("patient_name", "")), _CELL_STYLE),
                Paragraph(str(row.get("phone", "")), _CELL_STYLE),
                Paragraph(str(row.get("doctor", "")), _CELL_STYLE),
                Paragraph(str(row.get("facility", "")), _CELL_STYLE),
                Paragraph(str(row.get("booking_time", "")), _CELL_STYLE),
                Paragraph(str(row.get("token_number", "")), _CELL_STYLE),
                Paragraph(str(row.get("status", "")), _CELL_STYLE),
                Paragraph(str(row.get("payment_mode", "")), _CELL_STYLE),
                Paragraph(str(row.get("booking_fee", "")), _CELL_STYLE),
            ]
        )

    col_widths = [w * mm for w in _COLUMN_WIDTHS_MM]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)

    if not rows:
        story.append(Spacer(1, 8 * mm))
        story.append(Paragraph("No bookings match the selected filters.", _SUBTITLE_STYLE))

    doc.build(story)
    return buffer.getvalue()
