"""Unit tests that need no database (run in CI before the live check)."""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import quizlib  # noqa: E402


@pytest.mark.parametrize("sql", [
    "SELECT 1",
    "select * from students;",
    "  WITH t AS (SELECT 1) SELECT * FROM t ;; ",
])
def test_clean_sql_accepts_single_select(sql):
    assert quizlib.clean_sql(sql).lower().startswith(("select", "with"))
    assert not quizlib.clean_sql(sql).endswith(";")


@pytest.mark.parametrize("sql, reason", [
    ("", "type a query"),
    ("DELETE FROM students", "Only SELECT"),
    ("DROP TABLE students", "Only SELECT"),
    ("SELECT 1; DELETE FROM students", "one statement"),
])
def test_clean_sql_rejects(sql, reason):
    with pytest.raises(ValueError, match=reason):
        quizlib.clean_sql(sql)


def test_results_match_ignores_number_types():
    actual = [("Ava Chen", 4, Decimal("3.93"))]
    expected = [["Ava Chen", 4, 3.93]]
    assert quizlib.results_match(actual, expected, ordered=True)


def test_results_match_respects_order_only_when_asked():
    a = [("x", 1), ("y", 2)]
    b = [["y", 2], ["x", 1]]
    assert not quizlib.results_match(a, b, ordered=True)
    assert quizlib.results_match(a, b, ordered=False)


def test_results_match_detects_missing_rows():
    assert not quizlib.results_match([("x", 1)], [["x", 1], ["y", 2]], ordered=False)


def test_questions_file_is_complete():
    questions = quizlib.load_questions()
    assert sum(q["points"] for q in questions) == 20
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))
    for q in questions:
        assert q["prompt"] and q["hint_sql"]
        assert q["expected"]["columns"], f"{q['id']} has no expected result yet"
