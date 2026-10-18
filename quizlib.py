"""Shared logic for the SQL quiz: settings, SQL checks, database access.

Used by the Streamlit app (app.py) and by the CI check (scripts/check_quiz.py).
Nothing in here knows about Streamlit, so it is easy to test.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from decimal import Decimal
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
QUESTIONS_FILE = ROOT / "questions.json"
MAX_ROWS = 500          # never send more than this many rows to the browser

load_dotenv(ROOT / ".env")   # local runs only; .env is in .gitignore


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def setting(name: str, default: str | None = None) -> str | None:
    """Read a setting from the environment (.env locally, GitHub Secrets in CI).

    On Streamlit Community Cloud, top-level secrets are also exposed as
    environment variables, so the same lookup works there too.
    """
    value = os.getenv(name)
    if value:
        return value
    try:  # fall back to st.secrets if running inside Streamlit
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


def _connect(user_var: str, password_var: str):
    user = setting(user_var)
    password = setting(password_var)
    if not user or not password:
        raise RuntimeError(f"Missing setting {user_var} or {password_var}.")
    return psycopg2.connect(
        host=setting("DB_HOST", "localhost"),
        port=setting("DB_PORT", "5432"),
        dbname=setting("DB_NAME", "postgres"),
        user=user,
        password=password,
        sslmode=setting("DB_SSLMODE", "require"),
        connect_timeout=10,
    )


def reader_connection():
    """Connection as quiz_reader: SELECT on quiz tables only."""
    return _connect("DB_READER_USER", "DB_READER_PASSWORD")


def app_connection():
    """Connection as quiz_app: INSERT/SELECT on app tables only."""
    return _connect("DB_APP_USER", "DB_APP_PASSWORD")


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------
def load_questions(path: Path = QUESTIONS_FILE) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["questions"]


# ---------------------------------------------------------------------------
# Checking and running the taker's SQL
# ---------------------------------------------------------------------------
_ALLOWED_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def clean_sql(sql: str) -> str:
    """Return the SQL ready to run, or raise ValueError with a friendly reason.

    These checks give quick feedback. The real protection is in the
    database: quiz_reader can only SELECT, and every query runs in a
    read-only transaction.
    """
    text = (sql or "").strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    if not text:
        raise ValueError("Please type a query first.")
    if ";" in text:
        raise ValueError("Please run one statement at a time (remove the extra ';').")
    if not _ALLOWED_START.match(text):
        raise ValueError("Only SELECT queries (or WITH ... SELECT) are allowed in this quiz.")
    return text


def run_readonly(sql: str) -> tuple[list[str], list[tuple]]:
    """Run one SELECT as quiz_reader in a read-only transaction.

    Returns (column_names, rows). Raises ValueError for rejected SQL and
    psycopg2.Error for database errors (syntax errors, missing columns...).
    """
    query = clean_sql(sql)
    conn = reader_connection()
    try:
        with conn.cursor() as cur:
            # Must be the first statement of the transaction.
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '5s'")
            cur.execute("SET LOCAL search_path TO quiz")
            cur.execute(query)
            if cur.description is None:
                raise ValueError("That statement did not return any rows.")
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(MAX_ROWS)
        return columns, rows
    finally:
        conn.rollback()     # nothing is ever committed by a quiz query
        conn.close()


# ---------------------------------------------------------------------------
# Comparing results with the expected answer
# ---------------------------------------------------------------------------
def normalize_value(value):
    """Make database values comparable with the JSON answer key."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        number = round(float(value), 4)
        return int(number) if number.is_integer() else number
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    return str(value)


def normalize_rows(rows) -> list[list]:
    return [[normalize_value(v) for v in row] for row in rows]


def results_match(actual_rows, expected_rows, ordered: bool) -> bool:
    """Compare result sets by value. Column names do not matter.

    If ordered is True the row order must match too.
    """
    actual = normalize_rows(actual_rows)
    expected = normalize_rows(expected_rows)
    if ordered:
        return actual == expected
    key = lambda row: json.dumps(row, default=str)  # noqa: E731
    return sorted(actual, key=key) == sorted(expected, key=key)


# ---------------------------------------------------------------------------
# Saving answers and the audit log (parameterized SQL, never f-strings)
# ---------------------------------------------------------------------------
def save_submission(user_id: str, user_email: str, question_id: str, sql_text: str) -> None:
    conn = app_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.submissions (user_id, user_email, question_id, sql_text)
                VALUES (%s, %s, %s, %s)
                """,
                (user_id, user_email, question_id, sql_text),
            )
        conn.commit()
    finally:
        conn.close()


def log_event(user_id: str, user_email: str, action: str, question_id: str | None,
              sql_text: str | None, success: bool, row_count: int | None = None,
              error: str | None = None) -> None:
    conn = app_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app.audit_log
                    (user_id, user_email, action, question_id, sql_text, success, row_count, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, user_email, action, question_id, sql_text, success, row_count, error),
            )
        conn.commit()
    finally:
        conn.close()


def latest_submissions(user_id: str) -> dict[str, dict]:
    """The user's most recent saved answer for each question."""
    conn = app_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (question_id) question_id, sql_text, saved_at
                FROM app.submissions
                WHERE user_id = %s
                ORDER BY question_id, saved_at DESC
                """,
                (user_id,),
            )
            return {q: {"sql": s, "saved_at": t} for q, s, t in cur.fetchall()}
    finally:
        conn.close()
