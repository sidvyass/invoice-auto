"""Edit seller details for the current browser session."""
import json
from pathlib import Path

import streamlit as st

from invoice_generator import (
    InvoiceError, build_pdf, calculate_totals, parse_ticket, validate_seller,
)


st.title("Invoice settings")
st.caption("Seller details for new invoices in this browser session. Existing PDFs keep their contents.")
current = st.session_state.seller_settings

with st.form("seller_settings_form"):
    st.subheader("Header")
    name_col, website_col = st.columns(2)
    with name_col:
        name = st.text_input("Seller name", value=current["name"], key="settings_name")
    with website_col:
        website = st.text_input("Website", value=current["website"], key="settings_website")
    address_lines = tuple(
        st.text_input(f"Address line {index + 1}", value=line, key=f"settings_address_{index}")
        for index, line in enumerate(current["address_lines"])
    )
    phone_col, mobile_col, email_col = st.columns(3)
    with phone_col:
        phone = st.text_input("Phone", value=current["phone"], key="settings_phone")
    with mobile_col:
        mobile = st.text_input("Mobile", value=current["mobile"], key="settings_mobile")
    with email_col:
        email = st.text_input("Email", value=current["email"], key="settings_email")
    gst_col, pan_col = st.columns(2)
    with gst_col:
        gstin = st.text_input("Seller GSTIN", value=current["gstin"], key="settings_gstin")
    with pan_col:
        pan = st.text_input("Seller PAN", value=current["pan"], key="settings_pan")

    st.subheader("Bank details")
    bank_account_name = st.text_input("Account name", value=current["bank_account_name"], key="settings_account_name")
    bank_account_number = st.text_input("Account number", value=current["bank_account_number"], key="settings_account_number")
    bank_name = st.text_input("Bank name", value=current["bank_name"], key="settings_bank_name")
    bank_ifsc = st.text_input("IFSC", value=current["bank_ifsc"], key="settings_ifsc")
    bank_account_type = st.text_input("Account type", value=current["bank_account_type"], key="settings_account_type")
    bank_city = st.text_input("Bank city", value=current["bank_city"], key="settings_bank_city")

    st.subheader("Terms")
    terms = tuple(
        st.text_input(f"Term {index + 1}", value=term, key=f"settings_term_{index}")
        for index, term in enumerate(current["terms"])
    )
    saved = st.form_submit_button("Save settings", type="primary")

if saved:
    candidate = {
        "name": name, "website": website, "address_lines": address_lines,
        "phone": phone, "mobile": mobile, "email": email, "gstin": gstin, "pan": pan,
        "bank_account_name": bank_account_name, "bank_account_number": bank_account_number,
        "bank_name": bank_name, "bank_ifsc": bank_ifsc,
        "bank_account_type": bank_account_type, "bank_city": bank_city,
        "terms": terms,
    }
    try:
        candidate = validate_seller(candidate)
        sample_data = json.loads(Path(__file__).with_name("sample_ticket.json").read_text(encoding="utf-8"))
        sample_ticket = parse_ticket(sample_data)
        build_pdf(sample_ticket, calculate_totals(sample_ticket), "AT260914-1234567890", seller=candidate)
    except (InvoiceError, OSError) as exc:
        st.error(str(exc))
    else:
        st.session_state.seller_settings = candidate
        st.success("Settings saved for this browser session. Generate a new invoice to use them.")
