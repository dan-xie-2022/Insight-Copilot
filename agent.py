"""The agent loop.

Division of labour, and it is the whole safety argument:

    the model chooses   — which metric, which market, which question is being asked
    the code computes   — every number, interval, p-value, and assumption test
    the model narrates  — prose *over* results it was handed, never numbers it invented

So the model never emits a statistic. Tools return computed JSON; the final turn asks for
an explanation of that JSON. If the model is unavailable the same tools still run and a
deterministic narrator produces the answer, so the product degrades rather than breaks.

CLI:  python agent.py "Why did conversion drop in Rome?" --role "Market Manager"
"""

import json
import sys

import causal
import catalog as cat
import evidence_data as ed
import governance as gov
import llm_client
import mock_data as md

MAX_STEPS = 4


# --- Tools ---------------------------------------------------------------------------
# Each returns JSON-safe computed results. None of them accept SQL: the model picks a
# governed metric, and the catalog supplies the query.

def _summary(metric_id: str, market: str, role: str, days: int = 90) -> dict:
    df = gov.metric_series(metric_id, market, role, days)
    vals = df[metric_id].tolist()
    if len(vals) < 15:
        return {"error": "not enough history"}
    last7 = sum(vals[-7:]) / 7
    prior7 = sum(vals[-14:-7]) / 7
    base30 = sum(vals[-30:-23]) / 7 if len(vals) >= 30 else prior7
    spec = cat.METRICS[metric_id]
    return {
        "metric_id": metric_id,
        "label": spec["label"],
        "market": market,
        "unit": spec["unit"],
        "higher_is_better": spec["higher_is_better"],
        "current": round(last7, 4),
        "wow_pct": round((last7 - prior7) / prior7 * 100, 2) if prior7 else 0.0,
        "vs_30d_pct": round((last7 - base30) / base30 * 100, 2) if base30 else 0.0,
        "definition": spec["definition"],
        "lineage": spec["lineage"],
    }


def tool_list_metrics(role: str, **_) -> dict:
    return {
        "metrics": [
            {"metric_id": m, "label": cat.METRICS[m]["label"],
             "unit": cat.METRICS[m]["unit"], "definition": cat.METRICS[m]["definition"]}
            for m in cat.ROLES[role]["allowed"]
        ],
        "markets": cat.MARKETS,
    }


def tool_metric_summary(role: str, metric_id: str = None, market: str = "Rome",
                        days: int = 90, **_) -> dict:
    if not gov.can_access(role, metric_id):
        return {"refused": f"{role} is not entitled to {metric_id}"}
    return _summary(metric_id, market, role, days)


def tool_compare_markets(role: str, metric_id: str = None, **_) -> dict:
    if not gov.can_access(role, metric_id):
        return {"refused": f"{role} is not entitled to {metric_id}"}
    out = {}
    for m in cat.MARKETS:
        s = _summary(metric_id, m, role)
        out[m] = {"current": s.get("current"), "wow_pct": s.get("wow_pct")}
    return {"metric_id": metric_id, "by_market": out}


def tool_explain_change(role: str, metric_id: str = None, market: str = "Rome", **_) -> dict:
    if metric_id and not gov.can_access(role, metric_id):
        return {"refused": f"{role} is not entitled to {metric_id}"}
    return causal.explain(metric_id, market, role)


def tool_experiment_readout(role: str, query: str = "", **_) -> dict:
    exp = ed.find_by_name(query)
    if not exp:
        return {"error": "no experiment matched", "known": [e["name"] for e in ed.EXPERIMENTS]}
    a = md._experiment_readout(exp, role)
    return {"narrative": a["narrative"], "scorecard": a.get("scorecard"),
            "kind": a["kind"], "metric_id": a["metric_id"]}


TOOLS = {
    "list_metrics": tool_list_metrics,
    "metric_summary": tool_metric_summary,
    "compare_markets": tool_compare_markets,
    "explain_change": tool_explain_change,
    "experiment_readout": tool_experiment_readout,
}

_METRIC_ENUM = list(cat.METRICS.keys())

TOOL_SCHEMA = [
    {"type": "function", "function": {
        "name": "list_metrics",
        "description": "List the governed metrics this user may see, and the markets.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "metric_summary",
        "description": "Current value, week-over-week and 30-day change for one metric "
                       "in one market. Use for 'how is X doing' questions.",
        "parameters": {"type": "object", "properties": {
            "metric_id": {"type": "string", "enum": _METRIC_ENUM},
            "market": {"type": "string", "enum": cat.MARKETS}},
            "required": ["metric_id", "market"]}}},
    {"type": "function", "function": {
        "name": "compare_markets",
        "description": "One metric across every market. Use for portfolio questions.",
        "parameters": {"type": "object", "properties": {
            "metric_id": {"type": "string", "enum": _METRIC_ENUM}},
            "required": ["metric_id"]}}},
    {"type": "function", "function": {
        "name": "explain_change",
        "description": "Why a metric moved. Runs the causal engine: finds a randomized "
                       "experiment, else difference-in-differences against untreated "
                       "control markets, else refuses to attribute. Use for 'why' questions.",
        "parameters": {"type": "object", "properties": {
            "metric_id": {"type": "string", "enum": _METRIC_ENUM},
            "market": {"type": "string", "enum": cat.MARKETS}},
            "required": ["metric_id", "market"]}}},
    {"type": "function", "function": {
        "name": "experiment_readout",
        "description": "Full A/B scorecard for a named experiment: primary, secondary "
                       "and guardrail metrics, SRM health, decision.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string",
                      "description": "The user's phrasing, e.g. 'paris ranking experiment'"}},
            "required": ["query"]}}},
]


