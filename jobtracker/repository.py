import hashlib
import pandas as pd
from datetime import date, datetime
import psycopg2
import psycopg2.extras

DATE_FMT = "%Y-%m-%d"


def now_str():
    return datetime.now().strftime(DATE_FMT)


def _ts():
    return datetime.now().strftime("%Y-%m-%d")


# ---------------- Applications ----------------
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
        where.append("(next_action_date IS NOT NULL AND next_action_date < %s AND status NOT IN ('Rejected','Withdrawn'))")
        params.append(date.today().strftime(DATE_FMT))

    if where:
        q += " WHERE " + " AND ".join(where)

    q += " ORDER BY COALESCE(next_action_date, followup_date, '9999-12-31') ASC, id DESC"

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
             salary, contact, notes, created_at, updated_at,
             work_model, salary_range, interview_stage, interview_date, next_action, next_action_date, priority,
             company_research, phone_screen_notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                row["company"], row["role"], row.get("location"), row.get("job_url"), row.get("source"),
                row["status"], row.get("applied_date"), row.get("followup_date"),
                row.get("salary"), row.get("contact"), row.get("notes"),
                t, t,
                row.get("work_model"), row.get("salary_range"), row.get("interview_stage"), row.get("interview_date"),
                row.get("next_action"), row.get("next_action_date"), row.get("priority"),
                row.get("company_research"), row.get("phone_screen_notes"),
            ),
        )
        new_id = cur.fetchone()["id"]
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
              updated_at=%s,

              work_model=%s,
              salary_range=%s,
              interview_stage=%s,
              interview_date=%s,
              next_action=%s,
              next_action_date=%s,
              priority=%s,
              company_research=%s,
              phone_screen_notes=%s
            WHERE id=%s
            """,
            (
                row["company"], row["role"], row.get("location"), row.get("job_url"), row.get("source"),
                row["status"], row.get("applied_date"), row.get("followup_date"),
                row.get("salary"), row.get("contact"), row.get("notes"),
                t,
                row.get("work_model"), row.get("salary_range"), row.get("interview_stage"), row.get("interview_date"),
                row.get("next_action"), row.get("next_action_date"), row.get("priority"),
                row.get("company_research"), row.get("phone_screen_notes"),
                app_id
            ),
        )
    conn.commit()


def delete_app(conn, app_id: int):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM applications WHERE id=%s", (app_id,))
    conn.commit()


def quick_update_status(conn, app_id: int, new_status: str):
    t = now_str()
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE applications SET status=%s, updated_at=%s WHERE id=%s",
            (new_status, t, app_id),
        )
    conn.commit()


# ---------------- Documents ----------------
def _sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def add_document(conn, app_id: int, filename: str, mime_type: str, content: bytes, doc_type: str = "Document") -> bool:
    """
    Inserts a document with required content_hash. Returns False if duplicate.
    """
    content_hash = _sha256_hex(content)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (application_id, filename, mime_type, content, uploaded_at, doc_type, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (application_id, doc_type, content_hash) DO NOTHING
            RETURNING id
            """,
            (app_id, filename, mime_type, psycopg2.Binary(content), _ts(), doc_type, content_hash),
        )
        row = cur.fetchone()

    conn.commit()
    return bool(row)


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


def delete_docs_by_type_except(conn, app_id: int, doc_type: str, keep_doc_id: int):
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM documents
            WHERE application_id=%s AND doc_type=%s AND id <> %s
            """,
            (app_id, doc_type, keep_doc_id),
        )
    conn.commit()


# ---------------- Profile (settings + linked application row) ----------------
def ensure_profile_ids(conn) -> dict:
    """
    Returns:
      { "profile_id": <app_profile.id>, "application_id": <applications.id> }

    application_id exists so documents FK always points to applications.
    """
    label = "PROFILE"
    t = now_str()

    with conn.cursor() as cur:
        cur.execute("SELECT id, application_id FROM app_profile WHERE label=%s", (label,))
        row = cur.fetchone()

        if not row:
            cur.execute(
                "INSERT INTO app_profile (label, created_at) VALUES (%s, %s) RETURNING id",
                (label, t),
            )
            profile_id = int(cur.fetchone()["id"])
            app_id = None
        else:
            profile_id = int(row["id"])
            app_id = row.get("application_id")

        if app_id is not None:
            return {"profile_id": profile_id, "application_id": int(app_id)}

        # create a real applications row to hold resume documents
        cur.execute(
            """
            INSERT INTO applications
            (company, role, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            ("(Profile)", "Resume", "Saved", t, t),
        )
        new_app_id = int(cur.fetchone()["id"])

        cur.execute(
            "UPDATE app_profile SET application_id=%s WHERE id=%s",
            (new_app_id, profile_id),
        )

    conn.commit()
    return {"profile_id": profile_id, "application_id": new_app_id}


def ensure_profile_app(conn) -> int:
    # backward-compat: returns profile_id
    return ensure_profile_ids(conn)["profile_id"]


# ---------------- Persistent Settings ----------------
def get_setting(conn, profile_id: int, setting_key: str, default=None):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT setting_value FROM user_settings WHERE profile_id=%s AND setting_key=%s",
            (profile_id, setting_key),
        )
        row = cur.fetchone()
        if not row:
            return default
        return row.get("setting_value", default)


def set_setting(conn, profile_id: int, setting_key: str, setting_value):
    t = now_str()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_settings (profile_id, setting_key, setting_value, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (profile_id, setting_key)
            DO UPDATE SET setting_value=EXCLUDED.setting_value, updated_at=EXCLUDED.updated_at
            """,
            (profile_id, setting_key, psycopg2.extras.Json(setting_value), t),
        )
    conn.commit()
