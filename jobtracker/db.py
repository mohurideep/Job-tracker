import streamlit as st
import psycopg
from psycopg.rows import dict_row

def get_conn():
    # Prefer Streamlit secrets in cloud; fallback to env if you want locally
    db_url = None
    if hasattr(st, "secrets") and "DATABASE_URL" in st.secrets:
        db_url = st.secrets["DATABASE_URL"]

    if not db_url:
        raise RuntimeError("DATABASE_URL is not set. Add it to Streamlit Secrets.")

    # dict_row lets us work with column names easily if needed
    conn = psycopg.connect(db_url, row_factory=dict_row)
    return conn

def init_db(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
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
            """
        )
    conn.commit()
