# Fixed-layout hotel invoice generator

A ReportLab script based on the supplied `hi-06_9228 (2).pdf` invoice.

## Package contents

- `invoice_generator.py`: generator, validation, calculations, and command-line interface.
- `sample_invoice.json`: the supplied invoice's variable data.
- `assets/stamp.png`: the unchanged stamp/signature image extracted from the supplied PDF.
- `invoice_HI0000006.pdf`: generated example for comparison with the original.
- `requirements.txt`: the ReportLab version tested with this package.
- `test_invoice_generator.py`: 30 automated tests using Python's standard unittest module.

The original invoice PDF is NOT needed to run the generator. Keep the `assets`
folder beside the script. No font files are included.

## Installation and first run

Requires Python 3.10 or newer. Open a terminal inside this extracted folder:

```powershell
python -m pip install -r requirements.txt
python invoice_generator.py sample_invoice.json --output invoice.pdf
```

For each new invoice, edit a copy of `sample_invoice.json`, then run:

```powershell
python invoice_generator.py next_invoice.json --output next_invoice.pdf
```

Existing PDFs are not overwritten unless you explicitly add `--overwrite`:

```powershell
python invoice_generator.py sample_invoice.json --output invoice.pdf --overwrite
```

Use `--no-stamp` to leave the stamp area empty. The bundled image is a reproduction
of the supplied image, not a cryptographic digital signature.

## Input fields

All top-level keys below must be present. Pass `"0.00"` for a zero charge or tax
base. Use decimal strings for money and tax rates, strings for identifiers, and
`YYYY-MM-DD` for all dates. A blank customer GSTIN is permitted.

| Top-level field | Type | Meaning |
| --- | --- | --- |
| `invoice_number` | string | Printed invoice number, e.g. `HI0000006`. Assigned by your own workflow, not this script. |
| `invoice_date` | date string | Invoice date; printed as `14 Sep 2026`. |
| `customer_name` | string | Name after `To,`. The sample's original spelling is preserved. |
| `customer_gstin` | string | Customer GSTIN; 15 uppercase letters/digits, or `""`. This is only a format check. |
| `place_of_supply` | string | Text printed after `POS :`, e.g. `West Bengal`. |
| `state_code` | string | Two digits; use `"07"`, not `7`, to preserve a leading zero. |
| `guest_name` | string | Printed guest name(s), including any title you want displayed. |
| `hsn_sac_code` | string | Printed HSN/SAC code, e.g. `998551`. |
| `items` | list of objects | Hotel bookings. At least one is required. See each item's fields below. |
| `other_charges` | decimal string | Amount on the `Add Other Charges` row. |
| `igst_rate` | decimal string | Percentage, e.g. `"18.000"` for 18%, not `"0.18"`. Up to three decimal places. |
| `igst_taxable_amount` | decimal string | Explicit base used to calculate IGST. Not separately printed. For the sample, this is `"500.00"`. |
| `internal_id` | string | Value in the bottom-left `( ID:558 )` reference. Not an invoice number. |

Each object in `items` must contain exactly these six fields:

| Item field | Type | Meaning |
| --- | --- | --- |
| `voucher` | string | Printed voucher reference, e.g. `HV6`. |
| `description` | string | Hotel and room description. `\n` forces a line break; other text wraps within the existing Particulars column. |
| `check_in` | date string | Arrival date in `YYYY-MM-DD`. Printed in `DD/MM/YYYY`. |
| `check_out` | date string | Departure date in `YYYY-MM-DD`; must be after arrival. |
| `rooms` | integer | Number of rooms; must be at least 1. |
| `rate` | decimal string | Price per room per night, with up to two decimal places. No extra line tax is added to it. |

Unknown fields are rejected so input typos cannot silently change an invoice.
You do not supply nights, line amounts, total tax, net amount, or amount in words.

## Calculation contract

```text
nights            = check_out - check_in, in calendar days
line amount       = nights * rooms * rate
item subtotal     = sum of line amounts
IGST              = igst_taxable_amount * igst_rate / 100
net amount        = item subtotal + other_charges + IGST
```

