"""Smoke tests for the browser form using Streamlit's app test runner."""
import unittest
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from invoice_generator import COMPANY, build_pdf, calculate_totals, parse_ticket


class StreamlitInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file("streamlit_app.py").run()

    def fill(self, label, value):
        next(widget for widget in self.app.text_input if widget.label == label).set_value(value)

    def settings(self):
        self.app.switch_page("settings_page.py").run()

    def test_generate_and_rerun_keeps_one_invoice(self):
        self.fill("Passenger name", "MR AMISH NAIK")
        self.fill("Destination / route", "CCU-BKK-CCU")
        self.fill("TBO PNR (if available)", "9PE7IZ")
        self.fill("NET", "68222.00")
        self.fill("Processing Charges", "1485.00")
        self.fill("Company name", "IMPERIAL FRAGRANCES")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        first = self.app.session_state["generated_invoice"]
        self.assertTrue(first["pdf"].startswith(b"%PDF-"))
        self.assertEqual(str(first["totals"].net_amount), "69974.30")
        self.app.run()
        self.assertEqual(self.app.session_state["generated_invoice"]["number"], first["number"])

    def test_invalid_submission_clears_previous_pdf(self):
        self.fill("Passenger name", "MR AMISH NAIK")
        self.fill("Destination / route", "CCU-BKK-CCU")
        self.fill("TBO PNR (if available)", "9PE7IZ")
        self.fill("NET", "100.00")
        self.fill("Company name", "IMPERIAL FRAGRANCES")
        self.app.button[0].click().run()
        self.assertIn("generated_invoice", self.app.session_state)
        self.fill("NET", "bad amount")
        self.app.button[0].click().run()
        self.assertNotIn("generated_invoice", self.app.session_state)
        self.assertTrue(self.app.error)

    def test_gst_rate_override(self):
        self.fill("Passenger name", "MR AMISH NAIK")
        self.fill("Destination / route", "CCU-BKK-CCU")
        self.fill("TBO PNR (if available)", "9PE7IZ")
        self.fill("NET", "8836.00")
        self.fill("Processing Charges", "350.00")
        self.fill("GST rate (%)", "5")
        self.fill("Company name", "IMPERIAL FRAGRANCES")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(str(self.app.session_state["generated_invoice"]["totals"].gst), "17.50")

    def test_settings_order_and_session_isolation(self):
        self.settings()
        labels = [widget.label for widget in self.app.text_input]
        self.assertEqual(labels[:5], ["Seller name", "Website", "Address line 1", "Address line 2", "Address line 3"])
        self.assertLess(labels.index("Email"), labels.index("Seller GSTIN"))
        self.assertLess(labels.index("Seller PAN"), labels.index("Account name"))
        self.assertLess(labels.index("Bank city"), labels.index("Term 1"))
        self.fill("Seller name", "NEW SELLER")
        self.fill("Email", "new@example.com")
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.session_state["seller_settings"]["name"], "NEW SELLER")
        self.assertEqual(self.app.session_state["seller_settings"]["email"], "new@example.com")
        other = AppTest.from_file("streamlit_app.py").run()
        self.assertEqual(other.session_state["seller_settings"]["name"], COMPANY["name"])
        self.assertEqual(COMPANY["email"], "imperialroutes@gmail.com")

    def test_settings_validate_layout_and_preserve_existing_pdf(self):
        self.fill("Passenger name", "MR AMISH NAIK")
        self.fill("Destination / route", "CCU-BKK-CCU")
        self.fill("TBO PNR (if available)", "9PE7IZ")
        self.fill("NET", "8836.00")
        self.fill("Company name", "IMPERIAL FRAGRANCES")
        self.app.button[0].click().run()
        existing_pdf = self.app.session_state["generated_invoice"]["pdf"]

        self.settings()
        self.fill("Seller name", "NEW SELLER")
        self.app.button[0].click().run()
        self.assertEqual(self.app.session_state["generated_invoice"]["pdf"], existing_pdf)
        data = json.loads(Path("sample_ticket.json").read_text())
        ticket = parse_ticket(data)
        updated_pdf = build_pdf(ticket, calculate_totals(ticket), "AT260914-1234567890",
                                seller=self.app.session_state["seller_settings"])
        self.assertIn(b"/Author (NEW SELLER)", updated_pdf)

        self.fill("Seller name", "X" * 200)
        self.app.button[0].click().run()
        self.assertTrue(self.app.error)
        self.assertEqual(self.app.session_state["seller_settings"]["name"], "NEW SELLER")


if __name__ == "__main__":
    unittest.main()
