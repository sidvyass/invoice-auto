"""Smoke tests for the browser form using Streamlit's app test runner."""
import unittest

from streamlit.testing.v1 import AppTest


class StreamlitInvoiceTests(unittest.TestCase):
    def setUp(self):
        self.app = AppTest.from_file("streamlit_app.py").run()

    def fill(self, label, value):
        next(widget for widget in self.app.text_input if widget.label == label).set_value(value)

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


if __name__ == "__main__":
    unittest.main()
