import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
import streamlit.components.v1 as components
import matplotlib.pyplot as plt

from jobtracker.auth import logout_button
from jobtracker.db import get_conn
from jobtracker.repository import (
    fetch_df, insert_app, update_app, delete_app, quick_update_status,
    add_document, list_documents, get_document, delete_document,
    ensure_profile_ids,
    get_setting, set_setting,
    delete_docs_by_type_except
)
from jobtracker.service import (
    STATUSES as SERVICE_STATUSES, format_date, validate_required, default_followup, compute_overdue
)

DEFAULT_STATUSES = ["To Apply", "Saved", "Applied", "Interviewing", "Offered", "Rejected", "Withdrawn", "Ghosted"]
INTERVIEW_STAGES = ["Not started", "Screening Call", "Hiring Manager Interview", "Technical Round", "Onsite", "Offer Discussion"]
WORK_MODELS = ["Remote", "Hybrid", "On-site"]
PRIORITIES = ["Low", "Medium", "High"]


def merged_statuses():
    s = list(SERVICE_STATUSES) if isinstance(SERVICE_STATUSES, list) else list(DEFAULT_STATUSES)
    for x in DEFAULT_STATUSES:
        if x not in s:
            s.append(x)
    return s


STATUSES = merged_statuses()


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
    if s in ("offered", "offer", "selected"):
        return ("#d1fae5", "#065f46")
    if s in ("rejected", "withdrawn"):
        return ("#fee2e2", "#991b1b")
    if s in ("interviewing", "interview", "onsite", "hr screen"):
        return ("#dbeafe", "#1e3a8a")
    if s in ("applied", "to apply", "oa", "saved"):
        return ("#fef9c3", "#854d0e")
    if s in ("ghosted",):
        return ("#e5e7eb", "#374151")
    return ("#f3f4f6", "#111827")


def normalize_row(row_dict: dict) -> dict:
    out = {}
    for k, v in row_dict.items():
        out[k] = None if pd.isna(v) else v
    return out


def render_card_small(row: dict):
    bg, fg = status_style(row.get("status"))
    html = f"""
<div style="padding:10px 12px;border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;">
    <div>
      <div style="font-weight:800;font-size:15px;">{safe_str(row.get("company"))}</div>
      <div style="color:#374151;">{safe_str(row.get("role"))}</div>
      <div style="margin-top:6px;color:#6b7280;font-size:12px;">
        {safe_str(row.get("work_model"))}{" • " if row.get("interview_stage") else ""}{safe_str(row.get("interview_stage"))}
      </div>
    </div>
    <div style="display:inline-block;padding:4px 10px;border-radius:999px;background:{bg};color:{fg};
                font-weight:800;font-size:12px;line-height:18px;white-space:nowrap;">{safe_str(row.get("status"))}</div>
  </div>
</div>
"""
    components.html(html, height=120)


def donut_status_chart(df: pd.DataFrame):
    counts = df["status"].fillna("Unknown").value_counts()
    labels = counts.index.tolist()
    sizes = counts.values.tolist()

    fig, ax = plt.subplots()
    ax.pie(sizes, labels=None, startangle=90, wedgeprops=dict(width=0.35))
    ax.axis("equal")
    ax.set_title("Status Overview")
    ax.legend(labels, loc="center left", bbox_to_anchor=(1, 0.5))
    st.pyplot(fig)


