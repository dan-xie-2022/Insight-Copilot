"""Build the DuckDB warehouse the copilot queries.

The series generator in `mock_data.py` stays the source of truth for the *shape* of the
data — the planted Rome spend cut, the shared demand factor that makes parallel trends
hold, the untreated control markets. This script turns those series into a real star
schema so the agent runs genuine SQL against genuine tables, and the causal engine
estimates from query results rather than from a Python function.

Run:  python data/generate.py
"""

import os
import sys
from datetime import date, timedelta

import duckdb

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import catalog as cat  # noqa: E402
import evidence_data as ed  # noqa: E402
import mock_data as md  # noqa: E402

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "warehouse.duckdb")
DAYS = 120


def build(db_path: str = DB_PATH, days: int = DAYS) -> str:
    if os.path.exists(db_path):
        os.remove(db_path)
    con = duckdb.connect(db_path)

    # --- dimensions ------------------------------------------------------------------
    con.execute(
        """
        CREATE TABLE dim_market (
            market_id   INTEGER PRIMARY KEY,
            market_name VARCHAR NOT NULL,
            region      VARCHAR NOT NULL,
            country     VARCHAR NOT NULL
        )
        """
    )
    con.executemany(
        "INSERT INTO dim_market VALUES (?, ?, ?, ?)",
        [
            (i, m, cat.MARKETS_META[m]["region"], cat.MARKETS_META[m]["country"])
            for i, m in enumerate(cat.MARKETS, start=1)
        ],
    )
    market_id = {m: i for i, m in enumerate(cat.MARKETS, start=1)}

    end = date.today()
    dates = [end - timedelta(days=days - 1 - i) for i in range(days)]
    con.execute(
        """
        CREATE TABLE dim_date (
            date       DATE PRIMARY KEY,
            day_of_week INTEGER,
            is_weekend BOOLEAN,
            iso_week   INTEGER
        )
        """
    )
    con.executemany(
        "INSERT INTO dim_date VALUES (?, ?, ?, ?)",
        [(d, d.weekday(), d.weekday() >= 5, d.isocalendar()[1]) for d in dates],
    )

    # --- daily facts, one row per market-day ------------------------------------------
    # Pre-aggregated to daily grain: the demo's questions are all daily, and generating
    # millions of synthetic bookings would buy nothing the answers can show.
    con.execute(
        """
        CREATE TABLE fact_market_daily (
            date              DATE    NOT NULL,
            market_id         INTEGER NOT NULL,
            sessions          BIGINT,
            bookings          BIGINT,
            booking_value_usd DOUBLE,
            nightly_rate_usd  DOUBLE,
            cancelled         BIGINT,
            spend_usd         DOUBLE,
            support_tickets   BIGINT,
            csat_sum          DOUBLE,
            csat_responses    BIGINT
        )
        """
    )

    rows = []
    for m in cat.MARKETS:
        s = {
            k: dict(zip(md.series(k, m, days)["date"], md.series(k, m, days)["value"]))
            for k in ("conversion_rate", "gross_bookings", "adr", "cancellation_rate",
                      "marketing_spend", "csat", "support_tickets")
        }
        for d in dates:
            ts = __import__("pandas").Timestamp(d)
            conv = s["conversion_rate"][ts] / 100.0
            value = s["gross_bookings"][ts]
            adr = s["adr"][ts]
            bookings = max(1, round(value / max(adr, 1)))
            sessions = max(bookings, round(bookings / max(conv, 1e-6)))
            tickets = max(0, round(s["support_tickets"][ts]))
            rows.append(
                (
                    d, market_id[m], sessions, bookings, round(value, 2), round(adr, 2),
                    max(0, round(bookings * s["cancellation_rate"][ts] / 100.0)),
                    round(s["marketing_spend"][ts], 2), tickets,
                    round(s["csat"][ts] * tickets, 2), tickets,
                )
            )
    con.executemany(
        "INSERT INTO fact_market_daily VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows
    )

    # --- evidence tables --------------------------------------------------------------
    con.execute(
        """
        CREATE TABLE dim_intervention (
            intervention_id VARCHAR PRIMARY KEY,
            type            VARCHAR,
            market_id       INTEGER,
            start_date      DATE,
            end_date        DATE,
            description     VARCHAR,
            owner           VARCHAR,
            source          VARCHAR,
            blocks_control  BOOLEAN
        )
        """
    )
    con.executemany(
        "INSERT INTO dim_intervention VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (i["id"], i["type"], market_id[i["market"]], i["start"], i["end"],
             i["description"], i["owner"], i["source"], i["blocks_control"])
            for i in ed.INTERVENTIONS
        ],
    )

    con.execute(
        """
        CREATE TABLE dim_experiment (
            experiment_id VARCHAR PRIMARY KEY,
            name          VARCHAR,
            market        VARCHAR,
            hypothesis    VARCHAR,
            unit          VARCHAR,
            status        VARCHAR,
            start_date    DATE,
            end_date      DATE,
            owner         VARCHAR,
            srm_pass      BOOLEAN,
            exposed_units BIGINT,
            decision      VARCHAR
        )
        """
    )
    con.executemany(
        "INSERT INTO dim_experiment VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (e["experiment_id"], e["name"], e["market"], e["hypothesis"], e["unit"],
             e["status"], e["start"], e["end"], e["owner"], e["srm_pass"],
             e["exposed_users"], e["decision"])
            for e in ed.EXPERIMENTS
        ],
    )

    con.execute(
        """
        CREATE TABLE fact_experiment_result (
            experiment_id VARCHAR,
            metric_id     VARCHAR,
            kind          VARCHAR,
            control       DOUBLE,
            treatment     DOUBLE,
            estimate_pct  DOUBLE,
            ci_low        DOUBLE,
            ci_high       DOUBLE,
            p_value       DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO fact_experiment_result VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (e["experiment_id"], r["metric_id"], r["kind"], r["control"], r["treatment"],
             r["estimate"], r["ci"][0], r["ci"][1], r["p_value"])
            for e in ed.EXPERIMENTS
            for r in e["metrics"]
        ],
    )

    # --- PII, present precisely so governance has something real to protect -----------
    from faker import Faker

    fake = Faker()
    Faker.seed(42)
    con.execute(
        """
        CREATE TABLE dim_customer (
            customer_id   INTEGER PRIMARY KEY,
            full_name     VARCHAR,   -- pii
            email         VARCHAR,   -- pii
            phone         VARCHAR,   -- pii
            loyalty_tier  VARCHAR,
            home_market_id INTEGER
        )
        """
    )
    tiers = ["Blue", "Silver", "Gold", "Platinum"]
    con.executemany(
        "INSERT INTO dim_customer VALUES (?,?,?,?,?,?)",
        [
            (i, fake.name(), fake.email(), fake.phone_number(),
             tiers[i % len(tiers)], (i % len(cat.MARKETS)) + 1)
            for i in range(1, 501)
        ],
    )

    con.close()
    return db_path


def summarize(db_path: str = DB_PATH) -> None:
    con = duckdb.connect(db_path, read_only=True)
    print(f"warehouse: {db_path}\n")
    for (t,) in con.execute("SHOW TABLES").fetchall():
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t:<24} {n:>7,} rows")
    print()
    check = con.execute(
        """
        SELECT m.market_name,
               ROUND(SUM(f.bookings)::DOUBLE / NULLIF(SUM(f.sessions), 0) * 100, 3) AS conv
        FROM fact_market_daily f
        JOIN dim_market m USING (market_id)
        WHERE f.date >= CURRENT_DATE - INTERVAL 7 DAY
        GROUP BY 1 ORDER BY 2
        """
    ).fetchall()
    print("  last 7d conversion by market (Rome should be lowest):")
    for name, conv in check:
        print(f"    {name:<10} {conv}%")
    con.close()


if __name__ == "__main__":
    summarize(build())
