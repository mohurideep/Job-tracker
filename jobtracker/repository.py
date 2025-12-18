import pandas as pd
from datetime import date, datetime
import hashlib

DATE_FMT = "%Y-%m-%d"

def now_str():
    return datetime.now().strftime(DATE_FMT)

def _ts():
    return datetime.now().strftime(DATE_FMT)

def fetch_df(conn, search="", status="All", overdue_only=False) -> pd.DataFrame:
    q = "SELECT * FROM applications"
    params = []
    where = []

    if status != "All":
        where.append("status = %s")
        params.append(status)

    if search.strip():
        s = f"%{search.strip().lower()}%"
        where.append("(LOWER(company) LIKE %s OR LOWER(role) LIKE %s OR LOWER(location) LIKE %s OR LOWER(source) LIKE %s)")
        params.extend([s, s, s, s])

    if overdue_only:
        where.append("(followup_date IS NOT NULL AND followup_date < %s AND status NOT IN ('Rejected','Withdrawn'))")
        params.append(date.today().strftime(DATE_FMT))

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY COALESCE(followup_date, '9999-12-31') ASC, id DESC"

    with conn.cursor() as cur:
        cur.execute(q, params)
        rows = cur.fetchall()
    return pd.DataFrame(rows)

def insert_app(conn, row: dict) -> int:
    t = now_str()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO applications
            (company, role, location, job_url, source, status, applied_date, followup_date,
             salary, contact, notes, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                row["company"], row["role"], row.get("location"), row.get("job_url"), row.get("source"),
                row["status"], row.get("applied_date"), row.get("followup_date"),
                row.get("salary"), row.get("contact"), row.get("notes"),
                t, t
            ),
        )
        res = cur.fetchone()
        new_id = res["id"] if isinstance(res, dict) else res[0]
    conn.commit()
    return int(new_id)

def update_app(conn, app_id: int, row: dict):
    t = now_str()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE applications SET
              company=%s,
              role=%s,
              location=%s,
              job_url=%s,
              source=%s,
              status=%s,
              applied_date=%s,
              followup_date=%s,
              salary=%s,
              contact=%s,
              notes=%s,
              updated_at=%s
            WHERE id=%s
            """,
            (
                row["company"], row["role"], row.get("location"), row.get("job_url"), row.get("source"),
                row["status"], row.get("applied_date"), row.get("followup_date"),
                row.get("salary"), row.get("contact"), row.get("notes"),
                t, app_id
            ),
        )
    conn.commit()

def delete_app(conn, app_id: int):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM applications WHERE id=%s", (app_id,))
    conn.commit()

# ---------- Documents (Attachments) ----------
def add_document(conn, app_id: int, filename: str, mime_type: str, content: bytes, doc_type: str = "Document") -> bool:
    content_hash = hashlib.sha256(content).hexdigest()
    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO documents (application_id, filename, mime_type, doc_type, content_hash, content, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (app_id, filename, mime_type, doc_type, content_hash, content, _ts()),
            )
            conn.commit()
            return True
        except Exception:
            # Most likely unique violation (duplicate upload). Rollback and ignore.
            conn.rollback()
            return False

def list_documents(conn, app_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, filename, mime_type, doc_type, uploaded_at
            FROM documents
            WHERE application_id=%s
            ORDER BY id DESC
            """,
            (app_id,),
        )
        return cur.fetchall()

def get_document(conn, doc_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, filename, mime_type, doc_type, content FROM documents WHERE id=%s",
            (doc_id,),
        )
        return cur.fetchone()

def delete_document(conn, doc_id: int):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id=%s", (doc_id,))
    conn.commit()
