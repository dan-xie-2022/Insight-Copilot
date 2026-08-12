"""Causal engine — the evidence ladder behind every "why did this move?" answer.

Design rule: **the language model never computes an effect.** It routes (which metric,
which market, which intervention) and it narrates the returned verdict. Every number —
estimate, interval, p-value, assumption test — is produced here, in code. If the model
could emit a statistic directly, none of the trust machinery around it would mean anything.

The ladder, strongest evidence first:

  A  randomized     a registered experiment covers this metric and market
  B  quasi-exp      a known intervention + ≥2 untreated control markets, pre-trends hold
  C  associational  changepoint and correlated candidates only — labelled as such
  D  refusal        nothing supports even an association

Everything returns the same `Verdict` shape so one UI component renders all four.
"""

import math
from datetime import date, timedelta

import numpy as np

import evidence_data as ed
import mock_data as md

PRE_DAYS = 28          # pre-period used for both the estimate and the trends test
TRANSITION_DAYS = 3    # excluded from both periods: the consideration lag
MIN_CONTROLS = 2

RANDOMIZED = "randomized"
QUASI = "quasi-experimental"
ASSOCIATIONAL = "associational"
NONE = "insufficient evidence"


# --- Small OLS, so there is no scipy/statsmodels dependency --------------------------