def system_prompt(role: str) -> str:
    policy = cat.ROLES[role]
    lines = [
        f"- `{m}` — {cat.METRICS[m]['label']} ({cat.METRICS[m]['unit'] or 'count'}): "
        f"{cat.METRICS[m]['definition']}"
        for m in policy["allowed"]
    ]
    return f"""You are Insight Copilot, an internal analytics assistant at Expedia Group.

The user's role is **{role}**. {policy['note']}

Metrics they may see:
{chr(10).join(lines)}

Markets: {', '.join(cat.MARKETS)}.

RULES — these are absolute:
1. NEVER state a number that did not come from a tool result. You have no knowledge of
   this company's data. If you have not called a tool, you do not know the answer.
2. NEVER compute or estimate an effect, lift, interval or p-value yourself. The
   explain_change and experiment_readout tools do that. Quote their numbers exactly.
3. NEVER claim causation from a correlation. If explain_change returns design
   "associational", say plainly that the cause is not established.
4. If a tool returns "refused", tell the user they aren't entitled to that data and stop.
   Do not work around it with a different metric.
5. Personal data — names, emails, phone numbers — is never available. Refuse and point to
   the Traveler Support console.
6. If you cannot answer with the metrics above, say so and list what you can answer.

Style: lead with the answer in one bold sentence, then the reasoning in two or three
short paragraphs. Address the user as a busy decision-maker, not a statistician."""


def _deterministic(question: str, role: str) -> dict:
    """Fallback path: the same tools, narrated in code instead of by the model."""
    a = md.answer(question, role)
    a["engine"] = "deterministic"
    return a


def answer(question: str, role: str, use_llm: bool = True) -> dict:
    """Answer a question. Falls back to the deterministic path on any LLM failure."""
    if not use_llm or not llm_client.available():
        return _deterministic(question, role)

    messages = [
        {"role": "system", "content": system_prompt(role)},
        {"role": "user", "content": question},
    ]
    artifacts, used_tools = {}, []

    try:
        for _ in range(MAX_STEPS):
            reply = llm_client.chat(messages, tools=TOOL_SCHEMA)
            if not reply["tool_calls"]:
                break

            messages.append({
                "role": "assistant",
                "content": reply["text"] or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in reply["tool_calls"]
                ],
            })

            for tc in reply["tool_calls"]:
                fn = TOOLS.get(tc["name"])
                try:
                    args = json.loads(tc["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = fn(role=role, **args) if fn else {"error": "unknown tool"}
                except gov.Refused as r:
                    result = {"refused": r.reason, "category": r.category}
                except Exception as e:  # noqa: BLE001
                    result = {"error": f"{type(e).__name__}: {e}"}

                used_tools.append({"name": tc["name"], "args": args})
                artifacts.setdefault(tc["name"], []).append(result)
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(result, default=str)[:6000]})
        else:
            reply = llm_client.chat(messages)

        narrative = (reply.get("text") or "").strip()
        if not narrative:
            return _deterministic(question, role)
    except llm_client.LLMUnavailable:
        return _deterministic(question, role)

    return _assemble(question, role, narrative, artifacts, used_tools)


def _assemble(question, role, narrative, artifacts, used_tools) -> dict:
    """Attach the computed artifacts to the model's prose."""
    verdict = next(
        (r for r in artifacts.get("explain_change", []) if isinstance(r, dict)
         and "design" in r), None
    )
    readout = next(
        (r for r in artifacts.get("experiment_readout", []) if isinstance(r, dict)
         and r.get("scorecard")), None
    )
    summaries = [r for r in artifacts.get("metric_summary", []) if r.get("metric_id")]

    metric_id = market = None
    if verdict:
        metric_id, market = verdict["metric_id"], verdict["market"]
    elif readout:
        metric_id = readout.get("metric_id")
        market = readout["scorecard"]["market"]
        if market == "All":
            market = "Rome"
    elif summaries:
        metric_id, market = summaries[0]["metric_id"], summaries[0]["market"]

    refused = any(
        isinstance(r, dict) and r.get("refused")
        for rs in artifacts.values() for r in rs
    )
    confidence = 0.95 if (verdict or readout) else (0.9 if summaries else 0.4)
    if verdict:
        confidence = {"randomized": 0.95, "quasi-experimental": 0.84,
                      "associational": 0.45}[verdict["design"]]

    lineage = sorted({t for s in summaries for t in s.get("lineage", [])}) or [
        "fact_market_daily", "dim_market"
    ]
    if readout:
        lineage = ["experimentation platform", "dim_experiment", "fact_experiment_result"]

    return {
        "kind": "refusal" if refused and not (verdict or readout or summaries) else "insight",
        "narrative": narrative,
        "verdict": verdict,
        "scorecard": readout["scorecard"] if readout else None,
        "plan": [f"{t['name']}({', '.join(f'{k}={v}' for k, v in t['args'].items())})"
                 for t in used_tools] or ["answered without a tool call"],
        "sql": cat.series_sql(metric_id, market, 90) if metric_id and market else None,
        "metric_id": metric_id,
        "market": market,
        "lineage": lineage,
        "confidence": confidence,
        "engine": f"llm · {llm_client.model_name()}",
    }


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Why did conversion drop in Rome?"
    role = "Market Manager"
    if "--role" in sys.argv:
        role = sys.argv[sys.argv.index("--role") + 1]
    a = answer(q, role)
    print(f"\n[{a['engine']}] {role} · confidence {a['confidence']:.0%}\n")
    print(a["narrative"])
    print("\nplan:", " → ".join(a["plan"]))
    if a.get("verdict"):
        v = a["verdict"]
        print(f"verdict: {v['design']} · {v['method']}")
