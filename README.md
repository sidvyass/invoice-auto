# Air ticket invoice generator

This script creates one PDF invoice for one issued airline ticket. It uses the columns in `Ticketing amount.xlsx` as the input checklist, but does not read or modify the spreadsheet. The PDF keeps the existing invoice design and static seller details, with ticket wording in place of hotel wording.

## Set up and run

Requires Python 3.10 or newer and uv.

```sh
uv sync
uv run streamlit run streamlit_app.py
```

Open the local URL printed by Streamlit. Fill in one ticket, select **Generate invoice**, review the amount, and download the PDF. Submitting again creates a new invoice number. Downloading or refreshing the page retains the current invoice within that browser session. The web app does not store PDFs on the server.

Each successful web invoice is added to the local `generated_invoices.csv` register. The **Generated invoices** page displays its rows and has one **Download CSV** button. The register is ignored by Git because it contains customer and passenger details. If the app runs on Streamlit Community Cloud, download the CSV regularly: files created while a hosted app runs are [not guaranteed to persist](https://docs.streamlit.io/develop/concepts/configuration/serving-static-files). The CLI does not add rows to this web register.

The **Settings** page lets you edit the seller name, website, address, contact and tax details, bank details, and terms in the same order they appear on the PDF. Save settings before generating a new invoice. Changes apply only to your current browser session; another user sees the defaults, and a new session starts with the defaults again. Text that cannot fit the fixed invoice layout is rejected. Existing PDFs keep the seller details used when they were generated. The CLI always uses the defaults in `invoice_generator.py`.

The CLI remains available with `uv run python invoice_generator.py`. It prompts for one ticket and writes `invoices/invoice_<generated-number>.pdf`. Use `--output-dir PATH` to choose a different folder and `--no-stamp` to omit the bundled stamp image. Existing PDFs are never overwritten.

## Chat with AI

After generating an invoice, click **Chat with AI** to request changes to ticket fields,
customer details, amounts, or remarks. The gradient AI button opens a panel on the right
with a scrolling conversation and an input beneath it. Closing the panel keeps your
conversation and any pending proposal. The app uses `openai/gpt-5-nano` through
OpenRouter. Add your key to a `.env` file in the project directory:

```dotenv
openrouter_api_key=your-openrouter-api-key
```

`OPENROUTER_API_KEY` is also supported. Server environment variables take precedence
over Streamlit secrets and `.env`. On Streamlit Community Cloud, add the key in app
secrets instead. Keys stay on the server; `.env` and `.streamlit/secrets.toml` are ignored
by Git. Run `uv sync` after updating the repository.

The AI proposes edits; Python validates fields, calculates totals, and builds a preview
PDF. Select **Apply changes** to update the invoice and download, or **Discard** to keep
the current version. Ambiguous requests prompt a clarification. Seller settings,
bank details, invoice numbers, and PDF layout cannot be changed through chat.
Invoice fields and recent conversation messages are sent to OpenRouter and its model
provider when you send a message. No PDF or seller bank details are sent.

Accepted edits retain the invoice number and add a revision to the CSV register.
Existing CSV rows are treated as revision 1 and migrated on the next successful write.
The history page shows the latest revision by default; select **Show all revisions**
to view and export older versions too. PDF filenames include their revision.
The form is updated to match accepted changes. Generating another invoice starts a new
conversation. Chat history and editable invoice data last only for the browser session;
older CSV entries cannot be reopened for editing.

Run the complete test suite (API calls are mocked):

```sh
uv run python -m unittest -v
```

## Invoice fields

Enter dates as `YYYY-MM-DD` in the CLI and rupee amounts without commas or currency symbols. The fields are issued date, travel date, passenger name, destination/route, TBO PNR, Riya PNR, NET, Processing Charges, GST rate, seat charge, seat margin, seat gross, company name, company GSTIN, and remark. Either TBO PNR or Riya PNR is required. Company GSTIN, remark, and seat fields may be blank. Blank Processing Charges and seat amounts mean zero. GST rate defaults to 18% and can be changed for an invoice.

The printed invoice date is the issued date. The invoice number is generated automatically. The billed seat amount is `seat gross` when entered; otherwise it is `seat charge + seat margin`. Ticket cost is `NET + billed seat amount`. GST is calculated **only on Processing Charges**, rounded to two decimals. The final invoice amount is `ticket cost + Processing Charges + GST`. For example, the model invoice's `8836.00` ticket cost and `350.00` Processing Charges give `63.00` GST at 18% and a `9249.00` total. [sample_ticket.json](sample_ticket.json) gives `69974.30` under this rule.

The PDF's ticket row shows passenger, sector, travel date, PNR, Basic (NET), and Total (ticket cost). When a seat amount is billed, it is included in ticket cost and noted below the row. Processing Charges and GST appear in the summary. Class, Flight, Ticket No., and item tax columns from the model invoice are omitted because they are not collected.

The sample JSON is a reference for automated tests; normal users enter the same values at the prompts. To run the tests:

```sh
uv run python -m unittest -v test_invoice_generator.py
uv run python -m unittest -v test_streamlit_app.py
uv run python -m unittest -v test_invoice_register.py
```

Long text that cannot fit the fixed page is rejected with an error. The script does not send invoices, track invoice numbers in a ledger, or determine whether GST legally applies to a ticket.
