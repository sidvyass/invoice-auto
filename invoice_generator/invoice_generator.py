#!/usr/bin/env python3
"""Generate a fixed-layout hotel invoice using ReportLab.

Python 3.10+. Install: python -m pip install -r requirements.txt
Run: python invoice_generator.py sample_invoice.json --output invoice.pdf

Layout coordinates, labels, and static business details were transcribed from
hi-06_9228 (2).pdf. No reference PDF is needed at runtime. No accounting system,
network call, invoice-number allocation, or GST portal registration is included.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
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
MONEY_UNIT, RATE_UNIT = Decimal("0.01"), Decimal("0.001")
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
class LineItem:
    voucher: str
    description: str
    check_in: date
    check_out: date
    rooms: int
    rate: Decimal

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @property
    def amount(self) -> Decimal:
        # Contract: rate is the price per room per night; no tax is added here.
        return (self.rate * self.rooms * self.nights).quantize(MONEY_UNIT)


@dataclass(frozen=True)
class Invoice:
    invoice_number: str
    invoice_date: date
    customer_name: str
    customer_gstin: str
    place_of_supply: str
    state_code: str
    guest_name: str
    hsn_sac_code: str
    items: tuple[LineItem, ...]
    other_charges: Decimal
    igst_rate: Decimal
    igst_taxable_amount: Decimal
    internal_id: str


@dataclass(frozen=True)
class Totals:
    line_amounts: tuple[Decimal, ...]
    subtotal: Decimal
    other_charges: Decimal
    igst: Decimal
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


def _text(value: Any, label: str, *, empty_ok: bool = False, multiline: bool = False) -> str:
    if not isinstance(value, str):
        raise InvoiceError(f"{label} must be a string.")
    if any(ord(c) < 32 and not (multiline and c == "\n") for c in value):
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
    # Decimal strings are preferred. JSON numbers are also read as Decimal.
    # Reject Python floats at the programmatic boundary to avoid float artifacts.
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise InvoiceError(f"{label} must be a decimal string such as '7650.00', not a float.")
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or result >= Decimal("1000000000"):
            raise InvoiceError(f"{label} must be finite, nonnegative, and below 1,000,000,000.")
        rounded = result.quantize(unit, rounding=ROUND_HALF_UP)
        if rounded != result:
            places = -unit.as_tuple().exponent
            raise InvoiceError(f"{label} may have at most {places} decimal places.")
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


def parse_invoice(data: dict[str, Any]) -> Invoice:
    """Validate the complete input; reject typos, ambiguous numbers, and bad dates."""
    fields = {
        "invoice_number", "invoice_date", "customer_name", "customer_gstin",
        "place_of_supply", "state_code", "guest_name", "hsn_sac_code", "items",
        "other_charges", "igst_rate", "igst_taxable_amount", "internal_id",
    }
    d = _check_fields(data, fields, "invoice")
    if not isinstance(d["items"], list) or not d["items"]:
        raise InvoiceError("items must be a nonempty list.")
    if len(d["items"]) > 20:
        raise InvoiceError("Too many items for this fixed one-page layout.")
    items: list[LineItem] = []
    item_fields = {"voucher", "description", "check_in", "check_out", "rooms", "rate"}
    for index, raw in enumerate(d["items"]):
        label = f"items[{index}]"
        row = _check_fields(raw, item_fields, label)
        check_in = _date(row["check_in"], f"{label}.check_in")
        check_out = _date(row["check_out"], f"{label}.check_out")
        if check_out <= check_in:
            raise InvoiceError(f"{label}.check_out must be after check_in (at least one night).")
        rooms = row["rooms"]
        if type(rooms) is not int or not 1 <= rooms <= 9999:
            raise InvoiceError(f"{label}.rooms must be a whole number from 1 to 9999.")
        items.append(LineItem(
            voucher=_text(row["voucher"], f"{label}.voucher"),
            description=_text(row["description"], f"{label}.description", multiline=True),
            check_in=check_in, check_out=check_out, rooms=rooms,
            rate=_decimal(row["rate"], f"{label}.rate"),
        ))
    state = _text(d["state_code"], "state_code")
    if not re.fullmatch(r"\d{2}", state):
        raise InvoiceError("state_code must be a two-digit string, for example '19' or '07'.")
    gstin = _text(d["customer_gstin"], "customer_gstin", empty_ok=True)
    if gstin and not re.fullmatch(r"[A-Z0-9]{15}", gstin):
        raise InvoiceError("customer_gstin must be 15 uppercase letters/digits, or an empty string.")
    hsn = _text(d["hsn_sac_code"], "hsn_sac_code")
    if not re.fullmatch(r"\d{4,8}", hsn):
        raise InvoiceError("hsn_sac_code must be a string of 4 to 8 digits.")
    igst_rate = _decimal(d["igst_rate"], "igst_rate", RATE_UNIT)
    if igst_rate > 100:
        raise InvoiceError("igst_rate must be between 0 and 100 (18 means 18%, not 0.18).")
    invoice = Invoice(
        invoice_number=_text(d["invoice_number"], "invoice_number"),
        invoice_date=_date(d["invoice_date"], "invoice_date"),
        customer_name=_text(d["customer_name"], "customer_name"),
        customer_gstin=gstin,
        place_of_supply=_text(d["place_of_supply"], "place_of_supply"),
        state_code=state,
        guest_name=_text(d["guest_name"], "guest_name"),
        hsn_sac_code=hsn,
        items=tuple(items),
        other_charges=_decimal(d["other_charges"], "other_charges"),
        igst_rate=igst_rate,
        igst_taxable_amount=_decimal(d["igst_taxable_amount"], "igst_taxable_amount"),
        internal_id=_text(d["internal_id"], "internal_id"),
    )
    pre_tax_total = sum((item.amount for item in invoice.items), Decimal("0.00")) + invoice.other_charges
    if invoice.igst_taxable_amount > pre_tax_total:
        raise InvoiceError("igst_taxable_amount cannot exceed the item subtotal plus other_charges.")
    return invoice


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


def calculate_totals(invoice: Invoice) -> Totals:
    amounts = tuple(item.amount for item in invoice.items)
    subtotal = sum(amounts, Decimal("0.00"))
    # Explicit taxable base: NEVER assume that 18% applies to the whole invoice.
    tax = (invoice.igst_taxable_amount * invoice.igst_rate / Decimal("100")).quantize(
        MONEY_UNIT, rounding=ROUND_HALF_UP
    )
    total = subtotal + invoice.other_charges + tax
    return Totals(amounts, subtotal, invoice.other_charges, tax, total, amount_in_words(total))


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


def build_pdf(invoice: Invoice, totals: Totals, *, fonts: FontSet = DEFAULT_FONTS,
              stamp_path: Path | None = DEFAULT_STAMP) -> bytes:
    """Render in memory. Overflow is an error, not a clipped or reformatted PDF."""
    output = BytesIO()
    c = Canvas(output, pagesize=(PAGE_WIDTH, PAGE_HEIGHT), pageCompression=1)
    c.setTitle(f"Hotel Invoice {invoice.invoice_number}")
    c.setAuthor(COMPANY["name"])
    c.setSubject("Hotel invoice")
    p = _Painter(c, fonts)

    # Gray bands, using the dimensions and gray levels from the source PDF.
    p.fill(LEFT, 15.6, RIGHT - LEFT, 15.4, 0.753)
    for top, height in ((33.1, 10.65), (44.3, 10.65), (55.5, 10.5)):
        p.fill(377.1, top, 8.4, height, 0.753)
    p.fill(377.1, 81.0, 198.1, 14.25, 0.875)
    for x, width in ((44.6, 46.9), (92.2, 230.3), (323.2, 24.5), (348.4, 22.4),
                     (371.5, 41.3), (413.5, 28.0), (509.4, 65.8)):
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

    # Buyer, invoice identity, guest, and SAC code. Blank address space is retained.
    p.text(LEFT, 90.25, "To,")
    p.text(59.3, 90.85, invoice.customer_name, font=fonts.bold, size=BOLD_SIZE,
           max_width=313, field="customer_name")
    p.text(476.1, 91.45, "Hotel Invoice", size=9.4, align="center", max_width=190)
    p.text(377.1, 107.0, "Invoice")
    p.text(412.45, 107.0, ":")
    p.text(416.3, 107.0, invoice.invoice_number, font=fonts.bold, size=BOLD_SIZE,
           max_width=107, field="invoice_number")
    display_date = f"{invoice.invoice_date.day:02d} {MONTHS[invoice.invoice_date.month - 1]} {invoice.invoice_date.year}"
    p.text(RIGHT, 107.6, display_date, align="right", font=fonts.bold, size=BOLD_SIZE, max_width=50)
    gst_line = f"GST No :{invoice.customer_gstin}, POS :{invoice.place_of_supply}, State Code : {invoice.state_code}"
    p.text(59.3, 130.85, gst_line, max_width=313, field="customer GST / place of supply")
    p.text(377.1, 130.85, f"HSN/SAC Code: {invoice.hsn_sac_code}", max_width=198.1)
    p.text(LEFT, 144.1, "Guest")
    p.text(69.45, 144.1, f": {invoice.guest_name}", max_width=303, field="guest_name")

    # Item table: the source's Tax % column is intentionally blank.
    for x, text in ((LEFT, "Voucher"), (92.2, "Particulars"), (325.25, "Ngt/s"), (349.6, "Rm/s")):
        p.text(x, 157.4, text)
    p.text(412.8, 157.4, "Rate", align="right")
    p.text(441.5, 157.4, "Tax %", align="right")
    p.text(RIGHT, 157.4, "Amount", align="right")
    top, leading = 170.0, 10.55
    for index, (item, amount) in enumerate(zip(invoice.items, totals.line_amounts)):
        lines = p.wrap(item.description, 225.0, f"items[{index}].description")
        date_top = top + len(lines) * leading + 0.05
        if date_top > 238.0:
            raise InvoiceError(f"items[{index}] will not fit above the totals. This template never adds pages or moves the footer.")
        p.text(LEFT, top + 0.05, item.voucher, max_width=44.9, field=f"items[{index}].voucher")
        for offset, line in enumerate(lines):
            p.text(92.2, top + offset * leading, line, max_width=225, field=f"items[{index}].description")
        p.text(335.4, top + 0.05, str(item.nights), align="center", max_width=22, field="nights")
        p.text(359.6, top + 0.05, str(item.rooms), align="center", max_width=20, field="rooms")
        p.text(412.8, top + 0.05, f"{item.rate:.2f}", align="right", max_width=40, field="rate")
        p.text(RIGHT, top + 0.05, f"{amount:.2f}", align="right", max_width=65, field="line amount")
        stay = f"Check in: {item.check_in:%d/%m/%Y} Check out: {item.check_out:%d/%m/%Y}"
        p.text(92.2, date_top, stay, max_width=225, field="stay dates")
        top = date_top + leading + 5.0

    # Footer calculations. The taxable base itself is deliberately not printed.
    p.text(346.3, 250.9, "Add")
    p.text(368.7, 250.9, "Other Charges")
    p.text(RIGHT, 250.95, f"{totals.other_charges:.2f}", align="right", max_width=65, field="other_charges")
    p.text(346.3, 262.1, "Add")
    p.text(368.7, 262.15, "IGST")
    p.text(507.3, 262.15, f"{invoice.igst_rate:.3f}%", align="right", max_width=80)
    p.text(RIGHT, 262.15, f"{totals.igst:.2f}", align="right", max_width=65, field="IGST amount")
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
    p.text(LEFT, 396.8, f"( ID:{invoice.internal_id} )", font=fonts.bold, size=6.5,
           max_width=150, field="internal_id")
    p.text(200.05, 396.4, "This is a Computer generated document and does not require any signature.",
           size=6.8, max_width=RIGHT - 200.05)
    c.showPage()
    c.save()
    return output.getvalue()


def _write_output(path: Path, content: bytes, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        # Exclusive creation prevents silently replacing a previously issued PDF.
        with path.open("xb") as handle:
            handle.write(content)
        return
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            handle.write(content)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def generate_invoice(data: dict[str, Any], output_path: str | Path, *, overwrite: bool = False,
                     fonts: FontSet = DEFAULT_FONTS, stamp_path: Path | None = DEFAULT_STAMP) -> Totals:
    """Public API: validate, calculate, render, then write the PDF and return totals."""
    invoice = parse_invoice(data)
    totals = calculate_totals(invoice)
    content = build_pdf(invoice, totals, fonts=fonts, stamp_path=stamp_path)
    _write_output(Path(output_path), content, overwrite)
    return totals


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvoiceError(f"Duplicate JSON key: {key}.")
        result[key] = value
    return result


def load_invoice_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle, parse_float=Decimal, object_pairs_hook=_unique_object)
    if not isinstance(data, dict):
        raise InvoiceError("The JSON file must contain a single invoice object.")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, help="Invoice JSON input")
    parser.add_argument("--output", "-o", type=Path, default=Path("invoice.pdf"))
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace an existing output PDF")
    parser.add_argument("--no-stamp", action="store_true", help="Omit the supplied stamp/signature image")
    parser.add_argument("--font-regular", type=Path, help="Optional locally licensed regular TTF")
    parser.add_argument("--font-bold", type=Path, help="Optional locally licensed bold TTF")
    parser.add_argument("--font-bold-italic", type=Path, help="Optional matching bold-italic TTF")
    args = parser.parse_args(argv)
    try:
        if bool(args.font_regular) != bool(args.font_bold):
            raise InvoiceError("Supply both --font-regular and --font-bold, or neither.")
        if args.font_bold_italic and not args.font_regular:
            raise InvoiceError("--font-bold-italic also requires --font-regular and --font-bold.")
        fonts = register_fonts(args.font_regular, args.font_bold, args.font_bold_italic) if args.font_regular else DEFAULT_FONTS
        totals = generate_invoice(load_invoice_json(args.input), args.output, overwrite=args.overwrite,
                                  fonts=fonts, stamp_path=None if args.no_stamp else DEFAULT_STAMP)
    except FileExistsError:
        print(f"Error: {args.output} already exists. Use a new filename or add --overwrite.", file=sys.stderr)
        return 2
    except (InvoiceError, OSError, json.JSONDecodeError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Created: {args.output.resolve()}")
    print(f"Items: {totals.subtotal:.2f} | Other charges: {totals.other_charges:.2f} | IGST: {totals.igst:.2f} | Total: {totals.net_amount:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
