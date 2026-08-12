"""The semantic layer — one governed definition of every metric, for every surface.

This is the asset the whole product is built on. The dashboard, the copilot, the causal
engine, and the experiment scorecards all read metric definitions from here, so they
cannot disagree about what "conversion rate" means. Two surfaces disagreeing about a
number is the reconciliation work this product exists to delete; duplicating the
definitions in code would recreate it.

It also carries the **role policy** — and closes it under derivation, which is subtler
than it looks. See `close_policies()`.
"""

# --- Markets -------------------------------------------------------------------------
# The single place a location is defined. `scale` sets the market's size relative to the
# baseline and feeds both the synthetic generator and the warehouse build, so adding a
# market here is the only edit required anywhere.

# Three independent axes, because conflating them is a modelling error that only shows
# up once you have enough markets: `scale` is volume (bookings, spend, tickets),
# `adr_index` is price level, `quality` is how well the market converts. A small market
# is not a badly-converting one.
MARKETS_META = {
    # EMEA
    "Rome":       {"region": "EMEA",  "country": "Italy",       "scale": 0.90, "adr_index": 1.00, "quality": 1.00},
    "Paris":      {"region": "EMEA",  "country": "France",      "scale": 1.15, "adr_index": 1.15, "quality": 1.05},
    "London":     {"region": "EMEA",  "country": "UK",          "scale": 1.30, "adr_index": 1.30, "quality": 1.08},
    "Barcelona":  {"region": "EMEA",  "country": "Spain",       "scale": 0.95, "adr_index": 0.95, "quality": 1.02},
    "Amsterdam":  {"region": "EMEA",  "country": "Netherlands", "scale": 0.85, "adr_index": 1.10, "quality": 1.03},
    "Dubai":      {"region": "EMEA",  "country": "UAE",         "scale": 1.20, "adr_index": 1.35, "quality": 0.98},
    # AMER
    "New York":   {"region": "AMER",  "country": "USA",         "scale": 1.45, "adr_index": 1.45, "quality": 1.10},
    "Las Vegas":  {"region": "AMER",  "country": "USA",         "scale": 1.25, "adr_index": 1.05, "quality": 1.06},
    "Orlando":    {"region": "AMER",  "country": "USA",         "scale": 1.10, "adr_index": 1.00, "quality": 1.04},
    "Toronto":    {"region": "AMER",  "country": "Canada",      "scale": 0.80, "adr_index": 0.95, "quality": 1.00},
    "Cancún":     {"region": "LATAM", "country": "Mexico",      "scale": 0.75, "adr_index": 1.05, "quality": 0.96},
    "São Paulo":  {"region": "LATAM", "country": "Brazil",      "scale": 0.70, "adr_index": 0.70, "quality": 0.94},
    # APAC
    "Tokyo":      {"region": "APAC",  "country": "Japan",       "scale": 1.00, "adr_index": 1.20, "quality": 1.00},
    "Singapore":  {"region": "APAC",  "country": "Singapore",   "scale": 0.95, "adr_index": 1.15, "quality": 1.02},
    "Sydney":     {"region": "APAC",  "country": "Australia",   "scale": 0.88, "adr_index": 1.10, "quality": 1.01},
    "Bali":       {"region": "APAC",  "country": "Indonesia",   "scale": 0.65, "adr_index": 0.60, "quality": 0.95},
}

MARKETS = list(MARKETS_META)
REGIONS = sorted({m["region"] for m in MARKETS_META.values()})


def region_of(market: str) -> str:
    return MARKETS_META[market]["region"]


def markets_in(region: str) -> list:
    return [m for m, v in MARKETS_META.items() if v["region"] == region]

FACT = "fact_market_daily"

# --- Tables and classification -------------------------------------------------------
# `pii` columns are never returned to anyone, in any role, by any surface.

TABLES = {
    "fact_market_daily": {"grain": "market · day", "pii": []},
    "dim_market": {"grain": "market", "pii": []},
    "dim_date": {"grain": "day", "pii": []},
    "dim_intervention": {"grain": "intervention", "pii": []},
    "dim_experiment": {"grain": "experiment", "pii": []},
    "fact_experiment_result": {"grain": "experiment · metric", "pii": []},
    "dim_customer": {"grain": "customer", "pii": ["full_name", "email", "phone"]},
}

