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

    return psycopg2.connect(
        db_url,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


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
                updated_at TEXT NOT NULL,

                work_model TEXT,
                salary_range TEXT,
                interview_stage TEXT,
                interview_date TEXT,
                next_action TEXT,
                next_action_date TEXT,
                priority TEXT,
                company_research TEXT,
                phone_screen_notes TEXT
            )
        """)

        # documents
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id SERIAL PRIMARY KEY,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                mime_type TEXT,
                content BYTEA NOT NULL,
                uploaded_at TEXT NOT NULL,
                doc_type TEXT DEFAULT 'Document',
                content_hash TEXT NOT NULL
            )
        """)

        # safe migrations
        cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_type TEXT DEFAULT 'Document'")
        cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT")
        cur.execute("""
            UPDATE documents
               SET content_hash = COALESCE(content_hash, md5(filename || '|' || uploaded_at || '|' || COALESCE(doc_type,'Document')))
             WHERE content_hash IS NULL
        """)
        cur.execute("ALTER TABLE documents ALTER COLUMN content_hash SET NOT NULL")

        # dedupe
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS documents_app_type_hash_uniq
            ON documents(application_id, doc_type, content_hash)
        """)

        # profile row marker (for settings) + link to a real applications row
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_profile (
                id SERIAL PRIMARY KEY,
                label TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                application_id INTEGER UNIQUE
            )
        """)
        cur.execute("ALTER TABLE app_profile ADD COLUMN IF NOT EXISTS application_id INTEGER")
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE constraint_name = 'app_profile_application_id_fkey'
                      AND table_name = 'app_profile'
                ) THEN
                    ALTER TABLE app_profile
                    ADD CONSTRAINT app_profile_application_id_fkey
                    FOREIGN KEY (application_id) REFERENCES applications(id)
                    ON DELETE CASCADE;
                END IF;
            END $$;
        """)

        # persistent settings
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id SERIAL PRIMARY KEY,
                profile_id INTEGER NOT NULL REFERENCES app_profile(id) ON DELETE CASCADE,
                setting_key TEXT NOT NULL,
                setting_value JSONB,
                updated_at TEXT NOT NULL,
                UNIQUE(profile_id, setting_key)
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS user_settings_profile_key_idx
            ON user_settings(profile_id, setting_key);
        """)

    conn.commit()
