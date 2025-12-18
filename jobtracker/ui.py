import streamlit as st
import pandas as pd
from datetime import date, datetime
import streamlit.components.v1 as components

from jobtracker.auth import logout_button
from jobtracker.repository import (
    fetch_df, insert_app, update_app, delete_app,
    add_document, list_documents, get_document, delete_document
)
from jobtracker.service import (
    STATUSES, format_date, validate_required, default_followup, compute_overdue
)

# --------------------- Helpers ---------------------
def pd_to_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None

def safe_str(x):
    return "" if x is None else str(x)

def status_style(status: str):
    s = (status or "").strip().lower()
    if s in ("offer", "selected"):
        return ("#d1fae5", "#065f46")   # green
    if s in ("rejected", "withdrawn"):
        return ("#fee2e2", "#991b1b")   # red
    if s in ("interview", "onsite", "hr screen"):
        return ("#dbeafe", "#1e3a8a")   # blue
    if s in ("applied", "oa"):
        return ("#fef9c3", "#854d0e")   # yellow
    if s in ("ghosted",):
        return ("#e5e7eb", "#374151")   # gray
    return ("#f3f4f6", "#111827")

def normalize_row(row_dict: dict) -> dict:
    out = {}
    for k, v in row_dict.items():
        out[k] = None if pd.isna(v) else v
    return out

def render_card(row: dict):
    bg, fg = status_style(row.get("status"))
    html = f"""
<div style="padding:12px 14px;border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
    <div style="font-size:18px;font-weight:700;">{safe_str(row.get("company"))} — {safe_str(row.get("role"))}</div>
    <div style="display:inline-block;padding:4px 10px;border-radius:999px;background:{bg};color:{fg};
                font-weight:700;font-size:12px;line-height:18px;">{safe_str(row.get("status"))}</div>
  </div>
  <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:18px;color:#374151;">
    <div><b>ID:</b> {int(row.get("id"))}</div>
    <div><b>Location:</b> {safe_str(row.get("location"))}</div>
    <div><b>Applied:</b> {safe_str(row.get("applied_date"))}</div>
    <div><b>Follow-up:</b> {safe_str(row.get("followup_date"))}</div>
    <div><b>Overdue:</b> {"✅" if bool(row.get("overdue")) else "—"}</div>
    <div><b>Source:</b> {safe_str(row.get("source"))}</div>
  </div>
  <div style="margin-top:8px;color:#6b7280;font-size:13px;"><b>Updated:</b> {safe_str(row.get("updated_at"))}</div>
</div>
"""
    components.html(html, height=140)

def upload_attachments_block(conn, app_id: int, key_prefix: str):
    st.subheader("Attachments")

    doc_type = st.selectbox(
        "Attachment type",
        ["Document", "Email"],
        index=0,
        key=f"{key_prefix}_doctype"
    )

    files = st.file_uploader(
        "Upload attachments (multiple allowed). For emails upload .eml / .msg / pdf etc.",
        accept_multiple_files=True,
        key=f"{key_prefix}_files"
    )

    if files:
        uploaded_any = False
        for f in files:
            ok = add_document(
                conn,
                int(app_id),
                f.name,
                f.type or "application/octet-stream",
                f.getvalue(),
                doc_type
            )
            if ok:
                uploaded_any = True
            else:
                st.warning(f"Skipped duplicate: {f.name}")

        if uploaded_any:
            st.success("Uploaded.")
            st.rerun()

    docs = list_documents(conn, int(app_id))
    if not docs:
        st.info("No attachments yet.")
        return

    for d in docs:
        doc_id = d["id"] if isinstance(d, dict) else d[0]
        filename = d["filename"] if isinstance(d, dict) else d[1]
        doc_type_val = d["doc_type"] if isinstance(d, dict) else d[3]
        uploaded_at = d["uploaded_at"] if isinstance(d, dict) else d[4]

        a, b, c = st.columns([6, 2, 2])
        a.write(f"📎 [{doc_type_val}] {filename}  |  {uploaded_at}")

        if b.button("Download", key=f"{key_prefix}_dl_{doc_id}"):
            full = get_document(conn, int(doc_id))
            content = full["content"] if isinstance(full, dict) else full[4]
            mime = (full.get("mime_type") if isinstance(full, dict) else full[2]) or "application/octet-stream"
            st.download_button(
                "Click to download",
                data=content,
                file_name=filename,
                mime=mime,
                key=f"{key_prefix}_dlbtn_{doc_id}",
            )

        if c.button("Delete", key=f"{key_prefix}_del_{doc_id}"):
            delete_document(conn, int(doc_id))
            st.warning("Deleted.")
            st.rerun()


