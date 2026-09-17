"""Browser form for one issued airline ticket invoice."""
from datetime import date

import streamlit as st

from invoice_generator import InvoiceError, build_pdf, calculate_totals, new_invoice_number, parse_ticket


st.set_page_config(page_title="Air ticket invoice", page_icon="✈️")
st.title("Air ticket invoice")
st.caption("Enter one issued ticket to generate one invoice PDF.")

with st.form("ticket_invoice"):
    st.subheader("Ticket")
    passenger_name = st.text_input("Passenger name")
    destination = st.text_input("Destination / route", placeholder="CCU-BKK-CCU")
    pnr_left, pnr_right = st.columns(2)
    with pnr_left:
        tbo_pnr = st.text_input("TBO PNR (if available)")
    with pnr_right:
        riya_pnr = st.text_input("Riya PNR (if available)")
    date_left, date_right = st.columns(2)
    with date_left:
        issued_date = st.date_input("Issued date", value=date.today())
    with date_right:
        travel_date = st.date_input("Travel date", value=date.today())

    st.subheader("Amounts in rupees")
    st.caption("Enter decimal amounts without commas. Blank optional amounts count as zero.")
    net = st.text_input("NET", placeholder="68222.00")
    processing_charges = st.text_input("Processing Charges", value="0.00")
    gst_rate = st.text_input("GST rate (%)", value="18")
    seat_left, seat_mid, seat_right = st.columns(3)
    with seat_left:
        seat_charge = st.text_input("Seat charge", value="0.00")
    with seat_mid:
        seat_margin = st.text_input("Seat margin", value="0.00")
    with seat_right:
        seat_gross = st.text_input("Seat gross (if known)")
    st.caption("When seat gross is entered, it is used instead of seat charge plus seat margin.")

    st.subheader("Customer")
    company_name = st.text_input("Company name")
    company_gstin = st.text_input("Company GSTIN (if available)")
    remark = st.text_area("Remark (optional)")
    submitted = st.form_submit_button("Generate invoice", type="primary")

if submitted:
    st.session_state.pop("generated_invoice", None)
    data = {
        "issued_date": issued_date.isoformat(),
        "travel_date": travel_date.isoformat(),
        "passenger_name": passenger_name,
        "destination": destination,
        "tbo_pnr": tbo_pnr,
        "riya_pnr": riya_pnr,
        "net": net,
        "processing_charges": processing_charges or "0.00",
        "gst_rate": gst_rate or "18",
        "seat_charge": seat_charge or "0.00",
        "seat_margin": seat_margin or "0.00",
        "seat_gross": seat_gross,
        "company_name": company_name,
        "company_gstin": company_gstin,
        "remark": remark,
    }
    try:
        ticket = parse_ticket(data)
        totals = calculate_totals(ticket)
        number = new_invoice_number(ticket.issued_date)
        pdf = build_pdf(ticket, totals, number)
    except InvoiceError as exc:
        st.error(str(exc))
    else:
        st.session_state.generated_invoice = {"number": number, "totals": totals, "pdf": pdf}

if "generated_invoice" in st.session_state:
    result = st.session_state.generated_invoice
    totals = result["totals"]
    st.success(f"Invoice {result['number']} is ready.")
    st.write(
        f"Ticket cost: ₹{totals.ticket_cost:.2f} · "
        f"Processing Charges: ₹{totals.processing_charges:.2f} · "
        f"GST ({totals.gst_rate:.3f}%): ₹{totals.gst:.2f} · **Total: ₹{totals.net_amount:.2f}**"
    )
    st.download_button(
        "Download invoice PDF",
        data=result["pdf"],
        file_name=f"invoice_{result['number']}.pdf",
        mime="application/pdf",
        on_click="ignore",
    )
