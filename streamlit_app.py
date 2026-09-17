"""Browser invoice form and session-only seller settings."""
import copy
from datetime import date

import streamlit as st

from invoice_generator import (
    COMPANY, InvoiceError, build_pdf, calculate_totals, new_invoice_number, parse_ticket,
)
from invoice_register import append_invoice
from invoice_chat import ticket_data
from invoice_chat_ui import render_chat, render_chat_button, render_chat_styles


def invoice_page() -> None:
    render_chat_styles()
    invoice = st.session_state.get("generated_invoice", {})
    if invoice.get("chat_open"):
        editor, chat = st.columns([1.6, 1], gap="large")
        with editor:
            render_invoice_editor()
        current = st.session_state.get("generated_invoice", {})
        if current.get("chat_open"):
            with chat:
                render_chat(current)
    else:
        with st.container(key="invoice_editor_solo"):
            render_invoice_editor()


def render_invoice_editor() -> None:
    for field, value in st.session_state.pop("invoice_form_updates", {}).items():
        st.session_state[f"ticket_{field}"] = value
    defaults = {"issued_date": date.today(), "travel_date": date.today(),
                "processing_charges": "0.00", "gst_rate": "18",
                "seat_charge": "0.00", "seat_margin": "0.00"}
    for field, value in defaults.items():
        st.session_state.setdefault(f"ticket_{field}", value)
    st.title("Air ticket invoice")
    st.caption("Enter one issued ticket to generate one invoice PDF.")

    with st.form("ticket_invoice"):
        st.subheader("Ticket")
        passenger_name = st.text_input("Passenger name", key="ticket_passenger_name")
        destination = st.text_input("Destination / route", placeholder="CCU-BKK-CCU", key="ticket_destination")
        pnr_left, pnr_right = st.columns(2)
        with pnr_left:
            tbo_pnr = st.text_input("TBO PNR (if available)", key="ticket_tbo_pnr")
        with pnr_right:
            riya_pnr = st.text_input("Riya PNR (if available)", key="ticket_riya_pnr")
        date_left, date_right = st.columns(2)
        with date_left:
            issued_date = st.date_input("Issued date", value=None, key="ticket_issued_date")
        with date_right:
            travel_date = st.date_input("Travel date", value=None, key="ticket_travel_date")

        st.subheader("Amounts in rupees")
        st.caption("Enter decimal amounts without commas. Blank optional amounts count as zero.")
        net = st.text_input("NET", placeholder="68222.00", key="ticket_net")
        processing_charges = st.text_input("Processing Charges", key="ticket_processing_charges")
        gst_rate = st.text_input("GST rate (%)", key="ticket_gst_rate")
        seat_left, seat_mid, seat_right = st.columns(3)
        with seat_left:
            seat_charge = st.text_input("Seat charge", key="ticket_seat_charge")
        with seat_mid:
            seat_margin = st.text_input("Seat margin", key="ticket_seat_margin")
        with seat_right:
            seat_gross = st.text_input("Seat gross (if known)", key="ticket_seat_gross")
        st.caption("When seat gross is entered, it is used instead of seat charge plus seat margin.")

        st.subheader("Customer")
        company_name = st.text_input("Company name", key="ticket_company_name")
        company_gstin = st.text_input("Company GSTIN (if available)", key="ticket_company_gstin")
        remark = st.text_area("Remark (optional)", key="ticket_remark")
        submitted = st.form_submit_button("Generate invoice", type="primary")

    if submitted:
        st.session_state.pop("generated_invoice", None)
        data = {
            "issued_date": issued_date.isoformat() if issued_date else "",
            "travel_date": travel_date.isoformat() if travel_date else "",
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
            pdf = build_pdf(ticket, totals, number, seller=st.session_state.seller_settings)
            append_invoice(ticket, totals, number, st.session_state.seller_settings["name"])
        except (InvoiceError, OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.session_state.generated_invoice = {
                "number": number, "totals": totals, "pdf": pdf,
                "data": ticket_data(ticket), "seller": copy.deepcopy(st.session_state.seller_settings),
                "revision": 1, "messages": [],
            }

    if "generated_invoice" in st.session_state:
        result = st.session_state.generated_invoice
        totals = result["totals"]
        st.success(f"Invoice {result['number']} · Revision {result['revision']} is ready.")
        st.write(
            f"Ticket cost: ₹{totals.ticket_cost:.2f} · "
            f"Processing Charges: ₹{totals.processing_charges:.2f} · "
            f"GST ({totals.gst_rate:.3f}%): ₹{totals.gst:.2f} · **Total: ₹{totals.net_amount:.2f}**"
        )
        st.download_button(
            "Download invoice PDF",
            data=result["pdf"],
            file_name=f"invoice_{result['number']}_r{result['revision']}.pdf",
            mime="application/pdf",
            on_click="ignore",
        )
        render_chat_button(result)


st.set_page_config(page_title="Air ticket invoice", page_icon="✈️", layout="wide")
if "seller_settings" not in st.session_state:
    st.session_state.seller_settings = copy.deepcopy(COMPANY)

page = st.navigation([
    st.Page(invoice_page, title="Invoice", default=True),
    st.Page("invoice_history.py", title="Generated invoices"),
    st.Page("settings_page.py", title="Settings"),
])
page.run()