PII_COLUMNS = {f"{t}.{c}" for t, m in TABLES.items() for c in m["pii"]}

# --- Metrics -------------------------------------------------------------------------
# `expr` is the aggregate over fact_market_daily; everything else is derived from it,
# so a metric is defined exactly once.

METRICS = {
    "conversion_rate": {
        "label": "Conversion Rate",
        "unit": "%",
        "chart": "line",
        "higher_is_better": True,
        "expr": "SUM(f.bookings)::DOUBLE / NULLIF(SUM(f.sessions), 0) * 100",
        "definition": "Bookings ÷ sessions, by market and day. Denominator is sessions, "
                      "not users.",
        "lineage": ["fact_market_daily", "dim_market", "dim_date"],
    },
    "gross_bookings": {
        "label": "Gross Bookings",
        "unit": "$",
        "chart": "line",
        "higher_is_better": True,
        "expr": "SUM(f.booking_value_usd)",
        "definition": "Booking value in USD at time of booking. Gross of cancellations.",
        "lineage": ["fact_market_daily", "dim_market", "dim_date"],
    },
    "adr": {
        "label": "ADR (Avg Daily Rate)",
        "unit": "$",
        "chart": "line",
        "higher_is_better": True,
        "expr": "AVG(f.nightly_rate_usd)",
        "definition": "Average nightly rate in USD. Excludes taxes and fees.",
        "lineage": ["fact_market_daily", "dim_market", "dim_date"],
    },
    "cancellation_rate": {
        "label": "Cancellation Rate",
        "unit": "%",
        "chart": "line",
        "higher_is_better": False,
        "expr": "SUM(f.cancelled)::DOUBLE / NULLIF(SUM(f.bookings), 0) * 100",
        "definition": "Cancelled ÷ total bookings, by booking date (not cancellation date).",
        "lineage": ["fact_market_daily", "dim_market", "dim_date"],
    },
    "marketing_roas": {
        "label": "Marketing ROAS",
        "unit": "x",
        "chart": "line",
        "higher_is_better": True,
        "expr": "SUM(f.booking_value_usd) / NULLIF(SUM(f.spend_usd), 0)",
        "definition": "Gross bookings ÷ paid media spend, same market and day. "
                      "Last-touch attribution.",
        "lineage": ["fact_market_daily", "dim_market", "dim_date"],
    },
    "marketing_spend": {
        "label": "Marketing Spend",
        "unit": "$",
        "chart": "bar",
        "higher_is_better": True,
        "expr": "SUM(f.spend_usd)",
        "definition": "Paid media spend in USD by market and day, all channels.",
        "lineage": ["fact_market_daily", "dim_market", "dim_date"],
    },
    "csat": {
        "label": "CSAT",
        "unit": "/5",
        "chart": "line",
        "higher_is_better": True,
        "expr": "SUM(f.csat_sum) / NULLIF(SUM(f.csat_responses), 0)",
        "definition": "Mean CSAT on resolved tickets. DRAFT — grain is ambiguous between "
                      "ticket-created and ticket-resolved date.",
        "lineage": ["fact_market_daily", "dim_market", "dim_date"],
    },
    "support_tickets": {
        "label": "Support Tickets",
        "unit": "",
        "chart": "bar",
        "higher_is_better": False,
        "expr": "SUM(f.support_tickets)",
        "definition": "Tickets created, by market and day. DRAFT — does not exclude "
                      "duplicate contacts on one booking.",
        "lineage": ["fact_market_daily", "dim_market", "dim_date"],
    },
}


def series_sql(metric_id: str, market: str, days: int = 90) -> str:
    """The governed query for a metric series. The agent never writes SQL from scratch —
    it selects a metric, and the definition supplies the query."""
    m = METRICS[metric_id]
    return (
        f"SELECT f.date, {m['expr']} AS {metric_id}\n"
        f"FROM {FACT} f\n"
        f"JOIN dim_market mk ON mk.market_id = f.market_id\n"
        f"WHERE mk.market_name = '{market}'\n"
        f"  AND f.date >= CURRENT_DATE - INTERVAL {int(days)} DAY\n"
        f"GROUP BY 1 ORDER BY 1"
    )


