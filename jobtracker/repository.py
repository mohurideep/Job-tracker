import sqlite3
import pandas as pd
from datetime import date, datetime

DATE_FMT = "%Y-%m-%d"

def now_str():
    return datetime.now().strftime(DATE_FMT)

def fetch_df(conn: sqlite3.Connection, search="", status="All", overdue_only=False) -> pd.DataFrame:
    q = "SELECT * FROM applications"
    params = []
    where = []

    if status != "All":
        where.append("status = ?")
        params.append(status)

    if search.strip():
        s = f"%{search.strip().lower()}%"
        where.append("(LOWER(company) LIKE ? OR LOWER(role) LIKE ? OR LOWER(location) LIKE ? OR LOWER(source) LIKE ?)")
        params.extend([s, s, s, s])

    if overdue_only:
        where.append("(followup_date IS NOT NULL AND followup_date < ? AND status NOT IN ('Rejected','Withdrawn'))")
        params.append(date.today().strftime(DATE_FMT))

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY COALESCE(followup_date, '9999-12-31') ASC, id DESC"
    return pd.read_sql_query(q, conn, params=params)

def insert_app(conn: sqlite3.Connection, row: dict):
    t = now_str()
    conn.execute(
        """
        INSERT INTO applications
        (company, role, location, job_url, source, status, applied_date, followup_date,
         salary, contact, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["company"], row["role"], row.get("location"), row.get("job_url"), row.get("source"),
            row["status"], row.get("applied_date"), row.get("followup_date"),
            row.get("salary"), row.get("contact"), row.get("notes"),
            t, t
        ),
    )
    conn.commit()

def update_app(conn: sqlite3.Connection, app_id: int, row: dict):
    t = now_str()
    conn.execute(
        """
        UPDATE applications SET
          company=?,
          role=?,
          location=?,
          job_url=?,
          source=?,
          status=?,
          applied_date=?,
          followup_date=?,
          salary=?,
          contact=?,
          notes=?,
          updated_at=?
        WHERE id=?
        """,
        (
            row["company"], row["role"], row.get("location"), row.get("job_url"), row.get("source"),
            row["status"], row.get("applied_date"), row.get("followup_date"),
            row.get("salary"), row.get("contact"), row.get("notes"),
            t, app_id
        ),
    )
    conn.commit()

def delete_app(conn: sqlite3.Connection, app_id: int):
    conn.execute("DELETE FROM applications WHERE id=?", (app_id,))
    conn.commit()
