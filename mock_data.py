"""Mock semantic layer + data for the Insight Copilot UI shell.

This stands in for what will become `catalog.py` (metric definitions, lineage, role
policy) and `data/warehouse.duckdb` (the real numbers). The shapes here are the shapes
the real modules must return, so `app.py` won't need to change when they land.
"""

import hashlib
import math
from datetime import date, datetime, timedelta

import pandas as pd

# Markets, metric definitions and role policy all live in `catalog.py` — one governed
# definition per concept, imported rather than restated. Duplicating them here is exactly
# the reconciliation problem this product exists to remove.
from catalog import MARKETS, MARKETS_META, METRICS, REGIONS, ROLES, region_of  # noqa: E402,F401

# The planted story: Rome's paid-search spend was cut this many days ago. Kept recent
# enough that the effect lands inside the last-7-vs-prior-7 window the tiles display —
# a story that has already finished decaying is invisible to a WoW metric.
CUT_DAYS_AGO = 10
CONSIDERATION_LAG_DAYS = 3


def _seed(key: str) -> int:
    """Stable per-key seed (Python's hash() is salted per process, so don't use it)."""
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)


def _base_level(metric_id: str, market: str) -> float:
    levels = {
        "conversion_rate": 2.8,
        "gross_bookings": 420_000,
        "adr": 185,
        "cancellation_rate": 8.5,
        "marketing_roas": 4.2,
        "marketing_spend": 95_000,
        "csat": 4.3,
        "support_tickets": 240,
    }
    meta = MARKETS_META[market]
    # Volume scales with market size; rates do not. Scaling a *rate* by market size makes
    # small markets look broken, which is wrong and hides the real story.
    if metric_id in ("gross_bookings", "marketing_spend", "support_tickets"):
        factor = meta["scale"]
    elif metric_id == "adr":
        factor = meta["adr_index"]
    elif metric_id == "conversion_rate":
        factor = meta["quality"]
    elif metric_id == "cancellation_rate":
        factor = 1 / meta["quality"]          # better markets cancel less
    elif metric_id == "csat":
        factor = 1 + (meta["quality"] - 1) * 0.5   # damped: CSAT lives in a narrow band
    else:
        factor = 1.0
    return levels[metric_id] * factor


