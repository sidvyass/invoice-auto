"""Session-local chat and preview for the current invoice."""
from dataclasses import asdict
from datetime import date

import streamlit as st

from invoice_chat import ChatError, get_api_key, prepare_revision, request_edit
from invoice_generator import InvoiceError, parse_ticket
from invoice_register import append_invoice


def render_chat_styles() -> None:
    st.markdown("""
    <style>
    .st-key-invoice_editor_solo { max-width: 900px; margin-inline: auto; }
    .st-key-open_invoice_chat button {
        color: #fff;
        background: linear-gradient(115deg, #245edb 0%, #7040cc 35%, #ac2679 70%, #b8462e 100%);
        border: 1px solid rgba(255, 255, 255, .4);
        border-radius: 999px;
        padding: .65rem 1.25rem;
        box-shadow: -4px 0 18px rgba(62, 120, 255, .22),
                    4px 0 18px rgba(232, 83, 147, .22);
        transition: box-shadow .18s ease, filter .18s ease;
    }
    .st-key-open_invoice_chat button p { font-weight: 600; }
    .st-key-open_invoice_chat button:hover {
        color: #fff;
        filter: brightness(1.08);
        border-color: rgba(255, 255, 255, .7);
        box-shadow: -4px 0 24px rgba(62, 120, 255, .35),
                    4px 0 24px rgba(232, 83, 147, .35);
    }
    .st-key-open_invoice_chat button:focus-visible {
        outline: 3px solid #8b7cf8;
        outline-offset: 4px;
    }
    .st-key-invoice_chat_panel {
        border-radius: 20px;
        border-top: 3px solid #9c75e8;
        box-shadow: 0 8px 32px rgba(110, 90, 180, .09);
    }
    @media (min-width: 1000px) {
        [data-testid="stColumn"]:has(.st-key-invoice_chat_panel) {
            position: sticky;
            top: 4.5rem;
            align-self: flex-start;
        }
    }
    @media (prefers-reduced-motion: reduce) {
        .st-key-open_invoice_chat button { transition: none; }
    }
    </style>
    """, unsafe_allow_html=True)


def render_chat_button(invoice: dict) -> None:
    if st.button("Chat with AI", key="open_invoice_chat", icon="✨"):
        invoice["chat_open"] = True
        st.rerun()


def render_chat(invoice: dict) -> None:
    with st.container(key="invoice_chat_panel", border=True):
        _render_chat_panel(invoice)


def _render_chat_panel(invoice: dict) -> None:
    if st.button("Close chat", key="close_invoice_chat"):
        invoice["chat_open"] = False
        st.rerun()
    st.subheader("Chat with AI")
    st.caption("Ask to change ticket or customer details, amounts, or remarks. Review changes before applying them. "
               "Your invoice fields and recent messages are sent to OpenRouter and its model provider.")
    try:
        secrets = st.secrets.to_dict() if st.secrets else {}
    except FileNotFoundError:
        secrets = {}
    try:
        api_key = get_api_key(secrets)
    except ChatError as exc:
        st.info(str(exc))
        return

    messages = invoice.setdefault("messages", [])
    pending = invoice.get("pending")
    with st.container(height=420, border=False, key="invoice_chat_conversation"):
        if not messages:
            st.info("Try: ‘Set processing charges to ₹500’ or ‘Change the passenger name’. ")
        for message in messages:
            with st.chat_message(message["role"]):
                st.text(message["content"])
        if invoice.get("chat_error"):
            st.error(invoice["chat_error"])

        if pending:
            st.write("**Proposed changes**")
            changes = [{"Field": field.replace("_", " ").title(),
                        "Current": invoice["data"][field] or "(blank)",
                        "Proposed": value or "(blank)"}
                       for field, value in pending["data"].items() if value != invoice["data"][field]]
            st.dataframe(changes, hide_index=True, width="stretch")
            st.write(f"GST: ₹{invoice['totals'].gst:.2f} → ₹{pending['totals'].gst:.2f} · "
                     f"Total: ₹{invoice['totals'].net_amount:.2f} → **₹{pending['totals'].net_amount:.2f}**")
            st.download_button("Preview revised PDF", data=pending["pdf"],
                               file_name=f"preview_{invoice['number']}_r{pending['revision']}.pdf",
                               mime="application/pdf", on_click="ignore")
            apply_column, discard_column = st.columns(2)
            if apply_column.button("Apply changes", type="primary"):
                try:
                    if pending["base_revision"] != invoice["revision"]:
                        raise ChatError("This proposal is out of date. Discard it and request the changes again.")
                    ticket = parse_ticket(pending["data"])
                    append_invoice(ticket, pending["totals"], invoice["number"], invoice["seller"]["name"],
                                   revision=pending["revision"])
                except (OSError, ValueError) as exc:
                    st.error(f"Could not save the revision: {exc}")
                else:
                    invoice.update({key: pending[key] for key in ("data", "totals", "pdf", "revision")})
                    invoice.pop("pending")
                    invoice.pop("chat_error", None)
                    messages.append({"role": "assistant", "content": f"Applied revision {invoice['revision']}. Your download is updated."})
                    st.session_state.invoice_form_updates = {
                        key: date.fromisoformat(value) if key in ("issued_date", "travel_date") else value
                        for key, value in invoice["data"].items()
                    }
                    st.rerun()
            if discard_column.button("Discard"):
                invoice.pop("pending")
                invoice.pop("chat_error", None)
                messages.append({"role": "assistant", "content": "Proposal discarded. The invoice is unchanged."})
                st.rerun()

    prompt = st.chat_input("What would you like to change?", max_chars=2000, disabled=bool(pending),
                           key=f"invoice_chat_{invoice['number']}")
    if prompt and prompt.strip():
        invoice.pop("chat_error", None)
        messages.append({"role": "user", "content": prompt.strip()})
        try:
            with st.spinner("Preparing your invoice changes…"):
                reply = request_edit(invoice["data"],
                                     {k: str(v) for k, v in asdict(invoice["totals"]).items()},
                                     messages, api_key)
                if reply["action"] == "propose":
                    invoice["pending"] = prepare_revision(invoice, reply)
                content = reply["message"]
                if reply["changes"]:
                    content += "\n" + "\n".join(
                        f"{c['field'].replace('_', ' ').title()}: {c['value'] or '(blank)'}"
                        for c in reply["changes"])
                messages.append({"role": "assistant", "content": content})
        except (ChatError, InvoiceError) as exc:
            invoice["chat_error"] = str(exc)
            messages.append({"role": "assistant", "content": "The request failed validation or could not be completed. No changes were applied."})
        st.rerun()
