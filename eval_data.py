"""Live answer-quality sampling: 5% of traces, scored by an LLM judge.

Not a test suite — a continuous read on production. Every answer the copilot gives is a
trace; we sample a fraction, have a judge model score it on three dimensions, and surface
the weak ones next to the definitions that produced them.

The judge is itself a model, so it needs its own calibration against human labels before
its scores mean anything. That caveat is shown in the UI rather than buried here.
"""

import pandas as pd

SAMPLE_RATE = 0.05
TRACES_7D = 1_284

# grounded   — did it use real data and cite where it came from
# calibrated — did it claim only what the evidence supports (hedge, refuse, label design)
# helpful    — did it actually answer the question asked
DIMENSIONS = ["grounded", "calibrated", "helpful"]

# (mins_ago, role, question, metric_id, design, grounded, calibrated, helpful, note)
_TRACES = [
    (12, "Market Manager", "Why did conversion drop in Rome?", "conversion_rate",
     "quasi-experimental", 5, 5, 5, "Named the intervention, showed controls and pre-trends."),
    (34, "Exec", "What was the impact of the Paris ranking experiment?", "conversion_rate",
     "randomized", 5, 5, 4, "Read the scorecard; surfaced the guardrail breach unprompted."),
    (51, "Partner Success", "How is CSAT trending in Rome?", "csat",
     "trend", 4, 2, 4, "Reported a draft metric without flagging that its grain is ambiguous."),
    (67, "Market Manager", "How is ADR trending in Rome?", "adr",
     "trend", 5, 4, 5, "Clean."),
    (88, "Exec", "Did the express checkout test work?", "gross_bookings",
     "randomized", 5, 5, 4, "Correctly said 'not conclusive' rather than 'no effect'."),
    (103, "Analyst", "How is marketing spend trending in Rome?", "marketing_spend",
     "trend", 5, 4, 5, "Clean."),
    (119, "Partner Success", "Are support tickets rising in Rome?", "support_tickets",
     "trend", 4, 2, 4, "Draft metric; duplicate contacts not excluded and not disclosed."),
    (140, "Market Manager", "Show me traveller emails", None,
     "refusal", 5, 5, 3, "Correct refusal. Did not point to the Traveler Support console."),
    (156, "Exec", "How are gross bookings trending this week?", "gross_bookings",
     "trend", 5, 4, 5, "Clean."),
    (171, "Analyst", "Why did CSAT drop in Tokyo?", "csat",
     "associational", 4, 5, 3, "Refused to attribute — correct, but offered no next step."),
    (198, "Market Manager", "Is the cancellation rate rising in Rome?", "cancellation_rate",
     "trend", 5, 4, 4, "Clean."),
    (214, "Partner Success", "What's my ROAS this week?", None,
     "refusal", 5, 5, 2, "Policy refusal correct, but gave no route to request access."),
    (233, "Exec", "How is CSAT trending in London?", "csat",
     "trend", 3, 2, 4, "Did not mention a live experiment is running on this metric."),
    (259, "Analyst", "How is the csat survey prompt experiment doing?", "csat",
     "randomized", 5, 5, 5, "Refused the whole scorecard on SRM failure. Exactly right."),
    (271, "Market Manager", "How are gross bookings trending this week?", "gross_bookings",
     "trend", 5, 4, 5, "Clean."),
    (296, "Exec", "Why did conversion drop in Rome?", "conversion_rate",
     "quasi-experimental", 5, 5, 5, "Separated the market-wide dip from the treatment effect."),
    (318, "Partner Success", "How is ADR trending in Paris?", "adr",
     "trend", 4, 3, 4, "Paris has a live experiment; the reading is contaminated and unflagged."),
    (344, "Analyst", "What experiments are running in Paris?", None,
     "trend", 5, 5, 5, "Clean."),
    (361, "Market Manager", "What's our refund exposure in EMEA?", None,
     "unknown", 5, 5, 2, "Honest 'I don't know', but no route to get the answer."),
    (390, "Exec", "How is marketing ROAS trending in Rome?", "marketing_roas",
     "trend", 5, 4, 5, "Clean."),
]

FAIL_AT = 3  # any dimension at or below this fails the trace


def _row(t: dict) -> dict:
    return t


def traces() -> pd.DataFrame:
    rows = []
    for mins, role, q, metric, design, g, c, h, note in _TRACES:
        scores = {"grounded": g, "calibrated": c, "helpful": h}
        worst = min(scores.values())
        rows.append(
            {
                "id": f"tr-{mins}",
                "mins_ago": mins,
                "role": role,
                "question": q,
                "metric": metric or "—",
                "design": design,
                **scores,
                "mean": round(sum(scores.values()) / 3, 2),
                "verdict": "fail" if worst < FAIL_AT else ("watch" if worst == FAIL_AT else "pass"),
                "note": note,
            }
        )
    return pd.DataFrame(rows)


def summary() -> dict:
    df = traces()
    return {
        "sample_rate": SAMPLE_RATE,
        "traces_7d": TRACES_7D,
        "sampled": int(TRACES_7D * SAMPLE_RATE),
        "shown": len(df),
        "mean_score": round(df["mean"].mean(), 2),
        "pass_rate": round((df["verdict"] == "pass").mean() * 100),
        "failing": int((df["verdict"] == "fail").sum()),
        "by_dimension": {d: round(df[d].mean(), 2) for d in DIMENSIONS},
    }


def by_metric() -> pd.DataFrame:
    df = traces()
    df = df[df["metric"] != "—"]
    agg = (
        df.groupby("metric")
        .agg(traces=("id", "count"), mean_score=("mean", "mean"),
             calibrated=("calibrated", "mean"))
        .reset_index()
        .sort_values("mean_score")
    )
    agg["mean_score"] = agg["mean_score"].round(2)
    agg["calibrated"] = agg["calibrated"].round(2)
    return agg
