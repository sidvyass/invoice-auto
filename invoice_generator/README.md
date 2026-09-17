# Air ticket invoice generator

This script creates one PDF invoice for one issued airline ticket. It uses the columns in `Ticketing amount.xlsx` as the input checklist, but does not read or modify the spreadsheet. The PDF keeps the existing invoice design and static seller details, with ticket wording in place of hotel wording.

## Set up and run

Requires Python 3.10 or newer and uv.

```sh
cd invoice_generator
uv sync
uv run streamlit run streamlit_app.py
```

Open the local URL printed by Streamlit. Fill in one ticket, select **Generate invoice**, review the amount, and download the PDF. Submitting again creates a new invoice number. Downloading or refreshing the page retains the current invoice within that browser session. The web app does not store PDFs on the server.

The CLI remains available with `uv run python invoice_generator.py`. It prompts for one ticket and writes `invoices/invoice_<generated-number>.pdf`. Use `--output-dir PATH` to choose a different folder and `--no-stamp` to omit the bundled stamp image. Existing PDFs are never overwritten.

## What to enter

Enter dates as `YYYY-MM-DD` in the CLI and rupee amounts without commas or currency symbols. The fields are issued date, travel date, passenger name, destination/route, TBO PNR, Riya PNR, NET, Processing Charges, GST rate, seat charge, seat margin, seat gross, company name, company GSTIN, and remark. Either TBO PNR or Riya PNR is required. Company GSTIN, remark, and seat fields may be blank. Blank Processing Charges and seat amounts mean zero. GST rate defaults to 18% and can be changed for an invoice.

The printed invoice date is the issued date. The invoice number is generated automatically. The billed seat amount is `seat gross` when entered; otherwise it is `seat charge + seat margin`. Ticket cost is `NET + billed seat amount`. GST is calculated **only on Processing Charges**, rounded to two decimals. The final invoice amount is `ticket cost + Processing Charges + GST`. For example, the model invoice's `8836.00` ticket cost and `350.00` Processing Charges give `63.00` GST at 18% and a `9249.00` total. [sample_ticket.json](sample_ticket.json) gives `69974.30` under this rule.

The PDF's ticket row shows passenger, sector, travel date, PNR, Basic (NET), and Total (ticket cost). When a seat amount is billed, it is included in ticket cost and noted below the row. Processing Charges and GST appear in the summary. Class, Flight, Ticket No., and item tax columns from the model invoice are omitted because they are not collected.

The sample JSON is a reference for automated tests; normal users enter the same values at the prompts. To run the tests:

```sh
uv run python -m unittest -v test_invoice_generator.py
uv run python -m unittest -v test_streamlit_app.py
```

Long text that cannot fit the fixed page is rejected with an error. The script does not send invoices, track invoice numbers in a ledger, or determine whether GST legally applies to a ticket.
