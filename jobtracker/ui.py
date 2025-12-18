import streamlit as st
from datetime import date,datetime

from jobtracker.auth import logout_button
from jobtracker.repository import fetch_df, insert_app, update_app, delete_app
from jobtracker.service import (
    STATUSES, format_date, validate_required, default_followup, compute_overdue
)

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

    with tabs[0]:
        st.subheader("Applications")
        if df.empty:
            st.info("No rows yet. Add your first application in Add / Edit.")
        else:
            show_cols = [
                "id","company","role","location","status",
                "applied_date","followup_date","overdue","source",
                "job_url","contact","salary","updated_at"
            ]
            st.dataframe(df[show_cols], width="content", hide_index=True)

    with tabs[1]:
        st.subheader("Add / Edit application")
        left, right = st.columns([1, 1])

        # Add
        with left:
            st.markdown("### Add new")
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

                if st.form_submit_button("Add"):
                    err = validate_required(company, role)
                    if err:
                        st.error(err)
                    else:
                        insert_app(conn, {
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
                        st.success("Added.")
                        st.rerun()

        # Edit/Delete
        with right:
            st.markdown("### Edit / Delete")
            if df.empty:
                st.info("Nothing to edit yet.")
            else:
                app_ids = df["id"].tolist()
                selected_id = st.selectbox("Select ID", app_ids)
                row_df = df[df["id"] == selected_id].iloc[0].to_dict()

                with st.form("edit_form"):
                    company = st.text_input("Company *", value=row_df.get("company", ""))
                    role = st.text_input("Role *", value=row_df.get("role", ""))
                    location = st.text_input("Location", value=row_df.get("location") or "")
                    job_url = st.text_input("Job URL", value=row_df.get("job_url") or "")
                    source = st.text_input("Source", value=row_df.get("source") or "")
                    status_edit = st.selectbox("Status *", STATUSES, index=STATUSES.index(row_df.get("status", "Applied")))

                    ad = row_df.get("applied_date")
                    fd = row_df.get("followup_date")

                    applied_date = st.date_input("Applied date", value=pd_to_date(ad) or date.today(), key="edit_applied")
                    followup_enabled = st.checkbox("Has follow-up date", value=bool(fd))
                    followup_date = st.date_input(
                        "Follow-up date",
                        value=pd_to_date(fd) or default_followup(date.today(), int(default_followup_days)),
                        key="edit_followup"
                    ) if followup_enabled else None

                    salary = st.text_input("Salary", value=row_df.get("salary") or "")
                    contact = st.text_input("Contact", value=row_df.get("contact") or "")
                    notes = st.text_area("Notes", height=120, value=row_df.get("notes") or "")

                    c1, c2 = st.columns(2)
                    if c1.form_submit_button("Save changes"):
                        err = validate_required(company, role)
                        if err:
                            st.error(err)
                        else:
                            update_app(conn, int(selected_id), {
                                "company": company.strip(),
                                "role": role.strip(),
                                "location": location.strip() or None,
                                "job_url": job_url.strip() or None,
                                "source": source.strip() or None,
                                "status": status_edit,
                                "applied_date": format_date(applied_date),
                                "followup_date": format_date(followup_date) if followup_date else None,
                                "salary": salary.strip() or None,
                                "contact": contact.strip() or None,
                                "notes": notes.strip() or None,
                            })
                            st.success("Updated.")
                            st.rerun()

                    if c2.form_submit_button("Delete"):
                        delete_app(conn, int(selected_id))
                        st.warning("Deleted.")
                        st.rerun()

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


def pd_to_date(s):
    if not s:
        return None
    try:
        
        return datetime.strptime(str(s), "%Y-%m-%d").date()
    except Exception:
        return None
