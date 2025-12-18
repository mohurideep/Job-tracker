import os
import streamlit as st
import psycopg2
import psycopg2.extras

def _get_secret(key: str):
    try:
        return st.secrets.get(key, None)
    except Exception:
        return None

def get_conn():
    db_url = _get_secret("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL not set.\n"
            "Local: set env var DATABASE_URL\n"
            "Cloud: add DATABASE_URL to Streamlit Secrets"
        )

    conn = psycopg2.connect(
        db_url,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    return conn

def init_db(conn):
    with conn.cursor() as cur:
        # applications
        cur.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id SERIAL PRIMARY KEY,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                location TEXT,
                job_url TEXT,
                source TEXT,
                status TEXT NOT NULL,
                applied_date TEXT,
                followup_date TEXT,
                salary TEXT,
                contact TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # documents (attachments) - includes dedupe + type
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                mime_type TEXT,
                doc_type TEXT NOT NULL DEFAULT 'Document',
                content_hash TEXT NOT NULL,
                content BYTEA NOT NULL,
                uploaded_at TEXT NOT NULL,
                UNIQUE(application_id, content_hash)
            )
        """)

    conn.commit()