# Display SQL for the transparency panel: the same governed query with the market left
# as a bind parameter, so what the user is shown is what actually runs.
for _mid in METRICS:
    METRICS[_mid]["sql"] = series_sql(_mid, "%MARKET%").replace("'%MARKET%'", ":market")


def panel_sql(metric_id: str, markets: list, days: int = 90) -> str:
    """Same definition, several markets — what difference-in-differences needs."""
    m = METRICS[metric_id]
    quoted = ", ".join(f"'{x}'" for x in markets)
    return (
        f"SELECT mk.market_name, f.date, {m['expr']} AS {metric_id}\n"
        f"FROM {FACT} f\n"
        f"JOIN dim_market mk ON mk.market_id = f.market_id\n"
        f"WHERE mk.market_name IN ({quoted})\n"
        f"  AND f.date >= CURRENT_DATE - INTERVAL {int(days)} DAY\n"
        f"GROUP BY 1, 2 ORDER BY 1, 2"
    )


# --- Role policy ---------------------------------------------------------------------
# `intent` is what a human decided. `allowed` is what the policy actually permits once
# closed under derivation — see below.

ROLES = {
    "Market Manager": {
        "intent": [
            "conversion_rate", "gross_bookings", "adr", "cancellation_rate",
            "marketing_roas", "marketing_spend",
        ],
        "template": ["conversion_rate", "gross_bookings", "adr", "cancellation_rate"],
        "can_see_sql": False,
        "note": "Owns market performance. No access to support PII or ticket detail.",
    },
    "Partner Success": {
        "intent": ["csat", "support_tickets", "cancellation_rate", "adr"],
        "template": ["csat", "support_tickets", "cancellation_rate"],
        "can_see_sql": False,
        "note": "Owns partner health. No access to marketing spend or ROAS.",
    },
    "Exec": {
        "intent": ["gross_bookings", "conversion_rate", "marketing_roas", "csat"],
        "template": ["gross_bookings", "conversion_rate", "marketing_roas"],
        "can_see_sql": False,
        "note": "Portfolio view. Aggregates only — no row-level detail.",
    },
    "Analyst": {
        "intent": list(METRICS.keys()),
        "template": ["conversion_rate", "marketing_spend", "gross_bookings"],
        "can_see_sql": True,
        "note": "Full governed access. Sees generated SQL and can edit it.",
    },
}

# Metrics that are arithmetic identities of each other. Any two imply the third.
DERIVATIONS = [("marketing_roas", "gross_bookings", "marketing_spend")]


def close_policies() -> None:
    """Close each role's access under derivation.

    A policy that grants ROAS and gross bookings but withholds marketing spend does not
    actually withhold it: ROAS = bookings ÷ spend, so spend = bookings ÷ ROAS. The
    original Exec policy had exactly this hole — enforced perfectly at the surface and
    leaking through arithmetic.

    Rather than pretend, we make the implication explicit: if a role can derive a metric,
    it is granted it, and the grant is recorded so the catalog can show *why* it is there.
    The alternative — revoking one of the pair — is a product decision, and this makes
    that decision visible instead of accidental.
    """
    for name, role in ROLES.items():
        allowed = list(role["intent"])
        derived = []
        changed = True
        while changed:
            changed = False
            for triple in DERIVATIONS:
                present = [m for m in triple if m in allowed]
                if len(present) == 2:
                    missing = next(m for m in triple if m not in allowed)
                    allowed.append(missing)
                    derived.append((missing, tuple(present)))
                    changed = True
        role["allowed"] = allowed
        role["derived_grants"] = derived


close_policies()


def policy_findings() -> list:
    """Human-readable description of every access granted by implication, not intent."""
    out = []
    for name, role in ROLES.items():
        for metric, via in role.get("derived_grants", []):
            out.append(
                f"**{name}** is granted `{metric}` by derivation: it can already see "
                f"`{via[0]}` and `{via[1]}`, and the three are an arithmetic identity. "
                "Withholding it would be theatre."
            )
    return out
