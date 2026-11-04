"""
Read-only enforcement for generated SQL.

Three independent layers, because prompting is not a security control:

  1. The statement is PARSED (sqlglot, duckdb dialect) and its AST inspected.
     Anything that is not a single read-only SELECT is rejected before it ever
     reaches the database.
  2. A row limit is injected if the query does not already have a tighter one.
  3. Execution happens on a connection opened ``read_only=True``, under a
     wall-clock timeout enforced by ``DuckDBPyConnection.interrupt()``.

Layer 1 catches intent, layer 3 catches anything layer 1 missed. A reviewer
should be able to break layer 1 and still not be able to write to the database.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp

from firesight.config import settings


class SQLValidationError(Exception):
    """The generated SQL is not a permissible read-only query."""


class SQLTimeoutError(Exception):
    """The query exceeded the configured wall-clock budget."""


# Statement types that mutate data, schema, session state, or the filesystem.
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Copy,
    exp.Attach,
    exp.Detach,
    exp.Pragma,
    exp.Set,
    exp.SetItem,
    exp.Use,
    exp.Grant,
    exp.Merge,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    # sqlglot parks statements it has no node for (ATTACH variants, EXPORT,
    # CALL, INSTALL, LOAD, ...) in Command. Treat that as hostile by default.
    exp.Command,
)

# Table functions that read outside the database or load extensions.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "read_json",
        "read_json_auto",
        "read_json_objects",
        "read_text",
        "read_blob",
        "read_ndjson",
        "read_ndjson_objects",
        "parquet_scan",
        "json_scan",
        "csv_scan",
        "glob",
        "sniff_csv",
        "delta_scan",
        "iceberg_scan",
        "postgres_scan",
        "postgres_query",
        "mysql_scan",
        "mysql_query",
        "sqlite_scan",
        "sqlite_query",
        "install",
        "load",
        "copy",
        "shell",
        "system",
        "getenv",
    }
)

ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Except,
    exp.Intersect,
    exp.Subquery,
    exp.With,
    exp.Describe,
)


@dataclass(frozen=True)
class SQLResult:
    """Outcome of one validated execution. `sql` is the query actually run."""

    sql: str
    columns: list[str]
    rows: list[tuple[Any, ...]]
    row_count: int
    truncated: bool
    elapsed_ms: float

    def as_markdown(self, max_rows: int = 20) -> str:
        if not self.rows:
            return "_(no rows)_"
        head = "| " + " | ".join(self.columns) + " |"
        rule = "| " + " | ".join("---" for _ in self.columns) + " |"
        body = [
            "| " + " | ".join("NULL" if v is None else str(v) for v in r) + " |"
            for r in self.rows[:max_rows]
        ]
        out = [head, rule, *body]
        if len(self.rows) > max_rows:
            out.append(f"_... {len(self.rows) - max_rows} more row(s)_")
        return "\n".join(out)


def validate(sql: str) -> str:
    """
    Parse `sql` and return it with a row limit enforced.

    Raises SQLValidationError on anything that is not one read-only SELECT.
    """
    if not sql or not sql.strip():
        raise SQLValidationError("empty query")

    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except Exception as e:  # sqlglot raises several unrelated types
        raise SQLValidationError(f"could not parse SQL: {e}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) == 0:
        raise SQLValidationError("no statement found")
    if len(statements) > 1:
        raise SQLValidationError(
            f"expected a single statement, found {len(statements)}; "
            "multi-statement queries are not permitted"
        )

    stmt = statements[0]
    if not isinstance(stmt, ALLOWED_ROOTS):
        raise SQLValidationError(
            f"only SELECT queries are permitted, got {type(stmt).__name__.upper()}"
        )

    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SQLValidationError(
                f"{type(node).__name__.upper()} is not permitted in a read-only query"
            )
        name: str | None = None
        if isinstance(node, exp.Anonymous):
            name = node.name
        elif isinstance(node, exp.Func):
            sql_name = getattr(node, "sql_name", None)
            name = sql_name() if callable(sql_name) else type(node).__name__
        if name and name.lower() in FORBIDDEN_FUNCTIONS:
            raise SQLValidationError(f"function {name}() is not permitted")

    return _enforce_limit(stmt)


def _enforce_limit(stmt: exp.Expression) -> str:
    """Add or tighten a LIMIT so a runaway query cannot flood the context."""
    cap = settings.sql_row_limit
    if isinstance(stmt, exp.Describe):
        return stmt.sql(dialect="duckdb")

    existing = stmt.args.get("limit")
    if existing is not None:
        try:
            current = int(existing.expression.name)
        except (AttributeError, ValueError):
            current = None
        if current is not None and current <= cap:
            return stmt.sql(dialect="duckdb")

    try:
        return stmt.limit(cap).sql(dialect="duckdb")
    except Exception:
        # Set operations and some nested forms do not accept .limit();
        # wrapping preserves semantics.
        return f"SELECT * FROM ({stmt.sql(dialect='duckdb')}) AS _capped LIMIT {cap}"


def execute(sql: str, *, validate_first: bool = True) -> SQLResult:
    """Validate then execute, on a read-only connection under a timeout."""
    import time

    final_sql = validate(sql) if validate_first else sql

    if not settings.duckdb_path.exists():
        raise SQLValidationError(
            f"no database at {settings.duckdb_path}; "
            "run `python -m firesight.ingest.structured` first"
        )

    con = duckdb.connect(str(settings.duckdb_path), read_only=True)
    result: dict[str, Any] = {}

    def run() -> None:
        try:
            cur = con.execute(final_sql)
            result["columns"] = [d[0] for d in cur.description or []]
            result["rows"] = cur.fetchall()
        except Exception as e:  # noqa: BLE001 - surfaced to the caller verbatim
            result["error"] = e

    t0 = time.perf_counter()
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=settings.sql_timeout_s)

    if worker.is_alive():
        con.interrupt()
        worker.join(timeout=5)
        con.close()
        raise SQLTimeoutError(f"query exceeded {settings.sql_timeout_s}s budget")

    elapsed_ms = (time.perf_counter() - t0) * 1000
    con.close()

    if "error" in result:
        raise result["error"]

    rows = result.get("rows", [])
    return SQLResult(
        sql=final_sql,
        columns=result.get("columns", []),
        rows=rows,
        row_count=len(rows),
        truncated=len(rows) >= settings.sql_row_limit,
        elapsed_ms=elapsed_ms,
    )