IGST is rounded to two decimal places with decimal ROUND_HALF_UP. Input currency
values with more than two significant decimal places are rejected rather than
silently rounded. Calculations use Decimal, not binary floating-point arithmetic.

For the included sample:

```text
Hotel amount      1 night * 1 room * 7650.00 = 7650.00
Other charges                                  500.00
IGST               500.00 * 18 / 100            90.00
Net invoice amount                            8240.00
```

The taxable base is explicit because the sample shows 90.00 of IGST, not tax on
the full 8150.00 pre-tax amount. Supply the tax base and rate approved by your
accounting team. This script reproduces the calculation; it does not determine
GST applicability, validate the business's tax treatment, or check registration
records. It also does not infer tax rates from the state code.

The existing item-level `Tax %` column stays blank, as in the sample. All tax
calculated by this version appears in the IGST summary row. There are no added
CGST/SGST rows, discounts, withholding taxes, or credit-note workflows.

## Static information

The `COMPANY` dictionary near the top of `invoice_generator.py` contains the
seller's name, address, contacts, GSTIN, PAN, bank details, and terms copied from
the sample. These are configuration, not per-invoice inputs. The signature image
is read from `assets/stamp.png`. The labels and their positions are fixed.

## Layout and font fidelity

The generator uses the original PDF's 595 x 841 point page dimensions and fixed
coordinates. It retains the blank lower-page area, header bands, column positions,
summary section, bank block, terms, and stamp placement. It does not use the
original PDF as a background; invoice text is newly drawn by ReportLab.

The source embeds fonts named Infozeal and Infozeal-Bold. This package defaults to
ReportLab's standard Times fonts, so glyph appearance and text widths differ
slightly; the result is not a pixel-identical copy. To use suitable fonts already
licensed and installed on your machine, provide their TTF files:

```powershell
python invoice_generator.py sample_invoice.json --output invoice.pdf --font-regular "C:\Fonts\Infozeal.ttf" --font-bold "C:\Fonts\Infozeal-Bold.ttf"
```

Replace those example paths with actual local paths. Both regular and bold fonts
are required when using this option. An optional `--font-bold-italic` path is also
supported for the Terms label. No font files are supplied in this package.

Fields that cannot fit are rejected with an explanation. The script never clips
text, decreases the font size to force a fit, adds a page, or moves the totals.
Descriptions can wrap within the available item area. The number of bookings that
fit therefore depends on their description lengths. The supplied booking fits,
and two bookings with the same description length are covered by the tests.

Default fonts cover the sample's Latin text. Unsupported characters produce an
error rather than a missing-glyph box; a suitable locally installed TTF is needed
for additional scripts. This is not a complex-script shaping implementation.

## Call it from another Python script

```python
from invoice_generator import generate_invoice, load_invoice_json

data = load_invoice_json("sample_invoice.json")
totals = generate_invoice(data, "invoice.pdf")
print(totals.net_amount)  # Decimal('8240.00')
```

Your database/API code can supply the same dictionary directly instead of reading
JSON. Use strings or Decimal for monetary fields; raw Python floats are rejected.
`generate_invoice` returns a Totals dataclass with line amounts, subtotal, other
charges, IGST, net amount, and amount in words. `InvoiceError` reports invalid data
or layout overflow; `FileExistsError` protects an existing output file.

For in-memory output, such as a future HTTP response:

```python
from invoice_generator import build_pdf, calculate_totals, parse_invoice

invoice = parse_invoice(data)
totals = calculate_totals(invoice)
pdf_bytes = build_pdf(invoice, totals)
```

## Tests

```powershell
python -m unittest -v test_invoice_generator.py
```

The 30 tests cover sample totals, multiple nights/rooms, explicit tax bases,
rounding, amount-in-words conversion, bad inputs, overflow, two bookings,
missing images, supported JSON numbers, and output overwrite protection.

This package generates PDFs only. It does not post transactions to Tally, allocate
or enforce unique invoice numbers across files, email documents, maintain an
audit ledger, or register GST e-invoices. Avoid treating output-file overwrite
protection as a substitute for invoice-number control in your accounting workflow.
