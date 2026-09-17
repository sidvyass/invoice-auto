# Air ticket invoice generator

This script creates one PDF invoice for one issued airline ticket. It uses the columns in `Ticketing amount.xlsx` as the input checklist, but does not read or modify the spreadsheet. The PDF keeps the existing invoice design and static seller details, with ticket wording in place of hotel wording.

## Set up and run

Requires Python 3.10 or newer and uv.

```sh
cd invoice_generator
uv sync
uv run python invoice_generator.py
```

The script prompts for one ticket and writes `invoices/invoice_<generated-number>.pdf`. Run it again for another ticket. Use `--output-dir PATH` to choose a different folder and `--no-stamp` to omit the bundled stamp image. Existing PDFs are never overwritten.

## What to enter

Enter dates as `YYYY-MM-DD` and rupee amounts without commas or currency symbols. The prompts follow the spreadsheet: issued date, travel date, passenger name, destination/route, TBO PNR, Riya PNR, NET, MARK UP, seat charge, seat margin, seat gross, company name, company GSTIN, and remark. Either TBO PNR or Riya PNR is required. Company GSTIN, remark, and seat fields may be blank. Blank MARK UP and seat amounts mean zero.

The printed invoice date is the issued date. The invoice number is generated automatically. The billed seat amount is `seat gross` when entered; otherwise it is `seat charge + seat margin`. The final total is `NET + MARK UP + billed seat amount`. The script prints this breakdown before writing the PDF. It does not calculate tax or import historical spreadsheet totals. For example, [sample_ticket.json](sample_ticket.json) produces a total of `69707.00` from `68222.00 + 1485.00`; the source spreadsheet's GROSS cell for that row differs.

The sample JSON is a reference for automated tests; normal users enter the same values at the prompts. To run the tests:

```sh
uv run python -m unittest -v test_invoice_generator.py
```

Long text that cannot fit the fixed page is rejected with an error. The script does not send invoices, track invoice numbers in a ledger, or determine tax treatment.
