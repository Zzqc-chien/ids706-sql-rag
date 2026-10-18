"""Check the quiz against the live database.

GitHub Actions runs this with the database credentials from GitHub Secrets.

  python scripts/check_quiz.py          # check (exit code 1 on any failure)
  python scripts/check_quiz.py --write  # rewrite the expected answers in questions.json

Checks:
  1. The points add up to 20 and every question has a hint.
  2. Every hint SQL runs as quiz_reader and returns exactly the expected rows.
  3. quiz_reader cannot change data.
  4. (If DB_APP_* settings are present) the audit log is append-only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # noqa: E402

import quizlib  # noqa: E402

failures: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("PASS  " if ok else "FAIL  ") + message)
    if not ok:
        failures.append(message)


def check_structure(questions: list[dict]) -> None:
    total = sum(q["points"] for q in questions)
    check(total == 20, f"points add up to 20 (got {total})")
    for q in questions:
        check(bool(q.get("hint_sql")) and bool(q.get("prompt")),
              f"{q['id']} has a prompt and a hint")


def check_answers(questions: list[dict], write: bool) -> None:
    for q in questions:
        columns, rows = quizlib.run_readonly(q["hint_sql"])
        if write:
            q["expected"] = {"columns": columns, "rows": quizlib.normalize_rows(rows)}
            print(f"WROTE {q['id']}: {len(rows)} rows")
            continue
        ok = quizlib.results_match(rows, q["expected"]["rows"], ordered=q.get("ordered", False))
        check(ok, f"{q['id']} hint SQL returns the expected {len(q['expected']['rows'])} rows")


def check_reader_is_read_only() -> None:
    conn = quizlib.reader_connection()
    try:
        with conn.cursor() as cur:
            # Try even after switching read-only mode off: privileges must still block it.
            cur.execute("SET default_transaction_read_only = off")
            cur.execute("DELETE FROM quiz.students")
        blocked = False
    except psycopg2.Error:
        blocked = True
    finally:
        conn.rollback()
        conn.close()
    check(blocked, "quiz_reader cannot DELETE quiz data")


def check_audit_log_append_only() -> None:
    if not (quizlib.setting("DB_APP_USER") and quizlib.setting("DB_APP_PASSWORD")):
        print("SKIP  audit log check (DB_APP_USER / DB_APP_PASSWORD not set)")
        return
    conn = quizlib.app_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE app.audit_log SET success = success")
        blocked = False
    except psycopg2.Error:
        blocked = True
    finally:
        conn.rollback()
        conn.close()
    check(blocked, "quiz_app cannot UPDATE the audit log")


def main() -> int:
    write = "--write" in sys.argv
    data = json.loads(quizlib.QUESTIONS_FILE.read_text(encoding="utf-8"))
    questions = data["questions"]

    print(f"Database host: {quizlib.setting('DB_HOST')}")
    check_structure(questions)
    check_answers(questions, write)

    if write:
        quizlib.QUESTIONS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Updated {quizlib.QUESTIONS_FILE.name}")
        return 0

    check_reader_is_read_only()
    check_audit_log_append_only()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed.")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