def upload_attachments_block(conn, app_id: int, key_prefix: str, title="Attachments"):
    st.subheader(title)

    doc_type = st.selectbox(
        "Attachment type",
        ["Document", "Email"],
        index=0,
        key=f"{key_prefix}_doctype"
    )

    files = st.file_uploader(
        "Upload files (multiple allowed). Use Email for .eml/.msg/pdf screenshots.",
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


def board_columns_selector():
    default_cols = ["To Apply", "Saved", "Applied", "Interviewing", "Offered", "Rejected"]
    default_cols = [c for c in default_cols if c in STATUSES]
    all_cols = [s for s in STATUSES if s not in ("Withdrawn", "Ghosted")]

    chosen = st.multiselect(
        "Board columns",
        options=all_cols,
        default=default_cols,
        help="Choose which columns you want on the board",
        key="board_cols_picker"
    )
    return [s for s in STATUSES if s in chosen]


def render_app(conn):
    st.title("Job Search HQ")

    # ---- Navigation request handler ----
    if "_nav_to" in st.session_state:
        st.session_state["page"] = st.session_state["_nav_to"]
        del st.session_state["_nav_to"]

    if "page" not in st.session_state:
        st.session_state["page"] = "Dashboard"

    # Sidebar
    with st.sidebar:
        st.subheader("Filters")
        search = st.text_input("Search (company/role/location/source)")
        status = st.selectbox("Status", ["All"] + STATUSES, index=0)
        overdue_only = st.checkbox("Overdue actions only", value=False)

        st.divider()
        default_followup_days = st.number_input("Default follow-up after apply (days)", 1, 30, 7)

        st.divider()
        logout_button()

    df = fetch_df(conn, search=search, status=status, overdue_only=overdue_only)
    if not df.empty:
        df["overdue"] = df.apply(
            lambda r: compute_overdue(r.get("next_action_date") or r.get("followup_date"), r.get("status")),
            axis=1
        )
    else:
        df["overdue"] = []

    # Top metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", int(len(df)))
    c2.metric("Applied", int((df["status"] == "Applied").sum()) if not df.empty else 0)
    c3.metric("Interviewing", int((df["status"] == "Interviewing").sum()) if not df.empty else 0)
    c4.metric("Overdue", int(df["overdue"].sum()) if not df.empty else 0)

    st.divider()

    page = st.radio(
        "",
        ["Dashboard", "Board", "All Applications", "Add / Edit", "Export"],
        horizontal=True,
        key="page"
    )

    # ---------------- Dashboard ----------------
    if page == "Dashboard":
        left, right = st.columns([4, 8])

        with left:
            st.subheader("Resume")

            ids = ensure_profile_ids(conn)
            profile_id = ids["profile_id"]          # settings
            profile_app_id = ids["application_id"]  # documents FK

            docs = list_documents(conn, int(profile_app_id))
            resume_docs = [d for d in docs if (d["doc_type"] if isinstance(d, dict) else d[3]) == "Resume"]

            if resume_docs:
                d0 = resume_docs[0]  # already ordered desc
                fname = d0["filename"] if isinstance(d0, dict) else d0[1]
                st.write(f"Latest: **{fname}**")
            else:
                st.info("No resume uploaded yet.")

            # ✅ Single resume uploader, no doc_type selector
            resume_file = st.file_uploader(
                "Upload your resume (PDF/DOCX).",
                type=["pdf", "docx"],
                key="resume_uploader_single"
            )
            if resume_file is not None:
                ok = add_document(
                    conn,
                    int(profile_app_id),
                    resume_file.name,
                    resume_file.type or "application/octet-stream",
                    resume_file.getvalue(),
                    "Resume"
                )
                if ok:
                    # keep only the latest resume (delete older ones)
                    latest_docs = list_documents(conn, int(profile_app_id))
                    latest_resume = next((d for d in latest_docs if (d["doc_type"] if isinstance(d, dict) else d[3]) == "Resume"), None)
                    if latest_resume:
                        keep_id = latest_resume["id"] if isinstance(latest_resume, dict) else latest_resume[0]
                        delete_docs_by_type_except(conn, int(profile_app_id), "Resume", int(keep_id))

                    st.success("Resume uploaded (latest kept).")
                else:
                    st.warning("Skipped duplicate resume upload.")
                st.rerun()

            # Optional: show latest resume download/delete
            docs2 = list_documents(conn, int(profile_app_id))
            resume_docs2 = [d for d in docs2 if (d["doc_type"] if isinstance(d, dict) else d[3]) == "Resume"]
            if resume_docs2:
                d0 = resume_docs2[0]
                doc_id = d0["id"] if isinstance(d0, dict) else d0[0]
                filename = d0["filename"] if isinstance(d0, dict) else d0[1]
                st.caption("Resume controls")
                a, b = st.columns([1, 1])
                if a.button("Download resume", key="dl_resume_latest"):
                    full = get_document(conn, int(doc_id))
                    content = full["content"] if isinstance(full, dict) else full[4]
                    mime = (full.get("mime_type") if isinstance(full, dict) else full[2]) or "application/octet-stream"
                    st.download_button(
                        "Click to download",
                        data=content,
                        file_name=filename,
                        mime=mime,
                        key="dl_resume_latest_btn",
                    )
                if b.button("Delete resume", key="del_resume_latest"):
                    delete_document(conn, int(doc_id))
                    st.warning("Resume deleted.")
                    st.rerun()

            

        with right:
            st.subheader("Status Overview")
            if df.empty:
                st.info("No applications yet.")
            else:
                donut_status_chart(df)

            st.divider()
            st.subheader("Action Items this week")

            if df.empty:
                st.info("No action items.")
            else:
                today = date.today()
                week_end = today + timedelta(days=7)

                def parse_date(x):
                    try:
                        return datetime.strptime(str(x), "%Y-%m-%d").date()
                    except Exception:
                        return None

                items = []
                for _, r in df.iterrows():
                    d = parse_date(r.get("next_action_date"))
                    if d and d <= week_end and (r.get("status") not in ["Rejected", "Withdrawn"]):
                        items.append((d, r.to_dict()))
                items.sort(key=lambda t: t[0])

                if not items:
                    st.write("Nothing due in next 7 days.")
                else:
                    for d, r in items:
                        label = f"{safe_str(r.get('next_action')) or 'Next action'} — {safe_str(r.get('company'))} ({safe_str(r.get('role'))})"
                        st.checkbox(label, value=False, key=f"act_{int(r.get('id'))}_{d}")

    # ---------------- Board ----------------
    elif page == "Board":
        st.subheader("Applications in Progress")
        if df.empty:
            st.info("No applications yet.")
        else:
            board_statuses = board_columns_selector()
            if not board_statuses:
                st.warning("Select at least one column.")
            else:
                cols = st.columns(len(board_statuses))
                for i, st_status in enumerate(board_statuses):
                    with cols[i]:
                        st.markdown(f"### {st_status}")
                        sub = df[df["status"] == st_status].copy()
                        if sub.empty:
                            st.caption("—")
                            continue
                        sub = sub.head(30)
                        for _, r in sub.iterrows():
                            row = normalize_row(r.to_dict())
                            app_id = int(row["id"])
                            render_card_small(row)

                            current = row.get("status") or st_status
                            idx = STATUSES.index(current) if current in STATUSES else 0
                            new_status = st.selectbox(
                                "Move",
                                STATUSES,
                                index=idx,
                                key=f"move_{app_id}",
                                label_visibility="collapsed",
                            )
                            if new_status != current:
                                quick_update_status(conn, app_id, new_status)
                                st.rerun()

                            st.write("")

    # ---------------- All Applications ----------------
    elif page == "All Applications":
        st.subheader("All Applications")

        if df.empty:
            st.info("No rows yet.")
        else:
            ids = ensure_profile_ids(conn)
            profile_id = ids["profile_id"]

            settings_key = "allapps_cols"
            widget_key = "allapps_cols_widget"

            all_cols = list(df.columns)
            always_hide = {"id"}
            default_hide = {"overdue"}

            valid_options = [c for c in all_cols if c not in always_hide]

            suggested_default = [
                c for c in [
                    "company", "role", "location", "work_model", "salary_range",
                    "status", "applied_date", "interview_stage", "interview_date",
                    "next_action", "next_action_date", "priority", "source", "updated_at"
                ]
                if c in valid_options and c not in default_hide
            ]
            if not suggested_default:
                suggested_default = [c for c in valid_options if c not in default_hide]

            # Load once per session
            if widget_key not in st.session_state:
                saved_cols = get_setting(conn, profile_id, settings_key, default=None)
                if isinstance(saved_cols, list):
                    saved_cols = [c for c in saved_cols if c in valid_options]
                else:
                    saved_cols = None
                st.session_state[widget_key] = saved_cols if saved_cols else suggested_default

            def _persist_allapps_cols():
                cols = st.session_state.get(widget_key, [])
                cols = [c for c in cols if c in valid_options]

                conn2 = get_conn()
                try:
                    ids2 = ensure_profile_ids(conn2)
                    set_setting(conn2, ids2["profile_id"], settings_key, cols)
                finally:
                    try:
                        conn2.close()
                    except Exception:
                        pass

            with st.expander("Table columns", expanded=False):
                st.multiselect(
                    "Choose fields to display",
                    options=valid_options,
                    key=widget_key,
                    on_change=_persist_allapps_cols,
                )

            chosen_cols = st.session_state.get(widget_key, [])
            if not chosen_cols:
                st.warning("Select at least one column to display.")
                st.stop()

            header_cols = st.columns([1] * len(chosen_cols) + [1])
            for i, col in enumerate(chosen_cols):
                header_cols[i].markdown(f"**{col}**")
            header_cols[-1].markdown("**Edit**")
            st.divider()

            for _, r in df.iterrows():
                app_id = int(r["id"])
                row_cols = st.columns([1] * len(chosen_cols) + [1])

                for i, col in enumerate(chosen_cols):
                    val = r.get(col)
                    row_cols[i].write("—" if pd.isna(val) or val is None or str(val).strip() == "" else str(val))

                if row_cols[-1].button("✏️", key=f"row_edit_{app_id}"):
                    st.session_state["edit_id"] = app_id
                    st.session_state["_nav_to"] = "Add / Edit"
                    st.rerun()

    # ---------------- Add / Edit ----------------
    elif page == "Add / Edit":
        st.subheader("Add / Edit")
        left, right = st.columns([1, 1])

        with left:
            st.markdown("### Add new")
            with st.form("add_form", clear_on_submit=True):
                company = st.text_input("Company *")
                role = st.text_input("Role *")
                location = st.text_input("Location")
                job_url = st.text_input("Job URL")
                source = st.text_input("Source (LinkedIn/Referral/etc.)")

                work_model = st.selectbox("Work model", [""] + WORK_MODELS, index=0)
                salary_range = st.text_input("Salary range (optional)")

                status_new = st.selectbox("Status *", STATUSES, index=STATUSES.index("Applied") if "Applied" in STATUSES else 0)
                applied_date = st.date_input("Date applied", value=date.today())

                interview_stage = st.selectbox("Interview stage", [""] + INTERVIEW_STAGES, index=0)
                interview_date = st.date_input("Interview date (optional)", value=None)

                next_action = st.text_input("Next action (optional)")
                next_action_date = st.date_input("Next action date (optional)", value=default_followup(applied_date, 7))

                priority = st.selectbox("Priority", [""] + PRIORITIES, index=0)

                contact = st.text_input("Contact (name/email)")
                notes = st.text_area("Notes", height=120)

                company_research = st.text_area("Company research (optional)", height=90)
                phone_screen_notes = st.text_area("Phone screen notes (optional)", height=90)

                if st.form_submit_button("Add"):
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
                            "followup_date": None,
                            "work_model": work_model or None,
                            "salary_range": salary_range.strip() or None,
                            "interview_stage": interview_stage or None,
                            "interview_date": format_date(interview_date) if interview_date else None,
                            "next_action": next_action.strip() or None,
                            "next_action_date": format_date(next_action_date) if next_action_date else None,
                            "priority": priority or None,
                            "salary": None,
                            "contact": contact.strip() or None,
                            "notes": notes.strip() or None,
                            "company_research": company_research.strip() or None,
                            "phone_screen_notes": phone_screen_notes.strip() or None,
                        })
                        st.success("Added. You can edit + attach files on the right.")
                        st.session_state["edit_id"] = new_id
                        st.rerun()

        with right:
            st.markdown("### Edit existing")

            if df.empty:
                st.info("Nothing to edit yet.")
            else:
                app_ids = df["id"].tolist()
                pref = st.session_state.get("edit_id", app_ids[0])
                if pref not in app_ids:
                    pref = app_ids[0]

                selected_id = st.selectbox("Select ID", app_ids, index=app_ids.index(pref), key="edit_select")
                row_df = df[df["id"] == selected_id].iloc[0].to_dict()

                with st.form("edit_form"):
                    company = st.text_input("Company *", value=row_df.get("company") or "")
                    role = st.text_input("Role *", value=row_df.get("role") or "")
                    location = st.text_input("Location", value=row_df.get("location") or "")
                    job_url = st.text_input("Job URL", value=row_df.get("job_url") or "")
                    source_val = st.text_input("Source", value=row_df.get("source") or "")

                    work_model = st.selectbox("Work model", [""] + WORK_MODELS,
                                              index=([""] + WORK_MODELS).index(row_df.get("work_model") or ""),
                                              key="ewm")
                    salary_range = st.text_input("Salary range", value=row_df.get("salary_range") or "")

                    status_edit = st.selectbox("Status *", STATUSES,
                                               index=STATUSES.index(row_df.get("status") or "Applied"),
                                               key="estatus")

                    ad = pd_to_date(row_df.get("applied_date")) or date.today()
                    applied_date = st.date_input("Date applied", value=ad, key="ead")

                    interview_stage = st.selectbox("Interview stage", [""] + INTERVIEW_STAGES,
                                                   index=([""] + INTERVIEW_STAGES).index(row_df.get("interview_stage") or ""),
                                                   key="eis")
                    idt = pd_to_date(row_df.get("interview_date"))
                    interview_date = st.date_input("Interview date (optional)", value=idt, key="eidate")

                    next_action = st.text_input("Next action", value=row_df.get("next_action") or "")
                    nad = pd_to_date(row_df.get("next_action_date"))
                    next_action_date = st.date_input("Next action date (optional)", value=nad, key="enad")

                    priority = st.selectbox("Priority", [""] + PRIORITIES,
                                            index=([""] + PRIORITIES).index(row_df.get("priority") or ""),
                                            key="eprio")

                    contact = st.text_input("Contact", value=row_df.get("contact") or "")
                    notes = st.text_area("Notes", height=120, value=row_df.get("notes") or "")

                    company_research = st.text_area("Company research", height=90, value=row_df.get("company_research") or "")
                    phone_screen_notes = st.text_area("Phone screen notes", height=90, value=row_df.get("phone_screen_notes") or "")

                    c1, c2 = st.columns(2)
                    save = c1.form_submit_button("Save")
                    dele = c2.form_submit_button("Delete")

                    if save:
                        err = validate_required(company, role)
                        if err:
                            st.error(err)
                        else:
                            update_app(conn, int(selected_id), {
                                "company": company.strip(),
                                "role": role.strip(),
                                "location": location.strip() or None,
                                "job_url": job_url.strip() or None,
                                "source": source_val.strip() or None,
                                "status": status_edit,
                                "applied_date": format_date(applied_date),
                                "followup_date": row_df.get("followup_date"),
                                "work_model": work_model or None,
                                "salary_range": salary_range.strip() or None,
                                "interview_stage": interview_stage or None,
                                "interview_date": format_date(interview_date) if interview_date else None,
                                "next_action": next_action.strip() or None,
                                "next_action_date": format_date(next_action_date) if next_action_date else None,
                                "priority": priority or None,
                                "salary": row_df.get("salary"),
                                "contact": contact.strip() or None,
                                "notes": notes.strip() or None,
                                "company_research": company_research.strip() or None,
                                "phone_screen_notes": phone_screen_notes.strip() or None,
                            })
                            st.success("Updated.")
                            st.rerun()

                    if dele:
                        delete_app(conn, int(selected_id))
                        st.warning("Deleted.")
                        st.rerun()

                st.divider()
                upload_attachments_block(conn, selected_id, key_prefix=f"edit_{selected_id}", title="Attachments (Documents / Emails)")

    # ---------------- Export ----------------
    elif page == "Export":
        st.subheader("Export")
        if df.empty:
            st.info("No data to export.")
        else:
            export_df = df.drop(columns=["overdue"], errors="ignore")
            st.download_button(
                "Download CSV",
                export_df.to_csv(index=False).encode("utf-8"),
                file_name="job_search_hq.csv",
                mime="text/csv"
            )
