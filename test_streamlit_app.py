"""Smoke tests for the browser form using Streamlit's app test runner."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from invoice_generator import COMPANY, build_pdf, calculate_totals, parse_ticket
from invoice_register import read_invoices


class InvoiceAppTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.register_path = Path(folder.name) / "generated_invoices.csv"
        patcher = patch("invoice_register.REGISTER_PATH", self.register_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = AppTest.from_file("streamlit_app.py", default_timeout=15).run()

    def fill(self, label, value):
        next(widget for widget in self.app.text_input if widget.label == label).set_value(value)

    def settings(self):
        self.app.switch_page("settings_page.py").run()


class StreamlitInvoiceTests(InvoiceAppTestCase):
    def test_cleared_date_shows_validation_error(self):
        self.app.date_input[0].set_value(None)
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(self.app.error)
        self.assertNotIn("generated_invoice", self.app.session_state)

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
        self.assertEqual(len(read_invoices()), 1)
        self.app.run()
        self.assertEqual(self.app.session_state["generated_invoice"]["number"], first["number"])
        self.assertEqual(len(read_invoices()), 1)

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
        self.assertEqual(len(read_invoices()), 1)

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

    def test_history_page_shows_recorded_invoice(self):
        self.fill("Passenger name", "MR AMISH NAIK")
        self.fill("Destination / route", "CCU-BKK-CCU")
        self.fill("TBO PNR (if available)", "9PE7IZ")
        self.fill("NET", "8836.00")
        self.fill("Processing Charges", "350.00")
        self.fill("Company name", "IMPERIAL FRAGRANCES")
        self.app.button[0].click().run()
        number = self.app.session_state["generated_invoice"]["number"]
        self.app.switch_page("invoice_history.py").run()
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.dataframe), 1)
        table = self.app.dataframe[0].value
        self.assertEqual(table.iloc[0]["invoice_number"], number)
        self.assertEqual(table.iloc[0]["net_invoice_amount"], "9249.00")


class InvoiceChatFlowTests(InvoiceAppTestCase):
    def generate(self):
        for label, value in [("Passenger name", "TEST PASSENGER"), ("Destination / route", "CCU-DEL"),
                             ("TBO PNR (if available)", "TEST12"), ("NET", "8836.00"),
                             ("Processing Charges", "350.00"), ("Company name", "TEST CUSTOMER")]:
            self.fill(label, value)
        self.app.button[0].click().run()

    def click(self, label):
        next(button for button in self.app.button if button.label == label).click().run()

    def setUp(self):
        super().setUp()
        patcher = patch("invoice_chat_ui.get_api_key", return_value="test-key")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_apply_discard_and_followup(self):
        from test_invoice_chat import proposal
        self.assertNotIn("Chat with AI", [button.label for button in self.app.button])
        self.generate()
        original = self.app.session_state["generated_invoice"]["pdf"]
        number = self.app.session_state["generated_invoice"]["number"]
        self.click("Chat with AI")
        self.assertFalse(self.app.exception)
        with patch("invoice_chat_ui.request_edit", return_value=proposal()) as request:
            self.app.chat_input[0].set_value("Set processing charges to 500").run()
            self.assertFalse(self.app.exception)
            self.assertEqual(request.call_count, 1)
            self.app.run()
            self.assertEqual(request.call_count, 1)
        self.assertEqual(self.app.session_state["generated_invoice"]["pdf"], original)
        self.assertEqual(len(read_invoices()), 1)
        self.click("Apply changes")
        invoice = self.app.session_state["generated_invoice"]
        self.assertFalse(self.app.exception)
        self.assertEqual(invoice["number"], number)
        self.assertEqual(invoice["revision"], 2)
        self.assertEqual(str(invoice["totals"].net_amount), "9426.00")
        self.assertNotEqual(invoice["pdf"], original)
        self.assertEqual(next(w for w in self.app.text_input if w.label == "Processing Charges").value, "500.00")
        self.app.run()
        self.assertEqual(len(read_invoices()), 2)
        with patch("invoice_chat_ui.request_edit", return_value=proposal("remark", "Revised ticket")) as request:
            self.app.chat_input[0].set_value("Add a remark").run()
            self.assertEqual(request.call_args.args[0]["processing_charges"], "500.00")
        self.click("Discard")
        self.assertNotIn("pending", invoice)
        self.assertEqual(invoice["data"]["remark"], "")
        self.assertEqual(len(read_invoices()), 2)
        self.app.switch_page("invoice_history.py").run()
        self.assertEqual(len(self.app.dataframe[0].value), 1)
        self.assertEqual(self.app.dataframe[0].value.iloc[0]["revision"], "2")
        self.app.checkbox[0].check().run()
        self.assertEqual(len(self.app.dataframe[0].value), 2)

    def test_clarification_errors_and_new_invoice(self):
        from invoice_chat import ChatError
        from test_invoice_chat import proposal
        self.generate()
        self.click("Chat with AI")
        invoice = self.app.session_state["generated_invoice"]
        original = invoice["pdf"]
        with patch("invoice_chat_ui.request_edit", return_value={
                "action": "clarify", "message": "What date should I use?", "changes": []}):
            self.app.chat_input[0].set_value("Change travel date").run()
        self.assertNotIn("pending", invoice)
        self.assertIn("What date should I use?", [m["content"] for m in invoice["messages"]])
        with patch("invoice_chat_ui.request_edit", return_value=proposal("net", "-1")):
            self.app.chat_input[0].set_value("Use negative net").run()
        self.assertTrue(self.app.error)
        with patch("invoice_chat_ui.request_edit", side_effect=ChatError("Service unavailable")):
            self.app.chat_input[0].set_value("Try again").run()
        self.assertTrue(self.app.error)
        self.assertFalse(self.app.exception)
        self.assertEqual(invoice["pdf"], original)
        self.assertEqual(len(read_invoices()), 1)
        other = AppTest.from_file("streamlit_app.py").run()
        self.assertNotIn("generated_invoice", other.session_state)
        self.generate()
        self.assertEqual(self.app.session_state["generated_invoice"]["messages"], [])
        self.assertEqual(len(self.app.chat_input), 0)

    def test_save_failure_preserves_invoice_and_proposal(self):
        from test_invoice_chat import proposal
        self.generate()
        self.click("Chat with AI")
        invoice = self.app.session_state["generated_invoice"]
        with patch("invoice_chat_ui.request_edit", return_value=proposal()):
            self.app.chat_input[0].set_value("Change charges to 500").run()
        with patch("invoice_chat_ui.append_invoice", side_effect=OSError("Disk full")):
            self.click("Apply changes")
        self.assertEqual(invoice["revision"], 1)
        self.assertIn("pending", invoice)
        self.assertTrue(self.app.error)
        self.assertEqual(len(read_invoices()), 1)


if __name__ == "__main__":
    unittest.main()
