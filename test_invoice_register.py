"""Tests for the CSV register used by the Streamlit app."""
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from invoice_generator import calculate_totals, parse_ticket
from invoice_register import FIELDS, LEGACY_FIELDS, append_invoice, export_csv, latest_invoices, read_invoices


class InvoiceRegisterTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "invoices.csv"
        self.ticket = parse_ticket(json.loads(Path("sample_ticket.json").read_text()))
        self.totals = calculate_totals(self.ticket)

    def test_append_read_and_export(self):
        self.assertEqual(read_invoices(self.path), [])
        append_invoice(self.ticket, self.totals, "AT260914-AAAAAAAAAA", "SELLER ONE", self.path)
        append_invoice(self.ticket, self.totals, "AT260914-BBBBBBBBBB", "SELLER TWO", self.path)
        rows = read_invoices(self.path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["invoice_number"], "AT260914-AAAAAAAAAA")
        self.assertEqual(rows[0]["seller_name"], "SELLER ONE")
        self.assertEqual(rows[1]["net_invoice_amount"], "69974.30")
        self.assertEqual(self.path.read_text().count("invoice_number"), 1)
        exported = export_csv(rows)
        parsed = list(csv.DictReader(io.StringIO(exported.decode("utf-8-sig"))))
        self.assertEqual(parsed, rows)

    def test_empty_export_has_headers(self):
        self.assertEqual(export_csv([]).decode("utf-8-sig").splitlines()[0], ",".join(FIELDS))
        self.path.write_bytes(export_csv([]))
        self.assertEqual(read_invoices(self.path), [])
        append_invoice(self.ticket, self.totals, "AT260914-AAAAAAAAAA", "SELLER ONE", self.path)
        self.assertEqual(len(read_invoices(self.path)), 1)

    def test_legacy_migration_and_revision_idempotency(self):
        append_invoice(self.ticket, self.totals, "TEST", "SELLER", self.path)
        original = read_invoices(self.path)[0]
        with self.path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=LEGACY_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerow(original)
        self.assertEqual(read_invoices(self.path)[0]["revision"], "1")
        append_invoice(self.ticket, self.totals, "TEST", "SELLER", self.path, revision=2)
        append_invoice(self.ticket, self.totals, "TEST", "SELLER", self.path, revision=2)
        rows = read_invoices(self.path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], original)
        self.assertEqual(latest_invoices(rows), [rows[1]])
        with self.assertRaises(ValueError):
            append_invoice(self.ticket, self.totals, "TEST", "DIFFERENT", self.path, revision=2)
        with self.assertRaises(ValueError):
            append_invoice(self.ticket, self.totals, "TEST", "SELLER", self.path, revision=4)

    def test_failed_save_leaves_original_csv(self):
        append_invoice(self.ticket, self.totals, "TEST", "SELLER", self.path)
        original = self.path.read_bytes()
        with patch("invoice_register.os.replace", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                append_invoice(self.ticket, self.totals, "TEST", "SELLER", self.path, revision=2)
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
