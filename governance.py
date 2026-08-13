"""Governance — the only path from a question to the warehouse.

Nothing reaches DuckDB except through `run()`. The rules are enforced by parsing the SQL,
not by pattern-matching strings, because string matching is how governance layers get
bypassed: `DROP/**/TABLE`, `dRoP`, and a hundred other spellings all defeat a regex and
none of them defeat a parser.

What is enforced:
  · read-only    — SELECT/WITH only. No DDL, DML, COPY, ATTACH, PRAGMA.
  · single statement — no `; DROP ...` riders.
  · table allow-list — only tables declared in the catalog.
  · PII           — classified columns are refused for every role, including Analyst.
  · role policy   — metric access, closed under derivation (see catalog).
  · row cap       — a LIMIT is imposed if the query lacks one.
  · audit         — every attempt is logged, allowed or refused.
"""

import importlib.util
import json
import os
from datetime import date, datetime

import duckdb
import sqlglot
from sqlglot import exp

import catalog as cat

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "warehouse.duckdb")
AUDIT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "audit_log.jsonl")
GENERATOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "generate.py")
MAX_ROWS = 5_000
DIALECT = "duckdb"


class Refused(Exception):
    """Raised when a query violates policy. The message is shown to the user."""

    def __init__(self, reason: str, category: str):
        super().__init__(reason)
        self.reason = reason
        self.category = category


def _audit(event: dict) -> None:
    os.makedirs(os.path.dirname(AUDIT_PATH), exist_ok=True)
    event["at"] = datetime.now().isoformat(timespec="seconds")
    with open(AUDIT_PATH, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")


def can_access(role: str, metric_id: str) -> bool:
    return metric_id in cat.ROLES[role]["allowed"]


# --- SQL validation ------------------------------------------------------------------

WRITE_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.TruncateTable, exp.Command,
)


def validate(sql: str, role: str) -> dict:
    """Parse and check. Returns lineage on success; raises Refused otherwise."""
    try:
        statements = sqlglot.parse(sql, dialect=DIALECT)
    except Exception as e:
        raise Refused(f"I couldn't parse that query safely: {e}", "unparseable")

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise Refused(
            "Only one statement may run at a time. Multi-statement queries are refused.",
            "multi_statement",
        )

    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.With, exp.Subquery)):
        raise Refused(
            "Only read queries are allowed. This product cannot modify the warehouse.",
            "not_read_only",
        )
    for node in tree.walk():
        if isinstance(node, WRITE_NODES):
            raise Refused(
                "That query would modify or administer the warehouse, which is never "
                "permitted from here.",
                "not_read_only",
            )

    tables = {t.name for t in tree.find_all(exp.Table) if t.name}
    unknown = sorted(t for t in tables if t not in cat.TABLES)
    if unknown:
        raise Refused(
            f"`{'`, `'.join(unknown)}` is not in the governed catalog, so I won't query it.",
            "table_not_allowed",
        )

    # PII: refused for every role. A star-select on a PII table counts as requesting it.
    pii_by_table = {t: set(m["pii"]) for t, m in cat.TABLES.items() if m["pii"]}
    touched_pii_tables = tables & set(pii_by_table)
    if touched_pii_tables:
        if any(isinstance(s, exp.Star) for s in tree.find_all(exp.Star)):
            raise Refused(
                "That would select every column of a table containing personal data. "
                "PII is not available to any role.",
                "pii",
            )
        wanted = {c.name for c in tree.find_all(exp.Column) if c.name}
        for t in touched_pii_tables:
            hit = sorted(wanted & pii_by_table[t])
            if hit:
                raise Refused(
                    f"`{'`, `'.join(hit)}` is classified as personal data and is masked "
                    "for every role, including Analyst.",
                    "pii",
                )

    return {"tables": sorted(tables), "statement": type(tree).__name__.lower()}


def _cap(sql: str) -> str:
    tree = sqlglot.parse_one(sql, dialect=DIALECT)
    if not tree.args.get("limit"):
        tree = tree.limit(MAX_ROWS)
    return tree.sql(dialect=DIALECT)


# --- Freshness -----------------------------------------------------------------------
# Every series is generated relative to `date.today()`, so a warehouse built yesterday is
# not merely short a day: the intervention log keeps moving with the calendar while the
# planted spend cut stays put, so the causal engine ends up splitting pre/post on a date
# the data no longer breaks at. Rebuilding is cheap (~2s) and makes the app correct on any
# day it happens to be opened — including a cloud deploy, which starts with no warehouse
# at all because the file is git-ignored.

_fresh = False


def _max_date() -> date:
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        return con.execute("SELECT MAX(date) FROM fact_market_daily").fetchone()[0]
    finally:
        con.close()


def _rebuild() -> None:
    spec = importlib.util.spec_from_file_location("warehouse_generator", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    # Build beside the target and swap, so a second process reading mid-build sees either
    # the old warehouse or the new one, never a half-written file.
    tmp = f"{DB_PATH}.building"
    gen.build(tmp)
    os.replace(tmp, DB_PATH)


def ensure_warehouse() -> None:
    """Build the warehouse if it is missing or no longer reaches today."""
    global _fresh
    if _fresh:
        return
    try:
        stale = not os.path.exists(DB_PATH) or _max_date() < date.today()
    except Exception:
        stale = True  # unreadable or schema-less: rebuild rather than fail the query
    if stale:
        _rebuild()
    _fresh = True


# --- Execution -----------------------------------------------------------------------

def run(sql: str, role: str, question: str = "", metric_id: str = None):
    """The only way to reach the warehouse."""
    ensure_warehouse()
    if metric_id and not can_access(role, metric_id):
        r = Refused(
            f"{role} isn't entitled to {cat.METRICS[metric_id]['label']}.", "role_policy"
        )
        _audit({"role": role, "question": question, "metric_id": metric_id,
                "outcome": "refused", "category": r.category, "sql": sql})
        raise r

    try:
        lineage = validate(sql, role)
    except Refused as r:
        _audit({"role": role, "question": question, "metric_id": metric_id,
                "outcome": "refused", "category": r.category, "sql": sql})
        raise

    capped = _cap(sql)
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = con.execute(capped).fetchdf()
    finally:
        con.close()

    _audit({"role": role, "question": question, "metric_id": metric_id,
            "outcome": "allowed", "tables": lineage["tables"],
            "rows": len(df), "sql": capped})
    return df


def metric_series(metric_id: str, market: str, role: str, days: int = 90,
                  question: str = ""):
    return run(cat.series_sql(metric_id, market, days), role, question, metric_id)


def metric_panel(metric_id: str, markets: list, role: str, days: int = 90,
                 question: str = ""):
    return run(cat.panel_sql(metric_id, markets, days), role, question, metric_id)


def audit_tail(n: int = 50) -> list:
    if not os.path.exists(AUDIT_PATH):
        return []
    with open(AUDIT_PATH) as f:
        lines = f.readlines()[-n:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))