# --------------------- Main UI ---------------------
def render_app(conn):
    st.title("Job Application Tracker")

    # Sidebar
    with st.sidebar:
        st.subheader("Filters")
        search = st.text_input("Search (company/role/location/source)")
        status = st.selectbox("Status", ["All"] + STATUSES, index=0)
        overdue_only = st.checkbox("Overdue follow-ups only", value=False)

        st.divider()
        default_followup_days = st.number_input("Default follow-up after apply (days)", 1, 30, 7)

        st.divider()
        logout_button()

    df = fetch_df(conn, search=search, status=status, overdue_only=overdue_only)
    if not df.empty:
        df["overdue"] = df.apply(lambda r: compute_overdue(r.get("followup_date"), r.get("status")), axis=1)
    else:
        df["overdue"] = []

    # Metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", int(len(df)))
    c2.metric("Applied", int((df["status"] == "Applied").sum()) if not df.empty else 0)
    c3.metric("Interviews", int(df["status"].isin(["Interview", "Onsite"]).sum()) if not df.empty else 0)
    c4.metric("Overdue", int(df["overdue"].sum()) if not df.empty else 0)

    st.divider()
    tabs = st.tabs(["Applications", "Add / Edit", "Export"])

    # --------------------- Applications ---------------------
    with tabs[0]:
        st.subheader("Applications")

        if df.empty:
            st.info("No rows yet. Add your first application in Add / Edit.")
        else:
            show_cols = [
                "id", "company", "role", "location", "status",
                "applied_date", "followup_date", "overdue", "source",
                "job_url", "contact", "salary", "updated_at", "notes"
            ]
            view = df[show_cols].copy()

            for _, row in view.iterrows():
                row_dict = normalize_row(row.to_dict())
                app_id = int(row_dict["id"])

                left, right = st.columns([10, 2])
                with left:
                    render_card(row_dict)
                with right:
                    if st.button("✏️ Edit", key=f"edit_btn_{app_id}"):
                        st.session_state["inline_edit_id"] = app_id
                        st.rerun()
                st.write("")

            inline_id = st.session_state.get("inline_edit_id", None)
            if inline_id is not None and inline_id in df["id"].tolist():
                st.divider()
                st.subheader(f"Edit Application (ID {inline_id})")

                row_df = df[df["id"] == inline_id].iloc[0].to_dict()
                row_df = normalize_row(row_df)

                with st.form("inline_edit_form"):
                    company = st.text_input("Company *", value=row_df.get("company") or "")
                    role = st.text_input("Role *", value=row_df.get("role") or "")
                    location = st.text_input("Location", value=row_df.get("location") or "")
                    job_url = st.text_input("Job URL", value=row_df.get("job_url") or "")
                    source_val = st.text_input("Source", value=row_df.get("source") or "")
                    status_edit = st.selectbox(
                        "Status *", STATUSES,
                        index=STATUSES.index(row_df.get("status") or "Applied")
                    )

                    ad = pd_to_date(row_df.get("applied_date")) or date.today()
                    fd = pd_to_date(row_df.get("followup_date"))

                    applied_date = st.date_input("Applied date", value=ad, key="inline_applied")
                    has_followup = st.checkbox("Has follow-up date", value=bool(fd), key="inline_has_followup")
                    followup_date = st.date_input(
                        "Follow-up date",
                        value=fd or default_followup(date.today(), int(default_followup_days)),
                        key="inline_followup"
                    ) if has_followup else None

                    salary = st.text_input("Salary", value=row_df.get("salary") or "")
                    contact = st.text_input("Contact", value=row_df.get("contact") or "")
                    notes = st.text_area("Notes", height=120, value=row_df.get("notes") or "")

                    col_a, col_b, col_c = st.columns([2, 2, 2])
                    save = col_a.form_submit_button("Save")
                    dele = col_b.form_submit_button("Delete")
                    close = col_c.form_submit_button("Close")

                    if save:
                        err = validate_required(company, role)
                        if err:
                            st.error(err)
                        else:
                            update_app(conn, int(inline_id), {
                                "company": company.strip(),
                                "role": role.strip(),
                                "location": location.strip() or None,
                                "job_url": job_url.strip() or None,
                                "source": source_val.strip() or None,
                                "status": status_edit,
                                "applied_date": format_date(applied_date),
                                "followup_date": format_date(followup_date) if followup_date else None,
                                "salary": salary.strip() or None,
                                "contact": contact.strip() or None,
                                "notes": notes.strip() or None,
                            })
                            st.success("Updated.")
                            st.rerun()

                    if dele:
                        delete_app(conn, int(inline_id))
                        st.warning("Deleted.")
                        st.session_state["inline_edit_id"] = None
                        st.rerun()

                    if close:
                        st.session_state["inline_edit_id"] = None
                        st.rerun()

                upload_attachments_block(conn, inline_id, key_prefix=f"edit_{inline_id}")

    # --------------------- Add / Edit ---------------------
    with tabs[1]:
        st.subheader("Add new application (with attachments)")

        with st.form("add_form", clear_on_submit=True):
            company = st.text_input("Company *")
            role = st.text_input("Role *")
            location = st.text_input("Location")
            job_url = st.text_input("Job URL")
            source = st.text_input("Source (LinkedIn/Referral/etc.)")
            status_new = st.selectbox("Status *", STATUSES, index=STATUSES.index("Applied"))
            applied_date = st.date_input("Applied date", value=date.today())

            set_followup = st.checkbox("Set follow-up date", value=True)
            followup_date = st.date_input(
                "Follow-up date",
                value=default_followup(applied_date, int(default_followup_days)),
            ) if set_followup else None

            salary = st.text_input("Salary")
            contact = st.text_input("Contact (name/email)")
            notes = st.text_area("Notes", height=120)

            doc_type_new = st.selectbox("Attachment type", ["Document", "Email"], index=0, key="add_doctype")
            files_new = st.file_uploader(
                "Upload attachments now (optional)",
                accept_multiple_files=True,
                key="add_files"
            )

            submitted = st.form_submit_button("Add")
            if submitted:
                err = validate_required(company, role)
                if err:
                    st.error(err)
                else:
                    new_id = insert_app(conn, {
                        "company": company.strip(),
                        "role": role.strip(),
                        "location": location.strip() or None,
                        "job_url": job_url.strip() or None,
                        "source": source.strip() or None,
                        "status": status_new,
                        "applied_date": format_date(applied_date),
                        "followup_date": format_date(followup_date) if followup_date else None,
                        "salary": salary.strip() or None,
                        "contact": contact.strip() or None,
                        "notes": notes.strip() or None,
                    })

                    if files_new:
                        for f in files_new:
                            ok = add_document(
                                conn, int(new_id),
                                f.name,
                                f.type or "application/octet-stream",
                                f.getvalue(),
                                doc_type_new
                            )
                            if not ok:
                                st.warning(f"Skipped duplicate: {f.name}")

                    st.success(f"Added application ID {new_id}.")
                    st.rerun()

    # --------------------- Export ---------------------
    with tabs[2]:
        st.subheader("Export")
        if df.empty:
            st.info("No data to export.")
        else:
            export_df = df.drop(columns=["overdue"], errors="ignore")
            st.download_button(
                "Download CSV",
                export_df.to_csv(index=False).encode("utf-8"),
                file_name="job_applications.csv",
                mime="text/csv"
            )
