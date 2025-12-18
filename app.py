import streamlit as st
from jobtracker.config import configure_page
from jobtracker.auth import require_login
from jobtracker.db import get_conn, init_db
from jobtracker.ui import render_app

def main():
    configure_page()
    require_login()

    conn = get_conn()
    init_db(conn)

    render_app(conn)

if __name__ == "__main__":
    main()
