"""Evidence sources: the intervention log and the experimentation-platform adapter.

Two tables that make causal claims possible at all:

`INTERVENTIONS` — a change log. Most "why did it move?" questions are answered by
*somebody changed something and we already know what*. Without this the agent has to
rediscover known changes by correlating series, which is both slower and less honest.

`EXPERIMENTS` — a read-only mirror of the experimentation platform's registry and
scorecards. We never recompute their statistics; we join them to our metrics by
`metric_id` and surface them. That join key is the whole integration thesis: the
experiment platform and the copilot must share one certified definition of a metric.
"""

from datetime import date, timedelta

import mock_data as md

SPEND_CHANGE = "spend_change"
PRICE_CHANGE = "price_change"
INCIDENT = "incident"
EXPERIMENT = "experiment"


def _d(days_ago: int) -> date:
    return date.today() - timedelta(days=days_ago)


# type · entity · when · what. `blocks_control` marks changes that disqualify a market
# from being used as an untreated control.
INTERVENTIONS = [
    {
        "id": "int-204",
        "type": SPEND_CHANGE,
        "market": "Rome",
        "start": _d(md.CUT_DAYS_AGO),
        "end": None,
        "description": "Paid-search budget reduced ~55% (efficiency review)",
        "owner": "S. Devarajan · Marketing Analytics",
        "source": "Marketing ops change log",
        "blocks_control": True,
    },
    {
        "id": "int-207",
        "type": INCIDENT,
        "market": "Rome",
        "start": _d(8),
        "end": _d(4),
        "description": "Checkout latency incident, p95 +40% for 4 days",
        "owner": "Platform SRE",
        "source": "Incident register",
        "blocks_control": True,
    },
    {
        "id": "int-118",
        "type": EXPERIMENT,
        "market": "Paris",
        "start": _d(21),
        "end": None,
        "description": "Search ranking v3 experiment, 50% of traffic",
        "owner": "Marketplace Experimentation",
        "source": "Experimentation platform",
        "blocks_control": True,
    },
    {
        "id": "int-209",
        "type": PRICE_CHANGE,
        "market": "New York",
        "start": _d(16),
        "end": None,
        "description": "Partner rate-parity policy change on 3 major chains",
        "owner": "Supply Strategy",
        "source": "Supply change log",
        "blocks_control": True,
    },
]


# --- Experimentation platform mirror -------------------------------------------------
# Shape follows a standard scorecard: estimate, interval, p-value, SRM health, decision.

EXPERIMENTS = [
    {
        "experiment_id": "exp-118",
        "name": "paris_search_ranking_v3",
        "aliases": ["paris", "ranking", "search ranking"],
        "market": "Paris",
        "metric_id": "conversion_rate",
        "hypothesis": "Re-ranked results surface better-converting properties in Paris.",
        "unit": "user",
        "status": "running",
        "start": _d(21),
        "end": None,
        "owner": "Marketplace Experimentation",
        "estimate": 4.6,
        "ci": [1.2, 8.1],
        "p_value": 0.008,
        "srm_pass": True,
        "exposed_users": 1_240_000,
        "decision": "ship candidate",
        # A real scorecard is never one number: primary, secondary, and the guardrails
        # that decide whether a win is worth taking.
        "metrics": [
            {"metric_id": "conversion_rate", "kind": "primary",
             "control": 3.12, "treatment": 3.26,
             "estimate": 4.6, "ci": [1.2, 8.1], "p_value": 0.008},
            {"metric_id": "gross_bookings", "kind": "secondary",
             "control": 486_000, "treatment": 501_100,
             "estimate": 3.1, "ci": [-0.4, 6.6], "p_value": 0.085},
            {"metric_id": "cancellation_rate", "kind": "guardrail",
             "control": 9.4, "treatment": 9.98,
             "estimate": 6.2, "ci": [1.1, 11.5], "p_value": 0.018},
            {"metric_id": "adr", "kind": "guardrail",
             "control": 212.4, "treatment": 211.5,
             "estimate": -0.4, "ci": [-2.1, 1.3], "p_value": 0.64},
        ],
    },
    {
        "experiment_id": "exp-119",
        "name": "express_checkout_v2",
        "aliases": ["checkout", "express checkout", "one-tap", "express"],
        "market": "All",
        "metric_id": "gross_bookings",
        "hypothesis": "One-tap checkout lifts completed bookings.",
        "unit": "user",
        "status": "completed",
        "start": _d(45),
        "end": _d(6),
        "owner": "Checkout",
        "estimate": 2.1,
        "ci": [-0.3, 4.5],
        "p_value": 0.091,
        "srm_pass": True,
        "exposed_users": 3_910_000,
        "decision": "iterate — not conclusive",
        "metrics": [
            {"metric_id": "gross_bookings", "kind": "primary",
             "control": 2_140_000, "treatment": 2_185_000,
             "estimate": 2.1, "ci": [-0.3, 4.5], "p_value": 0.091},
            {"metric_id": "conversion_rate", "kind": "secondary",
             "control": 2.86, "treatment": 2.90,
             "estimate": 1.4, "ci": [-0.6, 3.4], "p_value": 0.17},
            {"metric_id": "cancellation_rate", "kind": "guardrail",
             "control": 8.51, "treatment": 8.54,
             "estimate": 0.3, "ci": [-1.9, 2.5], "p_value": 0.79},
        ],
    },
    {
        "experiment_id": "exp-121",
        "name": "csat_survey_prompt",
        "aliases": ["survey", "survey prompt", "csat prompt"],
        "market": "London",
        "metric_id": "csat",
        "hypothesis": "A lighter survey prompt raises response quality.",
        "unit": "session",
        "status": "running",
        "start": _d(9),
        "end": None,
        "owner": "Traveler Support",
        "estimate": 1.8,
        "ci": [-0.9, 4.5],
        "p_value": 0.19,
        "srm_pass": False,
        "exposed_users": 402_000,
        "decision": "invalid — sample ratio mismatch",
        "metrics": [
            {"metric_id": "csat", "kind": "primary",
             "control": 4.28, "treatment": 4.36,
             "estimate": 1.8, "ci": [-0.9, 4.5], "p_value": 0.19},
            {"metric_id": "support_tickets", "kind": "guardrail",
             "control": 244, "treatment": 249,
             "estimate": 2.0, "ci": [-3.1, 7.1], "p_value": 0.44},
        ],
    },
]


