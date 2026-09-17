"""Run with: python -m unittest -v test_invoice_generator.py"""
import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from invoice_generator import (
    DEFAULT_STAMP, InvoiceError, amount_in_words, build_pdf, calculate_totals,
    generate_invoice, load_invoice_json, main, parse_invoice,
)

HERE = Path(__file__).resolve().parent


class InvoiceTests(unittest.TestCase):
    def setUp(self):
        self.data = load_invoice_json(HERE / "sample_invoice.json")

    def render(self, data=None, **kwargs):
        invoice = parse_invoice(self.data if data is None else data)
        return build_pdf(invoice, calculate_totals(invoice), **kwargs)

    def test_sample_totals(self):
        invoice = parse_invoice(self.data)
        total = calculate_totals(invoice)
        self.assertEqual(invoice.items[0].nights, 1)
        self.assertEqual(total.line_amounts, (Decimal("7650.00"),))
        self.assertEqual(total.other_charges, Decimal("500.00"))
        self.assertEqual(total.igst, Decimal("90.00"))
        self.assertEqual(total.net_amount, Decimal("8240.00"))
        self.assertEqual(total.amount_in_words, "Rupees Eight Thousand Two Hundred Forty Only")

    def test_two_nights_three_rooms(self):
        self.data["items"][0].update(check_out="2026-09-23", rooms=3)
        invoice = parse_invoice(self.data)
        self.assertEqual(invoice.items[0].nights, 2)
        self.assertEqual(invoice.items[0].amount, Decimal("45900.00"))
        self.assertTrue(self.render().startswith(b"%PDF-"))

    def test_explicit_taxable_base(self):
        self.data["igst_taxable_amount"] = "8150.00"
        totals = calculate_totals(parse_invoice(self.data))
        self.assertEqual(totals.igst, Decimal("1467.00"))
        self.assertEqual(totals.net_amount, Decimal("9617.00"))

    def test_half_up_tax_rounding(self):
        self.data["items"][0]["rate"] = "0.00"
        self.data.update(other_charges="0.05", igst_taxable_amount="0.05", igst_rate="10.000")
        totals = calculate_totals(parse_invoice(self.data))
        self.assertEqual(totals.igst, Decimal("0.01"))
        self.assertEqual(totals.net_amount, Decimal("0.06"))
        self.assertEqual(totals.amount_in_words, "Rupees Zero and Six Paise Only")

    def test_zero_amount(self):
        self.data["items"][0]["rate"] = "0.00"
        self.data.update(other_charges="0", igst_taxable_amount="0")
        self.assertEqual(calculate_totals(parse_invoice(self.data)).amount_in_words, "Rupees Zero Only")
        self.assertTrue(self.render().startswith(b"%PDF-"))

    def test_indian_number_words(self):
        examples = {
            "1": "Rupees One Only",
            "21": "Rupees Twenty One Only",
            "101": "Rupees One Hundred One Only",
            "100000": "Rupees One Lakh Only",
            "12345678.25": "Rupees One Crore Twenty Three Lakh Forty Five Thousand Six Hundred Seventy Eight and Twenty Five Paise Only",
        }
        for number, expected in examples.items():
            with self.subTest(number=number):
                self.assertEqual(amount_in_words(Decimal(number)), expected)

    def test_more_than_two_currency_places_rejected(self):
        self.data["other_charges"] = "500.001"
        with self.assertRaisesRegex(InvoiceError, "decimal places"):
            parse_invoice(self.data)

    def test_more_than_three_tax_rate_places_rejected(self):
        self.data["igst_rate"] = "18.0001"
        with self.assertRaisesRegex(InvoiceError, "decimal places"):
            parse_invoice(self.data)

    def test_negative_nonfinite_and_invalid_amounts(self):
        for amount in ("-1", "NaN", "Infinity", "1,000.00", "abc", True, 500.0):
            with self.subTest(amount=amount):
                self.data["other_charges"] = amount
                with self.assertRaises(InvoiceError):
                    parse_invoice(self.data)

    def test_excessive_tax_rate_rejected(self):
        self.data["igst_rate"] = "101"
        with self.assertRaises(InvoiceError):
            parse_invoice(self.data)

    def test_taxable_base_above_invoice_rejected(self):
        self.data["igst_taxable_amount"] = "9000.00"
        with self.assertRaisesRegex(InvoiceError, "cannot exceed"):
            parse_invoice(self.data)

    def test_invalid_calendar_date(self):
        self.data["invoice_date"] = "2026-02-30"
        with self.assertRaisesRegex(InvoiceError, "calendar date"):
            parse_invoice(self.data)

    def test_non_iso_date_rejected(self):
        self.data["invoice_date"] = "14/09/2026"
        with self.assertRaisesRegex(InvoiceError, "YYYY-MM-DD"):
            parse_invoice(self.data)

    def test_nonpositive_stay_rejected(self):
        for day in ("2026-09-21", "2026-09-20"):
            with self.subTest(day=day):
                self.data["items"][0]["check_out"] = day
                with self.assertRaisesRegex(InvoiceError, "after check_in"):
                    parse_invoice(self.data)

    def test_invalid_rooms(self):
        for rooms in (0, -1, True, "1", 1.5, 10000):
            with self.subTest(rooms=rooms):
                self.data["items"][0]["rooms"] = rooms
                with self.assertRaisesRegex(InvoiceError, "rooms"):
                    parse_invoice(self.data)

    def test_missing_unknown_and_duplicate_fields(self):
        missing = copy.deepcopy(self.data)
        del missing["guest_name"]
        with self.assertRaisesRegex(InvoiceError, "missing field"):
            parse_invoice(missing)
        unknown = copy.deepcopy(self.data)
        unknown["guest_names"] = "Typo"
        with self.assertRaisesRegex(InvoiceError, "unknown field"):
            parse_invoice(unknown)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "duplicate.json"
            path.write_text('{"items": [], "items": []}', encoding="utf-8")
            with self.assertRaisesRegex(InvoiceError, "Duplicate JSON key"):
                load_invoice_json(path)

    def test_empty_items_rejected(self):
        self.data["items"] = []
        with self.assertRaisesRegex(InvoiceError, "nonempty"):
            parse_invoice(self.data)

    def test_whitespace_name_rejected(self):
        self.data["customer_name"] = "  "
        with self.assertRaisesRegex(InvoiceError, "blank"):
            parse_invoice(self.data)

    def test_control_character_rejected(self):
        self.data["guest_name"] = "Guest\nAnother line"
        with self.assertRaisesRegex(InvoiceError, "control character"):
            parse_invoice(self.data)

    def test_description_newline_preserved(self):
        invoice = parse_invoice(self.data)
        self.assertIn("\nPremier)", invoice.items[0].description)

    def test_description_automatically_wraps(self):
        self.data["items"][0]["description"] = "Hotel description " * 12
        self.assertTrue(self.render().startswith(b"%PDF-"))

    def test_leading_zero_state_and_blank_customer_gstin(self):
        self.data.update(state_code="07", customer_gstin="", place_of_supply="Delhi")
        self.assertEqual(parse_invoice(self.data).state_code, "07")
        self.assertTrue(self.render().startswith(b"%PDF-"))

    def test_missing_stamp_has_clear_error(self):
        with self.assertRaisesRegex(InvoiceError, "Missing stamp image"):
            self.render(stamp_path=HERE / "does_not_exist.png")
        self.assertTrue(DEFAULT_STAMP.is_file())

    def test_stamp_can_be_omitted(self):
        self.assertTrue(self.render(stamp_path=None).startswith(b"%PDF-"))

    def test_two_items_fit(self):
        self.data["items"].append(copy.deepcopy(self.data["items"][0]))
        self.data["items"][1]["voucher"] = "HV7"
        self.assertTrue(self.render().startswith(b"%PDF-"))

    def test_too_many_items_rejected_before_output(self):
        self.data["items"] *= 5
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.pdf"
            with self.assertRaisesRegex(InvoiceError, "will not fit"):
                generate_invoice(self.data, path)
            self.assertFalse(path.exists())

    def test_long_customer_rejected_before_output(self):
        self.data["customer_name"] = "VERY LONG COMPANY NAME " * 25
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.pdf"
            with self.assertRaisesRegex(InvoiceError, "too wide"):
                generate_invoice(self.data, path)
            self.assertFalse(path.exists())

    def test_unicode_glyph_error_is_explicit(self):
        self.data["guest_name"] = "Guest \U0001f600"
        with self.assertRaisesRegex(InvoiceError, "character"):
            self.render()

    def test_numeric_json_amounts_read_as_decimal(self):
        numeric = json.dumps(self.data).replace('"7650.00"', '7650.00')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "numeric.json"
            path.write_text(numeric, encoding="utf-8")
            data = load_invoice_json(path)
            self.assertIsInstance(data["items"][0]["rate"], Decimal)
            self.assertEqual(calculate_totals(parse_invoice(data)).net_amount, Decimal("8240.00"))

    def test_new_output_overwrite_protection_and_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "invoice.pdf"
            totals = generate_invoice(self.data, path)
            content = path.read_bytes()
            self.assertTrue(content.startswith(b"%PDF-"))
            self.assertEqual(totals.net_amount, Decimal("8240.00"))
            with self.assertRaises(FileExistsError):
                generate_invoice(self.data, path)
            self.assertEqual(path.read_bytes(), content)
            self.data["invoice_number"] = "HI0000007"
            generate_invoice(self.data, path, overwrite=True)
            self.assertNotEqual(path.read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