def series(metric_id: str, market: str, days: int = 90) -> pd.DataFrame:
    """Deterministic daily series for a metric+market, ending today.

    Carries the planted story: Rome's paid-search spend was cut ~5 weeks ago, and Rome
    conversion falls a few days later. The agent's job in the demo is to find that link.
    """
    # ROAS is *derived*, not generated: bookings ÷ spend. Generating it independently
    # let it drift into arithmetic nonsense (spend −36%, bookings −10%, ROAS flat).
    if metric_id == "marketing_roas":
        bookings = series("gross_bookings", market, days)
        spend = series("marketing_spend", market, days)
        scale = _base_level("marketing_roas", market) / (
            _base_level("gross_bookings", market) / _base_level("marketing_spend", market)
        )
        return pd.DataFrame(
            {"date": bookings["date"],
             "value": (bookings["value"] / spend["value"] * scale).round(3)}
        )

    base = _base_level(metric_id, market)
    end = date.today()
    rows = []
    cut_day = end - timedelta(days=CUT_DAYS_AGO)

    # Phases for the shared demand factor — per metric, identical across markets.
    ph = _seed(metric_id)
    p1 = (ph % 1000) / 1000 * 2 * math.pi
    p2 = ((ph // 1000) % 1000) / 1000 * 2 * math.pi

    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        n = d.toordinal()

        # Everything keys on the *date*, never the loop index, so a 90-day request and a
        # 68-day request agree about the same day. Without this the dashboard and the
        # causal engine would silently disagree about the same series.
        seasonal = 1 + 0.06 * math.sin(n / 14.0)
        weekly = 1 + (0.05 if d.weekday() >= 5 else -0.01)

        # Markets share demand shocks. This is what makes parallel trends hold in
        # reality, and therefore what licenses difference-in-differences here.
        common = (
            1
            + 0.015 * math.sin(2 * math.pi * n / 23 + p1)
            + 0.010 * math.sin(2 * math.pi * n / 37 + p2)
        )
        # Idiosyncratic noise, deliberately small next to the shared component.
        noise = (
            (_seed(f"{metric_id}|{market}|{d.isoformat()}") % 10_000) / 10_000 - 0.5
        ) * 0.024

        value = base * (seasonal * weekly * common + noise)

        if market == "Rome" and d >= cut_day:
            if metric_id == "marketing_spend":
                value *= 0.45  # the cut itself
            elif metric_id == "conversion_rate":
                # Traffic falls immediately; bookings follow after the consideration lag,
                # so conversion decays into a new lower plateau rather than stepping down.
                lag = max(0, (d - cut_day).days - CONSIDERATION_LAG_DAYS)
                value *= 1 - 0.14 * min(1.0, lag / 3.0)
            elif metric_id == "gross_bookings":
                lag = max(0, (d - cut_day).days - CONSIDERATION_LAG_DAYS)
                value *= 1 - 0.11 * min(1.0, lag / 3.0)

        rows.append({"date": pd.Timestamp(d), "value": round(value, 3)})

    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> dict:
    """Current value + week-over-week delta, as the tiles display them."""
    if len(df) < 15:
        return {"current": float(df["value"].iloc[-1]), "delta_pct": 0.0}
    last7 = df["value"].iloc[-7:].mean()
    prior7 = df["value"].iloc[-14:-7].mean()
    delta = (last7 - prior7) / prior7 * 100 if prior7 else 0.0
    return {"current": float(last7), "delta_pct": float(delta)}


def format_value(value: float, unit: str) -> str:
    if unit == "$":
        if value >= 1_000_000:
            return f"${value/1_000_000:.2f}M"
        if value >= 1_000:
            return f"${value/1_000:.0f}K"
        return f"${value:,.0f}"
    if unit == "%":
        return f"{value:.2f}%"
    if unit == "x":
        return f"{value:.2f}x"
    if unit == "/5":
        return f"{value:.2f}/5"
    return f"{value:,.0f}"


def warehouse_as_of() -> datetime:
    """Simulated warehouse freshness: hourly batch, so data lags the clock.

    Deliberately NOT 'real-time' — the tiles show this stamp so the product is honest
    about staleness instead of implying it is live.
    """
    now = datetime.now()
    return (now - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


# --- Canned agent responses ---------------------------------------------------------
# Placeholder for `agent.py`. Same return shape the real agent loop will produce:
# plan steps -> SQL -> data -> chart -> narrative -> lineage -> confidence.

def driver_analysis(market: str = "Rome") -> dict:
    """Compute the story from the series rather than asserting it.

    Placeholder for what the agent will really do (changepoint detection + correlated-
    metric scan). Numbers are derived, so the narrative can never drift from the chart
    sitting next to it — which is exactly the failure mode a live demo cannot afford.
    """
    deltas = {
        m: summarize(series(m, market))["delta_pct"]
        for m in ("conversion_rate", "gross_bookings", "marketing_spend", "marketing_roas")
    }
    return {
        "market": market,
        "deltas": deltas,
        "cut_date": date.today() - timedelta(days=CUT_DAYS_AGO),
        "cut_days_ago": CUT_DAYS_AGO,
        "lag_days": CONSIDERATION_LAG_DAYS,
    }


# Order matters: "cancellation rate" must match before the bare word "rate" reaches ADR.
METRIC_KEYWORDS = [
    ("cancellation_rate", ("cancellation", "cancel")),
    ("marketing_roas", ("roas", "return on ad", "ad spend efficiency")),
    ("marketing_spend", ("spend", "marketing budget", "paid search")),
    ("support_tickets", ("ticket", "support volume", "contacts")),
    ("csat", ("csat", "satisfaction")),
    ("conversion_rate", ("conversion", "convert")),
    ("gross_bookings", ("booking", "revenue", "gmv")),
    ("adr", ("adr", "daily rate", "nightly rate", "average rate")),
]


def detect_metric(q: str):
    for metric_id, words in METRIC_KEYWORDS:
        if any(w in q for w in words):
            return metric_id
    return None


def detect_market(q: str):
    for m in MARKETS:
        if m.lower() in q:
            return m
    return None


def _trend_answer(metric_id: str, market: str, role: str) -> dict:
    """Generic 'how is X doing' response, with every number derived from the series."""
    spec = METRICS[metric_id]
    df = series(metric_id, market)
    s = summarize(df)
    wow = s["delta_pct"]

    last7 = df["value"].iloc[-7:].mean()
    base30 = df["value"].iloc[-30:-23].mean()
    mom = (last7 - base30) / base30 * 100 if base30 else 0.0

    good = (wow >= 0) == spec["higher_is_better"]
    direction = "up" if wow >= 0 else "down"
    consistent = (wow >= 0) == (mom >= 0)

    narrative = (
        f"**{spec['label']} in {market} is {format_value(s['current'], spec['unit'])}, "
        f"{direction} {abs(wow):.1f}% week-over-week.** Against the last 30 days it's "
        f"{'up' if mom >= 0 else 'down'} {abs(mom):.1f}%, so the weekly move "
        + (
            "is consistent with the trend rather than a break from it."
            if consistent
            else "runs against the longer trend — worth a look if it holds."
        )
        + "\n\n"
        + (
            f"This is moving the right way for {spec['label'].lower()}."
            if good
            else f"This is moving the wrong way for {spec['label'].lower()}. "
            "Ask me why and I'll look for a driver."
        )
    )

    return {
        "kind": "insight",
        "narrative": narrative,
        "plan": [
            f"Resolve metric to `{metric_id}` and market to {market}",
            "Compute last 7 days vs prior 7, and vs the 30-day base",
            "Judge direction against the metric's higher_is_better definition",
        ],
        "sql": spec["sql"].replace(":market", f"'{market}'"),
        "metric_id": metric_id,
        "market": market,
        "lineage": spec["lineage"],
        "confidence": 0.93,
    }


def _experiment_readout(exp: dict, role: str) -> dict:
    """Read an experiment scorecard: primary, secondary, guardrails, and a decision.

    Written for a decision-maker, not a statistician — the headline is what to do, and
    the caveats are stated rather than left for the reader to infer.
    """
    import evidence_data as ed

    allowed = ROLES[role]["allowed"]
    if exp["metric_id"] not in allowed:
        return {
            "kind": "refusal",
            "narrative": f"**{role}** isn't entitled to "
                         f"{METRICS[exp['metric_id']]['label'].lower()}, which is this "
                         f"experiment's primary metric, so I can't show you its readout.",
            "plan": ["Match experiment", "Check role policy on its primary metric", "Refuse"],
            "sql": None, "metric_id": None, "market": None,
            "lineage": ["experimentation platform (blocked: role policy)"], "confidence": 1.0,
        }

    day = (date.today() - exp["start"]).days
    visible = [r for r in exp["metrics"] if r["metric_id"] in allowed]
    hidden = len(exp["metrics"]) - len(visible)

    if not exp["srm_pass"]:
        narrative = (
            f"**{exp['name']} can't be read — it failed its sample-ratio check.**\n\n"
            f"The traffic split doesn't match the design, which means the two groups aren't "
            f"comparable and *no* metric on this scorecard can be interpreted — including the "
            f"ones that look like wins. This is a data-collection fault, not a null result.\n\n"
            f"Recorded decision: **{exp['decision']}**. The fix is to find the assignment bug "
            f"and rerun; nothing about the feature has been learned yet."
        )
    else:
        primary = next(r for r in exp["metrics"] if r["kind"] == "primary")
        pv = ed.row_verdict(primary)
        breaches = ed.guardrail_breaches(exp)
        lo, hi = primary["ci"]

        if pv == "win" and not breaches:
            head = (
                f"**{exp['name']} is winning.** {METRICS[primary['metric_id']]['label']} is "
                f"{primary['estimate']:+.1f}% [{lo:+.1f}, {hi:+.1f}], p={primary['p_value']:.3f}, "
                "and no guardrail has moved against it."
            )
        elif pv == "win" and breaches:
            # Only name guardrails the role may see. A breach on a metric outside their
            # access is still disclosed — withholding "this may be harmful" would be the
            # worse failure — but without the label or the number.
            visible_ids = {r["metric_id"] for r in visible}
            named_breaches = [b for b in breaches if b["metric_id"] in visible_ids]
            hidden_breaches = len(breaches) - len(named_breaches)

            if named_breaches:
                names = ", ".join(METRICS[b["metric_id"]]["label"] for b in named_breaches)
                breach_clause = (
                    f"while **{names}** moved the wrong way by a statistically significant "
                    "margin"
                )
            else:
                breach_clause = (
                    "while a guardrail metric outside your access moved the wrong way by a "
                    "statistically significant margin"
                )
            head = (
                f"**{exp['name']} is winning on its primary metric but breaking a guardrail.** "
                f"{METRICS[primary['metric_id']]['label']} is {primary['estimate']:+.1f}% "
                f"[{lo:+.1f}, {hi:+.1f}] (p={primary['p_value']:.3f}), {breach_clause}."
                "\n\nThat makes this a trade, not a free win — someone has to decide whether "
                "the gain is worth the cost, and that decision is not mine to make."
                + (
                    f"\n\n_{hidden_breaches} breached guardrail(s) are outside your access. "
                    "Confirm with the experiment owner before acting on this._"
                    if hidden_breaches and named_breaches
                    else "\n\n_Confirm with the experiment owner before acting on this._"
                    if hidden_breaches
                    else ""
                )
            )
        elif pv == "flat":
            head = (
                f"**{exp['name']} is not conclusive.** "
                f"{METRICS[primary['metric_id']]['label']} is {primary['estimate']:+.1f}% "
                f"[{lo:+.1f}, {hi:+.1f}], and the interval crosses zero (p="
                f"{primary['p_value']:.3f}).\n\nThat is *not* the same as 'no effect' — the "
                "test may simply lack the power to detect one this size."
            )
        else:
            head = (
                f"**{exp['name']} is losing on its primary metric** "
                f"({primary['estimate']:+.1f}% [{lo:+.1f}, {hi:+.1f}], p="
                f"{primary['p_value']:.3f})."
            )

        status_line = (
            f"Day {day} of the test, {exp['exposed_users']:,} {exp['unit']}s exposed, "
            f"randomized by {exp['unit']}. Recorded decision: **{exp['decision']}**."
        )
        peeking = (
            "\n\n_Still running — treat this as a checkpoint, not a final result. Acting on "
            "an interim readout inflates the chance of a false positive._"
            if exp["status"] == "running"
            else ""
        )
        narrative = f"{head}\n\n{status_line}{peeking}"

    if hidden:
        narrative += (
            f"\n\n_{hidden} metric(s) on this scorecard are outside your access and are "
            "not shown._"
        )

    return {
        "kind": "insight",
        "narrative": narrative,
        # Built field-by-field rather than {**exp}: the registry holds `date` objects and
        # this dict gets persisted to the JSON transcript store.
        "scorecard": {
            "experiment_id": exp["experiment_id"],
            "name": exp["name"],
            "hypothesis": exp["hypothesis"],
            "market": exp["market"],
            "unit": exp["unit"],
            "status": exp["status"],
            "owner": exp["owner"],
            "srm_pass": exp["srm_pass"],
            "exposed_users": exp["exposed_users"],
            "decision": exp["decision"],
            "start": exp["start"].isoformat(),
            "end": exp["end"].isoformat() if exp["end"] else None,
            "day": day,
            "visible_metrics": visible,
        },
        "plan": [
            f"Match question to experiment `{exp['experiment_id']}`",
            "Fetch scorecard from the experimentation platform (read-only)",
            "Check sample-ratio health before reading any metric",
            "Filter scorecard rows to the role's entitlements",
            "Judge each row against its metric's own direction",
        ],
        "sql": None,
        "metric_id": exp["metric_id"],
        "market": exp["market"] if exp["market"] != "All" else "Rome",
        "lineage": ["experimentation platform", "dim_experiment", "fact_experiment_result"],
        "confidence": 0.4 if not exp["srm_pass"] else 0.95,
    }


def answer(question: str, role: str) -> dict:
    q = question.lower().strip()

    if any(w in q for w in ["email", "phone", "traveler name", "customer name", "pii"]):
        return {
            "kind": "refusal",
            "narrative": (
                "I can't return traveler contact details. Those columns are classified PII "
                "and are masked for every role in this product, including Analyst. If you "
                "need them for a support case, use the Traveler Support console, which logs "
                "access against the ticket."
            ),
            "plan": ["Parse request", "Check column classification in catalog", "Refuse — PII"],
            "sql": None,
            "metric_id": None,
            "market": None,
            "lineage": ["dim_customer (blocked: pii)"],
            "confidence": 1.0,
        }

    metric_id = detect_metric(q)
    market_named = detect_market(q)

    # A governed refusal when the role simply isn't entitled to what was asked for.
    if metric_id and metric_id not in ROLES[role]["allowed"]:
        spec = METRICS[metric_id]
        return {
            "kind": "refusal",
            "narrative": (
                f"**{role}** doesn't have access to {spec['label'].lower()}. That metric is "
                f"built from `{'`, `'.join(spec['lineage'][:2])}`, which sits outside your "
                "role's data policy, so I won't estimate it from what I can see either.\n\n"
                "If you need it, request access through the data platform team — the request "
                "will name this exact metric."
            ),
            "plan": [
                f"Resolve metric to `{metric_id}`",
                "Check role policy for table entitlements",
                "Refuse — outside role's data policy",
            ],
            "sql": None,
            "metric_id": None,
            "market": None,
            "lineage": [f"{spec['lineage'][0]} (blocked: role policy)"],
            "confidence": 1.0,
        }

    # --- Experiment reading, before causal inference ---------------------------------
    # An experiment readout is stronger evidence than anything we would estimate, so if
    # the question is about a test, answer from the scorecard rather than inferring.
    import evidence_data as ed

    asks_list = any(
        w in q for w in ("what experiments", "which experiments", "experiments running",
                         "any experiments", "tests running", "what tests", "experiments in")
    )
    if asks_list:
        market_for_list = market_named or "Rome"
        running = [
            e for e in ed.running_in(market_for_list)
            if e["metric_id"] in ROLES[role]["allowed"]
        ]
        if not running:
            return {
                "kind": "unknown",
                "narrative": f"No experiments are running in {market_for_list} on metrics "
                             "you have access to.",
                "plan": ["Query the experiment registry", "Filter to running + your entitlements"],
                "sql": None, "metric_id": None, "market": None,
                "lineage": ["experimentation platform"], "confidence": 0.9,
            }
        lines = []
        for e in running:
            breaches = ed.guardrail_breaches(e)
            flag = " ⚠️ guardrail regression" if breaches else ""
            invalid = " 🚫 invalid (SRM)" if not e["srm_pass"] else ""
            lines.append(
                f"- **{e['name']}** · primary metric {METRICS[e['metric_id']]['label']} "
                f"· day {(date.today() - e['start']).days} · {e['owner']}{flag}{invalid}"
            )
        return {
            "kind": "insight",
            "narrative": f"**{len(running)} experiment(s) running in {market_for_list}:**\n\n"
                         + "\n".join(lines)
                         + "\n\nAsk about any of them by name for the full scorecard.",
            "plan": ["Query the experiment registry", "Filter to running + your entitlements"],
            "sql": None, "metric_id": None, "market": market_for_list,
            "lineage": ["experimentation platform"], "confidence": 0.95,
        }

    named = ed.find_by_name(q)
    mentions_test = any(w in q for w in ("experiment", "a/b", "ab test", " test"))
    if named and (mentions_test or "result" in q or "impact" in q or "work" in q):
        return _experiment_readout(named, role)

    wants_why = any(
        w in q
        for w in ("why", "drop", "decline", "fell", "falling", "impact", "effect",
                  "experiment", "caused", "cause of")
    )

    if wants_why:
        # Lazy import: causal imports this module for the series and metric specs.
        import causal

        v = causal.explain(metric_id, market_named or "Rome", role)
        confidence = {
            causal.RANDOMIZED: 0.95,
            causal.QUASI: 0.84,
            causal.ASSOCIATIONAL: 0.45,
        }[v["design"]]
        if v["refusal"]:
            confidence = min(confidence, 0.35)

        spec = METRICS[v["metric_id"]]
        from_platform = v["design"] == causal.RANDOMIZED
        return {
            "kind": "insight",
            "narrative": causal.narrate(v),
            "verdict": v,
            "plan": [
                f"Resolve metric to `{v['metric_id']}` and market to {v['market']}",
                "Search the intervention log and experiment registry for the window",
                f"Select the strongest licensed design → **{v['design']}**",
                "Test the design's assumptions before estimating",
                "Estimate in code; narrate the returned verdict without recomputing it",
            ],
            "sql": None if from_platform else spec["sql"].replace(":market", f"'{v['market']}'"),
            "metric_id": v["metric_id"],
            "market": v["market"],
            "lineage": spec["lineage"]
            + (["experimentation platform"] if from_platform else ["dim_intervention"]),
            "confidence": confidence,
        }

    # Bookings without a named market reads as a portfolio question, not a single series.
    if metric_id == "gross_bookings" and not market_named:
        by_market = {
            m: summarize(series("gross_bookings", m))["delta_pct"] for m in MARKETS
        }
        portfolio = sum(by_market.values()) / len(by_market)
        leaders = sorted(by_market, key=by_market.get, reverse=True)[:2]
        laggard = min(by_market, key=by_market.get)
        return {
            "kind": "insight",
            "narrative": (
                f"**Gross bookings across all {len(MARKETS)} managed markets are "
                f"{portfolio:+.1f}% "
                f"week-over-week**, led by {leaders[0]} ({by_market[leaders[0]]:+.1f}%) and "
                f"{leaders[1]} ({by_market[leaders[1]]:+.1f}%). **{laggard}** is the weakest at "
                f"{by_market[laggard]:+.1f}%, dragging the portfolio number down.\n\n"
                f"{laggard} is worth a separate look — ask me why it dropped."
            ),
            "plan": [
                "Identify metric: gross_bookings",
                "Aggregate by market, last 7d vs prior 7d",
                "Rank contributors to the portfolio delta",
            ],
            "sql": METRICS["gross_bookings"]["sql"].replace(":market", "ANY(:markets)"),
            "metric_id": "gross_bookings",
            "market": "Rome",
            "lineage": METRICS["gross_bookings"]["lineage"],
            "confidence": 0.91,
        }

    if metric_id:
        return _trend_answer(metric_id, market_named or "Rome", role)

    return {
        "kind": "unknown",
        "narrative": (
            "I don't have a governed answer for that yet. I can currently answer questions about "
            "conversion, gross bookings, ADR, cancellations, marketing spend and ROAS, CSAT, and "
            f"support tickets — across {len(MARKETS)} markets in "
            f"{', '.join(REGIONS)}.\n\n"
            "Rather than guess, here's what I'd need: the metric you mean, and the time window."
        ),
        "plan": ["Parse request", "Match against semantic layer", "No confident match — ask back"],
        "sql": None,
        "metric_id": None,
        "market": None,
        "lineage": [],
        "confidence": 0.2,
    }


# Suggested prompts are role-specific: each one is a question that profile plausibly owns,
# and every one resolves against metrics that role is entitled to. Nothing here is a
# deliberate dead end — the refusal and out-of-scope paths still exist, but a suggested
# prompt that fails on purpose wastes the one chance to show what the product does.
SAMPLE_QUESTIONS_BY_ROLE = {
    "Market Manager": [
        "Why did conversion drop in Rome?",
        "How are gross bookings trending this week?",
        "How is ADR trending in Rome?",
        "Is the cancellation rate rising in Rome?",
    ],
    "Partner Success": [
        "How is CSAT trending in Rome?",
        "Are support tickets rising in Rome?",
        "Is the cancellation rate rising in Rome?",
        "How is ADR trending in Paris?",
    ],
    "Exec": [
        "Why did conversion drop in Rome?",
        "What was the impact of the Paris ranking experiment?",
        "Did the express checkout test work?",
        "How are gross bookings trending this week?",
    ],
    "Analyst": [
        "Why did conversion drop in Rome?",
        "What experiments are running in Paris?",
        "How is the csat survey prompt experiment doing?",
        "How is marketing spend trending in Rome?",
    ],
}


def sample_questions(role: str) -> list:
    return SAMPLE_QUESTIONS_BY_ROLE.get(role, SAMPLE_QUESTIONS_BY_ROLE["Market Manager"])