def row_verdict(row: dict) -> str:
    """win · regression · flat — judged against the metric's own direction."""
    if row["p_value"] >= 0.05:
        return "flat"
    good = md.METRICS[row["metric_id"]]["higher_is_better"]
    improved = (row["estimate"] > 0) == good
    return "win" if improved else "regression"


def guardrail_breaches(exp: dict) -> list:
    return [
        r for r in exp.get("metrics", [])
        if r["kind"] == "guardrail" and row_verdict(r) == "regression"
    ]


def find_by_name(text: str):
    """Match an experiment from free text by id, name, or alias."""
    t = text.lower()
    for e in EXPERIMENTS:
        if e["experiment_id"] in t or e["name"].replace("_", " ") in t or e["name"] in t:
            return e
    for e in EXPERIMENTS:
        if any(a in t for a in e["aliases"]):
            return e
    return None


def running_in(market: str) -> list:
    return [
        e for e in EXPERIMENTS
        if e["market"] in (market, "All") and e["status"] == "running"
    ]


def covering(metric_id: str, market: str):
    """A *running* experiment whose traffic contaminates this metric+market reading."""
    for e in EXPERIMENTS:
        if e["status"] != "running" or e["market"] not in (market, "All"):
            continue
        if any(r["metric_id"] == metric_id for r in e.get("metrics", [])):
            return e
    return None


def _overlaps(iv: dict, start: date, end: date) -> bool:
    iv_end = iv["end"] or date.today()
    return iv["start"] <= end and iv_end >= start


def interventions_for(market: str, start: date, end: date) -> list:
    return [i for i in INTERVENTIONS if i["market"] == market and _overlaps(i, start, end)]


def primary_intervention(market: str, start: date, end: date):
    """The change most likely to be the cause: earliest non-incident in the window."""
    candidates = [
        i for i in interventions_for(market, start, end) if i["type"] != INCIDENT
    ]
    return sorted(candidates, key=lambda i: i["start"])[0] if candidates else None


def clean_controls(treated: str, start: date, end: date) -> tuple:
    """Markets with nothing of their own going on — valid untreated comparisons."""
    controls, excluded = [], []
    for m in md.MARKETS:
        if m == treated:
            continue
        blockers = [i for i in interventions_for(m, start, end) if i["blocks_control"]]
        (excluded if blockers else controls).append(
            (m, blockers[0]["description"]) if blockers else m
        )
    return controls, excluded


def experiment_for(metric_id: str, market: str):
    """A registered experiment covering this metric and market, if one exists."""
    for e in EXPERIMENTS:
        if e["metric_id"] == metric_id and e["market"] in (market, "All"):
            return e
    return None


def experiments_for_market(market: str) -> list:
    return [e for e in EXPERIMENTS if e["market"] in (market, "All")]
