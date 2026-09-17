"""Run with: uv run python -m unittest -v test_invoice_generator.py"""
import copy
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from invoice_generator import (
    InvoiceError, amount_in_words, build_pdf, calculate_totals, generate_invoice,
    main, new_invoice_number, parse_ticket, prompt_ticket,
)

SAMPLE = json.loads((Path(__file__).parent / "sample_ticket.json").read_text())


class TicketInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.data = copy.deepcopy(SAMPLE)

    def ticket(self):
        return parse_ticket(self.data)

    def test_sample_total_and_pdf(self):
        ticket = self.ticket()
        totals = calculate_totals(ticket)
        self.assertEqual(totals.gst, Decimal("267.30"))
        self.assertEqual(totals.net_amount, Decimal("69974.30"))
        self.assertTrue(build_pdf(ticket, totals, "AT260914-1234567890").startswith(b"%PDF-"))

    def test_riya_pnr_and_seat_components(self):
        self.data.update(tbo_pnr="", riya_pnr="WHBI4U", seat_charge="480.00", seat_margin="20.00")
        ticket = self.ticket()
        self.assertEqual(ticket.pnr, "WHBI4U")
        self.assertEqual(calculate_totals(ticket).net_amount, Decimal("70474.30"))

    def test_explicit_seat_gross_takes_precedence(self):
        self.data.update(seat_charge="480.00", seat_margin="20.00", seat_gross="560.00")
        totals = calculate_totals(self.ticket())
        self.assertEqual(totals.seat_amount, Decimal("560.00"))
        self.assertEqual(totals.ticket_cost, Decimal("68782.00"))
        self.assertEqual(totals.net_amount, Decimal("70534.30"))

    def test_model_processing_charge_calculation(self):
        self.data.update(net="8836.00", processing_charges="350.00")
        totals = calculate_totals(self.ticket())
        self.assertEqual(totals.gst, Decimal("63.00"))
        self.assertEqual(totals.net_amount, Decimal("9249.00"))

    def test_changed_rate_and_zero_processing_charge(self):
        self.data["gst_rate"] = "5.000"
        self.assertEqual(calculate_totals(self.ticket()).net_amount, Decimal("69781.25"))
        self.data["processing_charges"] = "0.00"
        self.assertEqual(calculate_totals(self.ticket()).gst, Decimal("0.00"))

    def test_gst_rounds_half_up_and_rejects_bad_rate(self):
        self.data.update(net="0.00", processing_charges="0.05", gst_rate="10")
        self.assertEqual(calculate_totals(self.ticket()).gst, Decimal("0.01"))
        for value in ("-1", "100.001", "18.0001", "NaN"):
            with self.subTest(value=value):
                self.data["gst_rate"] = value
                with self.assertRaises(InvoiceError):
                    self.ticket()

    def test_both_pnrs_and_remark_render(self):
        self.data.update(riya_pnr="ABC123", remark="Ticket issued for business travel")
        ticket = self.ticket()
        self.assertTrue(build_pdf(ticket, calculate_totals(ticket), "AT260914-1234567890").startswith(b"%PDF-"))

    def test_missing_pnr_rejected(self):
        self.data.update(tbo_pnr="", riya_pnr="")
        with self.assertRaisesRegex(InvoiceError, "TBO PNR or Riya PNR"):
            self.ticket()

    def test_invalid_amount_and_date_rejected(self):
        for value in ("-1", "1.001", "NaN", "1,000"):
            with self.subTest(value=value):
                self.data["net"] = value
                with self.assertRaises(InvoiceError):
                    self.ticket()
        self.data["net"] = "100.00"
        self.data["travel_date"] = "2026-02-30"
        with self.assertRaisesRegex(InvoiceError, "calendar date"):
            self.ticket()

    def test_missing_and_unknown_fields_rejected(self):
        del self.data["net"]
        with self.assertRaisesRegex(InvoiceError, "missing field"):
            self.ticket()
        self.data = copy.deepcopy(SAMPLE)
        self.data["rooms"] = 1
        with self.assertRaisesRegex(InvoiceError, "unknown field"):
            self.ticket()

    def test_generated_number_and_no_overwrite(self):
        number = new_invoice_number(date(2026, 9, 14))
        self.assertRegex(number, r"^AT260914-[A-F0-9]{10}$")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / f"invoice_{number}.pdf"
            generate_invoice(self.ticket(), path, number)
            self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
            with self.assertRaises(FileExistsError):
                generate_invoice(self.ticket(), path, number)

    def test_long_remark_rejected(self):
        self.data["remark"] = "long remark " * 100
        ticket = self.ticket()
        with self.assertRaisesRegex(InvoiceError, "remark will not fit"):
            build_pdf(ticket, calculate_totals(ticket), "AT260914-1234567890")

    def test_prompt_collects_one_ticket(self):
        responses = iter([
            "2026-09-14", "2026-10-19", "MR AMISH NAIK", "CCU-BKK-CCU", "9PE7IZ", "",
            "68222.00", "1485.00", "18", "", "", "", "IMPERIAL FRAGRANCES", "", "",
        ])
        ticket = prompt_ticket(lambda _: next(responses))
        self.assertEqual(calculate_totals(ticket).net_amount, Decimal("69974.30"))

    def test_cli_creates_one_pdf(self):
        responses = iter([
            "2026-09-14", "2026-10-19", "MR AMISH NAIK", "CCU-BKK-CCU", "9PE7IZ", "",
            "68222.00", "1485.00", "18", "", "", "", "IMPERIAL FRAGRANCES", "", "",
        ])
        with tempfile.TemporaryDirectory() as folder, patch("builtins.input", side_effect=lambda _: next(responses)):
            self.assertEqual(main(["--output-dir", folder]), 0)
            self.assertEqual(len(list(Path(folder).glob("invoice_*.pdf"))), 1)

    def test_amount_words(self):
        self.assertEqual(amount_in_words(Decimal("100.06")), "Rupees One Hundred and Six Paise Only")


if __name__ == "__main__":
    unittest.main()