def _ols(X: np.ndarray, y: np.ndarray):
    """Return (coefficients, standard errors) for y = Xb + e."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(1, X.shape[0] - X.shape[1])
    sigma2 = float(resid @ resid) / dof
    xtx_inv = np.linalg.pinv(X.T @ X)
    se = np.sqrt(np.maximum(np.diag(xtx_inv) * sigma2, 0.0))
    return beta, se


def _p_two_sided(t: float) -> float:
    """Normal approximation — n is ~300+ here, so the t/z difference is immaterial."""
    return 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t) / math.sqrt(2.0))))


def _panel(metric_id: str, markets: list, first: date, last: date):
    """Long panel of log values, one row per market-day."""
    rows = []
    span = (date.today() - first).days + 1
    for m in markets:
        df = md.series(metric_id, m, days=max(span, PRE_DAYS + 40))
        for d, v in zip(df["date"], df["value"]):
            day = d.date()
            if first <= day <= last and v > 0:
                rows.append((m, day, math.log(v)))
    return rows


# --- Tier B: difference-in-differences ----------------------------------------------

def _did(metric_id: str, treated: str, controls: list, cut: date):
    """Two-way fixed-effects DiD on log values → a multiplicative effect."""
    first = cut - timedelta(days=PRE_DAYS)
    last = date.today()
    rows = [
        r for r in _panel(metric_id, [treated] + controls, first, last)
        # Drop the transition window: neither clean pre nor settled post.
        if not (cut <= r[1] < cut + timedelta(days=TRANSITION_DAYS))
    ]
    if len(rows) < 40:
        return None

    units = [treated] + controls
    X, y = [], []
    for market, day, logv in rows:
        post = 1.0 if day >= cut else 0.0
        treat = 1.0 if market == treated else 0.0
        # intercept · unit dummies (base = treated) · post · treat×post
        dummies = [1.0 if market == u else 0.0 for u in units[1:]]
        X.append([1.0] + dummies + [post, treat * post])
        y.append(logv)

    X, y = np.array(X), np.array(y)
    beta, se = _ols(X, y)
    b, s = float(beta[-1]), float(se[-1])

    return {
        "effect_pct": (math.exp(b) - 1) * 100,
        "ci_pct": [(math.exp(b - 1.96 * s) - 1) * 100, (math.exp(b + 1.96 * s) - 1) * 100],
        "p_value": _p_two_sided(b / s) if s > 0 else 1.0,
        "n_obs": len(rows),
    }


def _pre_trends(metric_id: str, treated: str, controls: list, cut: date):
    """Placebo test: did treated and controls already diverge *before* the change?

    Regress log value on a time trend interacted with treatment, using only the
    pre-period. A significant interaction means the parallel-trends assumption fails and
    DiD is not licensed.
    """
    first = cut - timedelta(days=PRE_DAYS)
    rows = _panel(metric_id, [treated] + controls, first, cut - timedelta(days=1))
    if len(rows) < 30:
        return {"passed": False, "p_value": None, "detail": "pre-period too short"}

    units = [treated] + controls
    X, y = [], []
    for market, day, logv in rows:
        t = (day - first).days
        treat = 1.0 if market == treated else 0.0
        dummies = [1.0 if market == u else 0.0 for u in units[1:]]
        X.append([1.0] + dummies + [t, treat * t])
        y.append(logv)

    beta, se = _ols(np.array(X), np.array(y))
    b, s = float(beta[-1]), float(se[-1])
    p = _p_two_sided(b / s) if s > 0 else 1.0
    return {
        "passed": p >= 0.05,
        "p_value": p,
        "detail": f"treated-vs-control trend divergence over {PRE_DAYS}d pre-period, p={p:.2f}",
    }


# --- The ladder ---------------------------------------------------------------------

def explain(metric_id: str, market: str, role: str) -> dict:
    metric_id = metric_id or "conversion_rate"
    spec = md.METRICS[metric_id]
    window_start = date.today() - timedelta(days=PRE_DAYS)
    window_end = date.today()

    # --- Tier A: a randomized experiment already answers this -----------------------
    exp = ed.experiment_for(metric_id, market)
    if exp:
        invalid = not exp["srm_pass"]
        sig = exp["p_value"] < 0.05
        return {
            "design": RANDOMIZED,
            "method": f"randomized experiment · {exp['name']}",
            "source": "Experimentation platform (read-only)",
            "metric_id": metric_id,
            "market": market,
            "effect_pct": None if invalid else exp["estimate"],
            "ci_pct": None if invalid else exp["ci"],
            "p_value": exp["p_value"],
            "intervention": f"{exp['name']} ({exp['status']}, unit = {exp['unit']})",
            "controls": ["randomized holdout"],
            "assumptions": [
                {
                    "name": "sample ratio mismatch check",
                    "passed": exp["srm_pass"],
                    "detail": "allocation matches design"
                    if exp["srm_pass"]
                    else "observed allocation differs from design — results are void",
                },
                {
                    "name": "statistical significance (α=0.05)",
                    "passed": sig,
                    "detail": f"p={exp['p_value']:.3f}",
                },
            ],
            "caveats": []
            if not invalid
            else ["SRM failure means this readout cannot be interpreted at all."],
            "refusal": (
                "This experiment failed its sample-ratio check, so I won't report an effect "
                "from it. That is a data-collection fault, not a null result."
                if invalid
                else None
            ),
            "decision": exp["decision"],
            "exposed_users": exp["exposed_users"],
        }

    # --- Tier B: quasi-experiment against untreated markets -------------------------
    intervention = ed.primary_intervention(market, window_start, window_end)
    controls, excluded = ed.clean_controls(market, window_start, window_end)

    if intervention:
        co_interventions = [
            i
            for i in ed.interventions_for(market, window_start, window_end)
            if i["id"] != intervention["id"]
        ]
        caveats = [
            f"{c['description']} overlapped the same window in {market} "
            f"({c['start']:%b %d}–{(c['end'] or date.today()):%b %d}). The estimate cannot "
            "separate the two."
            for c in co_interventions
        ]

        if len(controls) < MIN_CONTROLS:
            return _associational(
                metric_id, market, spec,
                refusal="I can't attribute this. Every other market had its own change in "
                        "the same window, so there is no clean comparison to make.",
                caveats=caveats, excluded=excluded,
            )

        trends = _pre_trends(metric_id, market, controls, intervention["start"])
        if not trends["passed"]:
            return _associational(
                metric_id, market, spec,
                refusal="I can't attribute this to the change. "
                        f"{market} and the control markets were already diverging before it "
                        f"({trends['detail']}), so a difference-in-differences estimate would "
                        "be misleading.",
                caveats=caveats, excluded=excluded, trends=trends,
            )

        est = _did(metric_id, market, controls, intervention["start"])
        if est is None:
            return _associational(metric_id, market, spec, caveats=caveats, excluded=excluded)

        return {
            "design": QUASI,
            "method": "difference-in-differences (two-way fixed effects, log scale)",
            "source": "Computed here · intervention log + warehouse",
            "metric_id": metric_id,
            "market": market,
            "effect_pct": est["effect_pct"],
            "ci_pct": est["ci_pct"],
            "p_value": est["p_value"],
            "intervention": f"{intervention['description']} "
                            f"({intervention['start']:%b %d}, {intervention['owner']})",
            "controls": controls,
            "assumptions": [
                {"name": "parallel pre-trends", "passed": True, "detail": trends["detail"]},
                {
                    "name": "untreated controls",
                    "passed": True,
                    "detail": f"{len(controls)} clean market(s); excluded "
                    + (", ".join(f"{m} ({why})" for m, why in excluded) or "none"),
                },
                {
                    "name": "transition window excluded",
                    "passed": True,
                    "detail": f"{TRANSITION_DAYS} days after the change dropped from both periods",
                },
            ],
            "caveats": caveats
            + [
                "Standard errors are classical, not clustered by market. With only "
                f"{len(controls) + 1} units, clustered errors would be unreliable anyway — "
                "treat the interval as indicative."
            ],
            "refusal": None,
            "n_obs": est["n_obs"],
        }

    # --- Tier C / D -----------------------------------------------------------------
    return _associational(
        metric_id, market, spec,
        refusal="No change is recorded for this market in the window, so I can't say what "
                "caused the move — only what moved alongside it.",
        excluded=excluded,
    )


def _associational(metric_id, market, spec, refusal=None, caveats=None, excluded=None,
                   trends=None):
    """Tier C: what we had before — a movement and its correlates, honestly labelled."""
    df = md.series(metric_id, market)
    s = md.summarize(df)
    correlates = []
    for other in md.METRICS:
        if other == metric_id:
            continue
        o = md.summarize(md.series(other, market))
        if abs(o["delta_pct"]) >= 5:
            correlates.append((other, o["delta_pct"]))
    correlates.sort(key=lambda c: -abs(c[1]))

    assumptions = [
        {
            "name": "causal identification",
            "passed": False,
            "detail": "no randomization and no usable quasi-experimental design",
        }
    ]
    if trends:
        assumptions.insert(0, {"name": "parallel pre-trends", "passed": False,
                               "detail": trends["detail"]})

    return {
        "design": ASSOCIATIONAL,
        "method": "week-over-week change with correlated candidates",
        "source": "Computed here · warehouse",
        "metric_id": metric_id,
        "market": market,
        "effect_pct": s["delta_pct"],
        "ci_pct": None,
        "p_value": None,
        "intervention": None,
        "controls": [],
        "correlates": [(md.METRICS[m]["label"], d) for m, d in correlates[:3]],
        "assumptions": assumptions,
        "caveats": (caveats or [])
        + ["These are associations. Anything here could be coincidence or a shared cause."],
        "refusal": refusal,
        "excluded_controls": excluded or [],
    }


# --- Narration ----------------------------------------------------------------------

def narrate(v: dict) -> str:
    """Prose for the verdict. Reads numbers off the verdict; never recomputes them."""
    spec = md.METRICS[v["metric_id"]]
    label = spec["label"]  # not lowercased: acronyms like CSAT / ADR / ROAS

    if v["refusal"]:
        head = f"**I can't give you a causal answer for {label} in {v['market']}.**\n\n{v['refusal']}"
        if v["design"] == ASSOCIATIONAL and v.get("correlates"):
            moves = ", ".join(f"{n} {d:+.1f}%" for n, d in v["correlates"])
            head += (
                f"\n\nWhat I *can* tell you: {label} moved {v['effect_pct']:+.1f}% "
                f"week-over-week, and these moved alongside it — {moves}. "
                "Association only; I have not established that any of them is the cause."
            )
        return head

    if v["design"] == RANDOMIZED:
        lo, hi = v["ci_pct"]
        sig = v["p_value"] < 0.05
        return (
            f"**{spec['label']} in {v['market']}: {v['effect_pct']:+.1f}% "
            f"[{lo:+.1f}, {hi:+.1f}] from a randomized experiment.**\n\n"
            f"This comes from `{v['intervention']}` on the experimentation platform, "
            f"with {v['exposed_users']:,} users exposed — not from my own estimate. "
            + (
                f"The effect is statistically significant (p={v['p_value']:.3f}), and the "
                f"recorded decision is **{v['decision']}**."
                if sig
                else f"The interval crosses zero (p={v['p_value']:.3f}), so this is *not "
                f"conclusive*; the recorded decision is **{v['decision']}**. "
                "A non-significant result is not evidence of no effect."
            )
            + "\n\nThis is the strongest evidence available for this question, because "
            "assignment was randomized."
        )

    lo, hi = v["ci_pct"]
    controls = ", ".join(v["controls"])
    return (
        f"**The change caused {label} in {v['market']} to move {v['effect_pct']:+.1f}% "
        f"[{lo:+.1f}, {hi:+.1f}].**\n\n"
        f"Attributed to: {v['intervention']}. Estimated by difference-in-differences "
        f"against {controls}, which had no changes of their own in the window — so normal "
        f"seasonality and market-wide movements are differenced out rather than being "
        f"mistaken for an effect.\n\n"
        f"Parallel pre-trends hold, so the comparison is licensed. This is quasi-experimental "
        "evidence: stronger than correlation, weaker than a randomized test."
    )
