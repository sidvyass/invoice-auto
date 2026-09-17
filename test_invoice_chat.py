"""Validation and transport tests; no real API calls or credentials."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from invoice_chat import (ChatError, get_api_key, prepare_revision, request_edit,
                          ticket_data, validate_reply)
from invoice_generator import COMPANY, InvoiceError, calculate_totals, parse_ticket


def proposal(field="processing_charges", value="500.00"):
    return {"action": "propose", "message": "Here is the proposed change.",
            "changes": [{"field": field, "value": value}]}


class InvoiceChatTests(unittest.TestCase):
    def setUp(self):
        ticket = parse_ticket(json.loads(Path("sample_ticket.json").read_text()))
        self.invoice = {"data": ticket_data(ticket), "totals": calculate_totals(ticket),
                        "number": "AT260914-AAAAAAAAAA", "revision": 1,
                        "seller": copy.deepcopy(COMPANY), "pdf": b"original"}

    def test_revision_recalculates_and_preserves_original(self):
        original = copy.deepcopy(self.invoice)
        revision = prepare_revision(self.invoice, proposal())
        self.assertEqual(str(revision["totals"].gst), "90.00")
        self.assertEqual(str(revision["totals"].net_amount), "68812.00")
        self.assertEqual(revision["revision"], 2)
        self.assertTrue(revision["pdf"].startswith(b"%PDF-"))
        self.assertEqual(self.invoice, original)

    def test_invalid_and_oversize_edits_rejected(self):
        for field, value in [("net", "-1"), ("gst_rate", "101"),
                             ("travel_date", "tomorrow"), ("remark", "X" * 4000),
                             ("tbo_pnr", "")]:
            with self.subTest(field=field), self.assertRaises(InvoiceError):
                prepare_revision(self.invoice, proposal(field, value))
        with self.assertRaises(ChatError):
            prepare_revision(self.invoice, proposal("net", self.invoice["data"]["net"]))

    def test_reply_schema_rejects_untrusted_shapes(self):
        bad = [None, [], {}, proposal("pdf", "bad"), proposal("net", 12.5),
               {"action": "answer", "message": "ok", "changes": proposal()["changes"]},
               {"action": "propose", "message": "ok", "changes": []}]
        duplicate = proposal()
        duplicate["changes"] *= 2
        bad.append(duplicate)
        for reply in bad:
            with self.subTest(reply=reply), self.assertRaises(ChatError):
                validate_reply(reply)

    def test_key_sources_without_printing_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / ".env"
            env.write_text('openrouter_api_key="test-file-key"\n')
            with patch("invoice_chat.ENV_PATH", env), patch.dict("os.environ", {}, clear=True):
                self.assertEqual(get_api_key(), "test-file-key")
                self.assertEqual(get_api_key({"OPENROUTER_API_KEY": "test-hosted-key"}), "test-hosted-key")
                with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-env-key"}):
                    self.assertEqual(get_api_key(), "test-env-key")
                env.unlink()
                with self.assertRaises(ChatError):
                    get_api_key()

    def call_api(self):
        return request_edit(self.invoice["data"],
                            {k: str(v) for k, v in asdict(self.invoice["totals"]).items()},
                            [{"role": "user", "content": "Set processing charges to 500"}], "test-key")

    @patch("invoice_chat.urlopen")
    def test_structured_request_and_response(self, opener):
        opener.return_value.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(proposal())}}]
        }).encode()
        self.assertEqual(self.call_api(), proposal())
        request = opener.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["model"], "openai/gpt-5-nano")
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertNotIn("test-key", request.data.decode())
        self.assertNotIn("bank", request.data.decode().split("Current invoice data")[-1])
        self.assertEqual(opener.call_args.kwargs["timeout"], 45)

    @patch("invoice_chat.urlopen")
    def test_api_failures_are_safe(self, opener):
        for error in [TimeoutError("secret"), HTTPError("url", 401, "secret", {}, None),
                      HTTPError("url", 402, "secret", {}, None), HTTPError("url", 429, "secret", {}, None)]:
            opener.side_effect = error
            with self.assertRaises(ChatError) as caught:
                self.call_api()
            self.assertNotIn("secret", str(caught.exception))
        opener.side_effect = None
        for response in [b"invalid JSON", b'{}', json.dumps({"choices": [
            {"finish_reason": "length", "message": {"content": "{}"}}]}).encode()]:
            opener.return_value.__enter__.return_value.read.return_value = response
            with self.assertRaises(ChatError):
                self.call_api()


if __name__ == "__main__":
    unittest.main()
