"""
The read-only guard is a security control, so it gets adversarial tests.

Prompting the model to "only write SELECT" is not a control; this is. These
tests are the evidence for the M1 read-only enforcement requirement.
"""

import pytest

from firesight.config import settings
from firesight.retrieval.sql_guard import SQLValidationError, validate

# Each of these must be rejected by AST inspection, before touching the DB.
FORBIDDEN = [
    # --- the six statement types named in the spec ---
    "INSERT INTO departments VALUES ('XX', '00000')",
    "UPDATE departments SET fd_name = 'x'",
    "DELETE FROM incidents",
    "DROP TABLE incidents",
    "ALTER TABLE incidents ADD COLUMN x INT",
    "CREATE TABLE evil (a INT)",
    "ATTACH 'other.db' AS other",
    # --- variants that a naive keyword blocklist would miss ---
    "SELECT 1; DROP TABLE incidents",
    "select 1;drop table incidents;",
    "CREATE OR REPLACE VIEW v AS SELECT 1",
    "CREATE TEMP TABLE t AS SELECT 1",
    "TRUNCATE TABLE incidents",
    "COPY incidents TO 'out.csv'",
    "DETACH other",
    "PRAGMA database_list",
    "SET memory_limit='1GB'",
    "INSTALL httpfs",
    "LOAD httpfs",
    "BEGIN TRANSACTION",
    "COMMIT",
    "CALL pragma_version()",
    # --- filesystem / external reads ---
    "SELECT * FROM read_csv('C:/Windows/win.ini')",
    "SELECT * FROM read_parquet('secrets.parquet')",
    "SELECT * FROM glob('C:/**')",
    "SELECT getenv('ANTHROPIC_API_KEY')",
    "SELECT * FROM incidents WHERE state IN (SELECT * FROM read_csv('x.csv'))",
    # --- nonsense ---
    "",
    "   ",
    "not sql at all ;;;",
]

ALLOWED = [
    "SELECT count(*) FROM incidents",
    "SELECT state, count(*) FROM incidents GROUP BY state",
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    "SELECT * FROM incidents WHERE inc_type = '111' ORDER BY inc_date",
    "SELECT 1 UNION ALL SELECT 2",
    "SELECT m.fd_name FROM metrics_department_year m JOIN departments d "
    "ON d.state = m.state AND d.fdid = m.fdid",
    "SELECT median(response_min) FROM incidents WHERE response_min BETWEEN 0 AND 90",
]


@pytest.mark.parametrize("sql", FORBIDDEN)
def test_forbidden_sql_is_rejected(sql):
    with pytest.raises(SQLValidationError):
        validate(sql)


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed_sql_passes(sql):
    assert "SELECT" in validate(sql).upper()


def test_row_limit_is_injected_when_absent():
    out = validate("SELECT * FROM incidents")
    assert f"LIMIT {settings.sql_row_limit}" in out.upper()


def test_tighter_user_limit_is_preserved():
    out = validate("SELECT * FROM incidents LIMIT 5")
    assert "LIMIT 5" in out.upper()
    assert str(settings.sql_row_limit) not in out


def test_excessive_user_limit_is_capped():
    out = validate("SELECT * FROM incidents LIMIT 999999")
    assert "999999" not in out
    assert f"LIMIT {settings.sql_row_limit}" in out.upper()


def test_multi_statement_is_rejected_with_a_clear_reason():
    with pytest.raises(SQLValidationError, match="single statement"):
        validate("SELECT 1; SELECT 2")
