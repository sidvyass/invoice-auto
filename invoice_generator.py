#!/usr/bin/env python3
"""Generate one airline ticket invoice from interactive CLI prompts.

Python 3.10+. Install: uv sync. Run: uv run python invoice_generator.py

Layout coordinates, labels, and static business details were transcribed from
hi-06_9228 (2).pdf. No reference PDF is needed at runtime. No accounting system,
network call, spreadsheet import, or GST portal registration is included.
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

# Keep these values in one place. They are not repeated in each invoice input.
COMPANY = {
    "name": "IMPERIAL BUSINESS HOUSE",
    "address_lines": (
        "704, 7th floor,Indraprasth Corporates,",
        "Opp. Venus Atlantis,Anandnagar Cross Road,Prahladnagar,",
        "AHMEDABAD-380015 (India).",
    ),
    "website": "www.imperialbh.in",
    "phone": "079-66718822,66178844",
    "mobile": "+91-9998541097",
    "email": "imperialroutes@gmail.com",
    "gstin": "24ACYPV2536J1ZW",
    "pan": "ACYPV2536J",
    "bank_account_name": "IMPERIAL BUSINESS HOUSE",
    "bank_account_number": "50200003401615",
    "bank_name": "HDFC BANK",
    "bank_ifsc": "HDFC0000890",
    "bank_account_type": "CURRENT ACCOUNT",
    "bank_city": "AHMEDABAD 380015",
    "terms": (
        "# Subject to AHMEDABAD jurisdiction.",
        "# Without original invoice no refund is permissible.",
        "# Interest @ 24% will be charged on delayed payment.",
        "# Cheque to be drawn in our company name on presentation of invoice.",
        "# Kindly check all details carefully to avoid un-necessary complications.",
    ),
}

# The source PDF is exactly 595 x 841 points, rather than ReportLab's unrounded A4.
PAGE_WIDTH, PAGE_HEIGHT = 595.0, 841.0
LEFT, RIGHT = 44.6, 575.2
BODY_SIZE, BOLD_SIZE = 7.7, 7.3
MONEY_UNIT = Decimal("0.01")
RATE_UNIT = Decimal("0.001")
DEFAULT_STAMP = Path(__file__).resolve().parent / "assets" / "stamp.png"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class InvoiceError(ValueError):
    """Invalid invoice data or content that will not fit the fixed layout."""


@dataclass(frozen=True)
class FontSet:
    regular: str = "Times-Roman"
    bold: str = "Times-Bold"
    bold_italic: str = "Times-BoldItalic"


DEFAULT_FONTS = FontSet()


@dataclass(frozen=True)
class Ticket:
    issued_date: date
    travel_date: date
    passenger_name: str
    destination: str
    tbo_pnr: str
    riya_pnr: str
    net: Decimal
    processing_charges: Decimal
    gst_rate: Decimal
    seat_charge: Decimal
    seat_margin: Decimal
    seat_gross: Decimal | None
    company_name: str
    company_gstin: str
    remark: str

    @property
    def pnr(self) -> str:
        return self.tbo_pnr or self.riya_pnr

    @property
    def seat_amount(self) -> Decimal:
        return self.seat_gross if self.seat_gross is not None else self.seat_charge + self.seat_margin


@dataclass(frozen=True)
class Totals:
    net: Decimal
    seat_amount: Decimal
    ticket_cost: Decimal
    processing_charges: Decimal
    gst_rate: Decimal
    gst: Decimal
    net_amount: Decimal
    amount_in_words: str


def _check_fields(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvoiceError(f"{label} must be a JSON object.")
    missing = expected - value.keys()
    unexpected = value.keys() - expected
    if missing:
        raise InvoiceError(f"{label}: missing field(s): {', '.join(sorted(missing))}.")
    if unexpected:
        raise InvoiceError(f"{label}: unknown field(s): {', '.join(sorted(map(str, unexpected)))}.")
    return value


def _text(value: Any, label: str, *, empty_ok: bool = False) -> str:
    if not isinstance(value, str):
        raise InvoiceError(f"{label} must be a string.")
    if any(ord(c) < 32 for c in value):
        raise InvoiceError(f"{label} contains a control character or an unsupported line break.")
    if "\x7f" in value:
        raise InvoiceError(f"{label} contains an unsupported control character.")
    result = value.strip()
    if not result and not empty_ok:
        raise InvoiceError(f"{label} cannot be blank.")
    if len(result) > 4000:
        raise InvoiceError(f"{label} is too long.")
    return result


def _decimal(value: Any, label: str, unit: Decimal = MONEY_UNIT) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise InvoiceError(f"{label} must be a decimal string such as '7650.00', not a float.")
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or result >= Decimal("1000000000"):
            raise InvoiceError(f"{label} must be finite, nonnegative, and below 1,000,000,000.")
        rounded = result.quantize(unit, rounding=ROUND_HALF_UP)
        if rounded != result:
            raise InvoiceError(f"{label} may have at most {-unit.as_tuple().exponent} decimal places.")
        return rounded.copy_abs()  # Normalize a possible negative zero.
    except (InvalidOperation, ValueError, OverflowError) as exc:
        if isinstance(exc, InvoiceError):
            raise
        raise InvoiceError(f"{label} is not a valid decimal amount (do not include commas or currency symbols).") from exc


def _date(value: Any, label: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InvoiceError(f"{label} must use YYYY-MM-DD, for example 2026-09-21.")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvoiceError(f"{label} is not a valid calendar date.") from exc


def parse_ticket(data: dict[str, Any]) -> Ticket:
    """Validate one ticket and its selected GST rate."""
    fields = {"issued_date", "travel_date", "passenger_name", "destination", "tbo_pnr",
              "riya_pnr", "net", "processing_charges", "gst_rate", "seat_charge", "seat_margin", "seat_gross",
              "company_name", "company_gstin", "remark"}
    d = _check_fields(data, fields, "ticket")
    gstin = _text(d["company_gstin"], "company_gstin", empty_ok=True)
    if gstin and not re.fullmatch(r"[A-Z0-9]{15}", gstin):
        raise InvoiceError("company_gstin must be 15 uppercase letters/digits, or blank.")
    ticket = Ticket(
        issued_date=_date(d["issued_date"], "issued_date"),
        travel_date=_date(d["travel_date"], "travel_date"),
        passenger_name=_text(d["passenger_name"], "passenger_name"),
        destination=_text(d["destination"], "destination"),
        tbo_pnr=_text(d["tbo_pnr"], "tbo_pnr", empty_ok=True),
        riya_pnr=_text(d["riya_pnr"], "riya_pnr", empty_ok=True),
        net=_decimal(d["net"], "net"),
        processing_charges=_decimal(d["processing_charges"], "processing_charges"),
        gst_rate=_decimal(d["gst_rate"], "gst_rate", RATE_UNIT),
        seat_charge=_decimal(d["seat_charge"], "seat_charge"),
        seat_margin=_decimal(d["seat_margin"], "seat_margin"),
        seat_gross=None if d["seat_gross"] in (None, "") else _decimal(d["seat_gross"], "seat_gross"),
        company_name=_text(d["company_name"], "company_name"),
        company_gstin=gstin,
        remark=_text(d["remark"], "remark", empty_ok=True),
    )
    if not ticket.pnr:
        raise InvoiceError("Enter a TBO PNR or Riya PNR.")
    if ticket.gst_rate > 100:
        raise InvoiceError("gst_rate must be between 0 and 100 percent.")
    return ticket


_SMALL = (
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)
_TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def _integer_words(number: int) -> str:
    if number < 20:
        return _SMALL[number]
    if number < 100:
        return _TENS[number // 10] + (" " + _SMALL[number % 10] if number % 10 else "")
    for value, name in ((10000000, "Crore"), (100000, "Lakh"), (1000, "Thousand"), (100, "Hundred")):
        if number >= value:
            quotient, remainder = divmod(number, value)
            return _integer_words(quotient) + " " + name + (" " + _integer_words(remainder) if remainder else "")
    raise AssertionError("Unreachable number-to-words branch.")


def amount_in_words(amount: Decimal) -> str:
    """Indian currency wording; no extra dependency. Include paise when nonzero."""
    if not amount.is_finite() or amount < 0:
        raise InvoiceError("The amount in words requires a finite, nonnegative amount.")
    paise_total = int(amount.quantize(MONEY_UNIT, rounding=ROUND_HALF_UP) * 100)
    rupees, paise = divmod(paise_total, 100)
    result = "Rupees " + _integer_words(rupees)
    if paise:
        result += " and " + _integer_words(paise) + " Paise"
    return result + " Only"


def calculate_totals(ticket: Ticket) -> Totals:
    ticket_cost = ticket.net + ticket.seat_amount
    gst = (ticket.processing_charges * ticket.gst_rate / Decimal("100")).quantize(
        MONEY_UNIT, rounding=ROUND_HALF_UP
    )
    total = ticket_cost + ticket.processing_charges + gst
    return Totals(ticket.net, ticket.seat_amount, ticket_cost, ticket.processing_charges,
                  ticket.gst_rate, gst, total, amount_in_words(total))


def register_fonts(regular_path: Path, bold_path: Path, italic_path: Path | None = None) -> FontSet:
    """Optional: use locally licensed TTF fonts. No font files are bundled."""
    try:
        for name, path in (("InvoiceRegular", regular_path), ("InvoiceBold", bold_path)):
            pdfmetrics.registerFont(TTFont(name, str(path)))
        if italic_path is not None:
            pdfmetrics.registerFont(TTFont("InvoiceBoldItalic", str(italic_path)))
        return FontSet("InvoiceRegular", "InvoiceBold", "InvoiceBoldItalic" if italic_path else "InvoiceBold")
    except Exception as exc:
        raise InvoiceError(f"Could not load the supplied TrueType fonts: {exc}") from exc


def _check_glyphs(text: str, font_name: str) -> None:
    face = pdfmetrics.getFont(font_name).face
    if hasattr(face, "charToGlyph"):
        bad = [ch for ch in text if ord(ch) not in face.charToGlyph]
    else:
        try:
            encoded = text.encode("cp1252")
        except UnicodeEncodeError as exc:
            raise InvoiceError("A character is not supported by the default Times font. Supply suitable local TTF fonts.") from exc
        encoding = pdfmetrics.getFont(font_name).encoding.vector
        bad = [chr(ch) for ch in encoded if not encoding[ch]]
    if bad:
        raise InvoiceError(f"Font {font_name} cannot display {bad[0]!r}; supply a font covering this character.")


class _Painter:
    """All y coordinates are measured DOWN from the top, matching the reference."""
    def __init__(self, canvas: Canvas, fonts: FontSet) -> None:
        self.c, self.fonts = canvas, fonts

    def text(self, x: float, top: float, text: str, *, size: float = BODY_SIZE,
             font: str | None = None, max_width: float | None = None,
             align: str = "left", field: str = "text") -> None:
        font = font or self.fonts.regular
        _check_glyphs(text, font)
        width = pdfmetrics.stringWidth(text, font, size)
        if max_width is not None and width > max_width + 0.01:
            raise InvoiceError(f"{field} is too wide for the fixed layout ({width:.1f} pt; maximum {max_width:.1f} pt). Shorten it.")
        if align == "right":
            x -= width
        elif align == "center":
            x -= width / 2
        self.c.setFillGray(0)
        self.c.setFont(font, size)
        self.c.drawString(x, PAGE_HEIGHT - top, text)

    def rule(self, x1: float, y1: float, x2: float, y2: float, width: float = 0) -> None:
        self.c.setStrokeGray(0)
        self.c.setLineWidth(width)
        self.c.line(x1, PAGE_HEIGHT - y1, x2, PAGE_HEIGHT - y2)

    def fill(self, x: float, top: float, width: float, height: float, gray: float) -> None:
        self.c.setFillGray(gray)
        self.c.rect(x, PAGE_HEIGHT - top - height, width, height, stroke=0, fill=1)

    def wrap(self, text: str, max_width: float, field: str) -> list[str]:
        """Preserve explicit newlines, and wrap additional text without shrinking."""
        lines: list[str] = []
        _check_glyphs(text.replace("\n", ""), self.fonts.regular)
        for paragraph in text.split("\n"):
            line = ""
            for word in paragraph.split():
                if pdfmetrics.stringWidth(word, self.fonts.regular, BODY_SIZE) > max_width:
                    raise InvoiceError(f"{field} contains a word too wide for the Particulars column.")
                candidate = f"{line} {word}".strip()
                if pdfmetrics.stringWidth(candidate, self.fonts.regular, BODY_SIZE) <= max_width:
                    line = candidate
                else:
                    lines.append(line)
                    line = word
            lines.append(line)
        return lines


def build_pdf(ticket: Ticket, totals: Totals, invoice_number: str, *, fonts: FontSet = DEFAULT_FONTS,
              stamp_path: Path | None = DEFAULT_STAMP) -> bytes:
    """Render in memory. Overflow is an error, not a clipped or reformatted PDF."""
    output = BytesIO()
    c = Canvas(output, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), pageCompression=1)
    c.setTitle(f"Air Ticket Invoice {invoice_number}")
    c.setAuthor(COMPANY["name"])
    c.setSubject("Air ticket invoice")
    p = _Painter(c, fonts)

    # Gray bands, using the dimensions and gray levels from the source PDF.
    p.fill(LEFT, 15.6, RIGHT - LEFT, 15.4, 0.753)
    for top, height in ((33.1, 10.65), (44.3, 10.65), (55.5, 10.5)):
        p.fill(377.1, top, 8.4, height, 0.753)
    p.fill(377.1, 81.0, 198.1, 14.25, 0.875)
    for x, width in ((44.6, 13.3), (59.3, 122.5), (182.5, 70.0), (253.0, 91.0),
                     (345.6, 74.9), (421.2, 86.5), (509.4, 65.8)):
        p.fill(x, 148.9, width, 11.2, 0.875)
    p.fill(346.3, 266.2, 161.0, 10.5, 0.875)
    p.fill(509.4, 266.2, 65.8, 10.5, 0.875)
    p.fill(LEFT, 278.1, RIGHT - LEFT, 10.5, 0.875)

    # All boundaries remain fixed regardless of input length.
    for y, width in ((79.6, 0.5), (96.4, 0), (134.2, 0), (147.5, 0),
                     (160.8, 0.5), (242.4, 0.5), (264.8, 0), (277.4, 0),
                     (289.4, 0), (312.4, 0), (388.0, 0)):
        p.rule(LEFT, y, RIGHT, y, width)
    p.rule(375.0, 79.6, 375.0, 146.8)
    p.rule(344.9, 242.4, 344.9, 277.4)
    p.rule(508.3, 242.4, 508.3, 277.4)
    p.rule(345.25, 312.4, 345.25, 388.0)

    # Company header and contact block.
    p.text(LEFT, 27.95, COMPANY["name"], size=11.1, max_width=385, field="COMPANY.name")
    p.text(RIGHT, 26.25, COMPANY["website"], align="right", max_width=130, field="COMPANY.website")
    for text, top in zip(COMPANY["address_lines"], (41.65, 52.85, 64.05)):
        p.text(LEFT, top, text, max_width=328, field="COMPANY.address_lines")
    for symbol, key, top in (("P", "phone", 41.65), ("M", "mobile", 52.85), ("@", "email", 64.05)):
        p.text(381.3, top - 0.05, symbol, align="center", max_width=8.4)
        p.text(386.2, top, COMPANY[key], max_width=RIGHT - 386.2, field=f"COMPANY.{key}")
    p.text(LEFT, 76.25, f"GST No. {COMPANY['gstin']}", max_width=328)
    p.text(377.1, 76.25, f"PAN No. {COMPANY['pan']}", max_width=198.1)

    # Buyer and ticket identity. Blank address space is retained.
    p.text(LEFT, 90.25, "To,")
    p.text(59.3, 90.85, ticket.company_name, font=fonts.bold, size=BOLD_SIZE,
           max_width=313, field="company_name")
    p.text(476.1, 91.45, "Air Ticket Invoice", size=9.4, align="center", max_width=190)
    p.text(377.1, 107.0, "Invoice")
    p.text(412.45, 107.0, ":")
    p.text(416.3, 107.0, invoice_number, font=fonts.bold, size=BOLD_SIZE,
           max_width=107, field="invoice_number")
    display_date = f"{ticket.issued_date.day:02d} {MONTHS[ticket.issued_date.month - 1]} {ticket.issued_date.year}"
    p.text(RIGHT, 107.6, display_date, align="right", font=fonts.bold, size=BOLD_SIZE, max_width=50)
    if ticket.company_gstin:
        p.text(59.3, 130.85, f"GST No :{ticket.company_gstin}", max_width=313, field="company_gstin")
    p.text(377.1, 130.85, f"Travel: {ticket.travel_date:%d/%m/%Y}", max_width=198.1)
    # The model invoice has one compact ticket row. Only collected fields get columns.
    for x, label in ((46.0, "Sr."), (60.0, "Passenger"), (184.0, "Sector"),
                     (254.0, "Travel Date"), (347.0, "PNR")):
        p.text(x, 157.4, label)
    p.text(507.3, 157.4, "Basic", align="right")
    p.text(RIGHT, 157.4, "Total", align="right")
    p.text(46.0, 170.05, "1", max_width=11)
    p.text(60.0, 170.05, ticket.passenger_name, max_width=121, field="passenger_name")
    p.text(184.0, 170.05, ticket.destination, max_width=68, field="destination")
    p.text(254.0, 170.05, f"{ticket.travel_date:%d %b %Y}", max_width=89)
    p.text(507.3, 170.05, f"{totals.net:.2f}", align="right", max_width=85, field="basic fare")
    p.text(RIGHT, 170.05, f"{totals.ticket_cost:.2f}", align="right", max_width=65, field="ticket cost")
    if ticket.tbo_pnr and ticket.riya_pnr:
        p.text(347.0, 170.05, f"TBO: {ticket.tbo_pnr}", max_width=73, field="TBO PNR")
        p.text(347.0, 180.6, f"Riya: {ticket.riya_pnr}", max_width=73, field="Riya PNR")
    else:
        p.text(347.0, 170.05, ticket.pnr, max_width=73, field="PNR")
    if totals.seat_amount:
        p.text(60.0, 191.2, f"Seat amount included in ticket cost: {totals.seat_amount:.2f}",
               max_width=283, field="seat amount note")
    if ticket.remark:
        lines = p.wrap(ticket.remark, 450.0, "remark")
        if len(lines) > 3:
            raise InvoiceError("remark will not fit in the fixed layout. Shorten it.")
        for index, line in enumerate(lines):
            p.text(60.0, 201.8 + index * 10.55, line, max_width=450, field="remark")

    # Existing summary area now shows the ticket's actual billed components.
    p.text(346.3, 250.9, "Add")
    p.text(368.7, 250.9, "Processing Charges")
    p.text(RIGHT, 250.95, f"{totals.processing_charges:.2f}", align="right", max_width=65, field="processing charges")
    p.text(346.3, 262.1, "Add")
    p.text(368.7, 262.15, "GST")
    p.text(507.3, 262.15, f"{totals.gst_rate:.3f}%", align="right", max_width=80)
    p.text(RIGHT, 262.15, f"{totals.gst:.2f}", align="right", max_width=65, field="GST amount")
    p.text(346.3, 274.7, "Net Invoice Amount")
    p.text(RIGHT, 274.75, f"{totals.net_amount:.2f}", align="right", max_width=65, field="net amount")
    p.text(LEFT, 286.65, totals.amount_in_words, max_width=RIGHT - LEFT, field="amount in words")

    bank_line_1 = (f"NAME OF THE ACCOUNT:{COMPANY['bank_account_name']},ACCOUNT NUMBER "
                   f"{COMPANY['bank_account_number']},BANK NAME:{COMPANY['bank_name']} IFSC")
    bank_line_2 = f"CODE:{COMPANY['bank_ifsc']};{COMPANY['bank_account_type']};{COMPANY['bank_city']}"
    for text, y in ((bank_line_1, 299.2), (bank_line_2, 310.35)):
        p.text(LEFT, y, text, font=fonts.bold, size=BOLD_SIZE, max_width=RIGHT - LEFT, field="bank details")

    p.text(LEFT, 321.25, "Terms :", font=fonts.bold_italic, size=6.5)
    p.text(344.15, 320.8, "E.  & O.  E.", size=6.8, align="right")
    for term, y in zip(COMPANY["terms"], (330.5, 339.7, 348.8, 357.9, 367.0)):
        p.text(LEFT, y, term, size=6.8, max_width=298, field="COMPANY.terms")
    p.text(RIGHT, 323.05, f"for {COMPANY['name']}", align="right", max_width=226, field="company sign-off")
    if stamp_path is not None:
        path = Path(stamp_path)
        if not path.is_file():
            raise InvoiceError(f"Missing stamp image: {path}. Keep assets/stamp.png beside the script, or use --no-stamp.")
        try:
            c.drawImage(ImageReader(str(path)), 467.2, PAGE_HEIGHT - 370.03006,
                        width=107.47754, height=38.03006, mask="auto")
        except Exception as exc:
            raise InvoiceError(f"Cannot read stamp image {path}: {exc}") from exc
    p.text(LEFT, 384.6, "Receiver's Signature")
    p.text(RIGHT, 384.6, "Authorized Signatory", align="right")
    p.text(200.05, 396.4, "This is a Computer generated document and does not require any signature.",
           size=6.8, max_width=RIGHT - 200.05)
    c.showPage()
    c.save()
    return output.getvalue()


def _write_output(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)


def new_invoice_number(issued_date: date) -> str:
    return f"AT{issued_date:%y%m%d}-{uuid.uuid4().hex[:10].upper()}"


def generate_invoice(ticket: Ticket, output_path: str | Path, invoice_number: str, *,
                     fonts: FontSet = DEFAULT_FONTS, stamp_path: Path | None = DEFAULT_STAMP) -> Totals:
    """Render one ticket and create a new PDF without overwriting an existing invoice."""
    totals = calculate_totals(ticket)
    content = build_pdf(ticket, totals, invoice_number, fonts=fonts, stamp_path=stamp_path)
    _write_output(Path(output_path), content)
    return totals


def prompt_ticket(prompt: Any = None) -> Ticket:
    """Collect exactly one ticket; blank optional amounts mean zero."""
    prompt = prompt or input
    def ask(label: str, *, optional: bool = False, default: str = "") -> str:
        suffix = " (optional)" if optional else ""
        value = prompt(f"{label}{suffix}: ").strip()
        return value or default

    print("Enter one issued airline ticket. Dates use YYYY-MM-DD; amounts use rupees.")
    data = {
        "issued_date": ask("Issued date"),
        "travel_date": ask("Travel date"),
        "passenger_name": ask("Passenger name"),
        "destination": ask("Destination / route"),
        "tbo_pnr": ask("TBO PNR", optional=True),
        "riya_pnr": ask("Riya PNR", optional=True),
        "net": ask("NET"),
        "processing_charges": ask("Processing Charges", optional=True, default="0.00"),
        "gst_rate": ask("GST rate (%)", optional=True, default="18"),
        "seat_charge": ask("Seat charge", optional=True, default="0.00"),
        "seat_margin": ask("Seat margin", optional=True, default="0.00"),
        "seat_gross": ask("Seat gross", optional=True),
        "company_name": ask("Company name"),
        "company_gstin": ask("Company GSTIN", optional=True),
        "remark": ask("Remark", optional=True),
    }
    return parse_ticket(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, default=Path("invoices"), help="Directory for generated PDFs")
    parser.add_argument("--no-stamp", action="store_true", help="Omit the supplied stamp/signature image")
    parser.add_argument("--font-regular", type=Path, help="Optional locally licensed regular TTF")
    parser.add_argument("--font-bold", type=Path, help="Optional locally licensed bold TTF")
    parser.add_argument("--font-bold-italic", type=Path, help="Optional matching bold-italic TTF")
    args = parser.parse_args(argv)
    path: Path | None = None
    try:
        if bool(args.font_regular) != bool(args.font_bold):
            raise InvoiceError("Supply both --font-regular and --font-bold, or neither.")
        if args.font_bold_italic and not args.font_regular:
            raise InvoiceError("--font-bold-italic also requires --font-regular and --font-bold.")
        fonts = register_fonts(args.font_regular, args.font_bold, args.font_bold_italic) if args.font_regular else DEFAULT_FONTS
        ticket = prompt_ticket()
        totals = calculate_totals(ticket)
        print(f"Ticket cost: {totals.ticket_cost:.2f} | Processing Charges: {totals.processing_charges:.2f} | GST ({totals.gst_rate:.3f}%): {totals.gst:.2f} | Total: {totals.net_amount:.2f}")
        invoice_number = new_invoice_number(ticket.issued_date)
        path = args.output_dir / f"invoice_{invoice_number}.pdf"
        generate_invoice(ticket, path, invoice_number, fonts=fonts,
                         stamp_path=None if args.no_stamp else DEFAULT_STAMP)
    except FileExistsError:
        print(f"Error: {path} already exists. No file was replaced; run again for a new invoice number.", file=sys.stderr)
        return 2
    except (InvoiceError, OSError, UnicodeError, EOFError, KeyboardInterrupt) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Invoice number: {invoice_number}")
    print(f"Created: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
