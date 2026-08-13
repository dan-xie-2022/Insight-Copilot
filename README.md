# Insight Copilot

An internal AI analytics product for a travel marketplace: ask a question in plain
language, get an answer that shows its evidence — with the governance, causal discipline,
and evaluation you would need before letting non-technical employees act on it.

Built as a portfolio piece for a Product Manager, Analytics Products role.

---

## The idea in one paragraph

Dashboards answer the questions you already knew to ask. Chat answers the long tail. Most
"AI analytics" products stop there — and that combination is now table stakes. This one
adds the parts that decide whether anyone should *trust* it: it monitors your metrics and
tells you what moved before you ask, it refuses to claim a cause it cannot defend, it
enforces data access at render time rather than at save time, and it measures its own
answer quality in production.

## Two surfaces, two audiences

**Decision-makers** (market managers, partner leads, execs) get a conversation with an
**Insight Dashboard** beside it. Ask why something moved, pin the answer, and it becomes a
standing tile — persisted as a *definition*, recomputed on every open, re-checked against
your current entitlements.

**Analysts** get a **Control Plane** instead. They are not another asker: they are the
supply side. They certify metric definitions, triage what the copilot got wrong, read
experiment scorecards, and audit what the product told the business.

## What makes the answers defensible

**An evidence ladder.** Every "why did this move?" climbs down until it finds a design the
data supports:

| Tier | Design | Used when |
|---|---|---|
| A | Randomized experiment | A registered A/B test covers this metric and market |
| B | Difference-in-differences | A known intervention plus ≥2 untreated control markets, pre-trends hold |
| C | Association | A movement and its correlates — labelled as association, not cause |
| D | Refusal | Nothing supports even an association |

**The model never computes a number.** The LLM chooses the metric, the market and the
method, then narrates a verdict computed in Python. Estimates, intervals, p-values and
assumption tests all come from `causal.py`. That division is the entire safety argument.

**Governance is enforced by parsing, not pattern-matching.** Every query is parsed with
`sqlglot` before it runs: read-only, single statement, allow-listed tables, PII refused for
every role including Analyst, row cap imposed, every attempt audited.

**Role policy is closed under derivation.** ROAS = bookings ÷ spend, so a role granted ROAS
and bookings can derive spend by division. The catalog detects that implication and makes
the grant explicit rather than pretending the data is withheld.

## Running it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # paste a DeepSeek key
.venv/bin/python data/generate.py
.venv/bin/python -m streamlit run app.py
```

Without a key the agent falls back to deterministic answers, so the app runs fully offline.

```bash
.venv/bin/python agent.py "Why did conversion drop in Rome?" --role "Market Manager"
```

The warehouse rebuilds itself whenever it is missing or no longer reaches today, so
`data/generate.py` is a convenience rather than a required step. Every series is generated
relative to `date.today()`; a warehouse left over from yesterday would put the planted spend
cut on a date the intervention log no longer claims, and the causal engine would split
pre/post in the wrong place.

## Deploying

Streamlit Community Cloud, from this repo:

1. Point [share.streamlit.io](https://share.streamlit.io) at this repo, branch `main`,
   entry point `app.py`.
2. Add the key under **Advanced settings → Secrets**, in TOML:
   ```toml
   DEEPSEEK_API_KEY = "sk-..."
   ```
   `llm_client` reads the environment first and falls back to `st.secrets`, so the same code
   runs locally off `.env` and hosted off secrets. Without the key the deployed app still
   works — it serves the deterministic answers.
3. Nothing else to provision. The warehouse builds itself on first query, in about two
   seconds, so no database ships with the repo.

Persistence is a local file (`data/`), which on Community Cloud lives on ephemeral disk:
pinned tiles and conversations survive a session but not a container restart. That is fine
for a demo and wrong for anything real — the store interfaces in `dashboard_store.py` and
`chat_store.py` are the seam where a hosted database would go.

## How it fits together

[ARCHITECTURE.md](ARCHITECTURE.md) — two diagrams: the layered stack that decides what the
product is *allowed* to say, and the evaluation loop that decides whether it should have
said it.

## Layout

| File | Role |
|---|---|
| `ARCHITECTURE.md` | The stack and the evaluation loop, as diagrams |
| `app.py` | Conversation + Insight Dashboard |
| `control_plane.py` | Analyst surface: queue, evaluation harness, catalog, experiments, audit |
| `catalog.py` | Semantic layer — metrics, markets, role policy. One definition, every surface |
| `governance.py` | The only path to the warehouse |
| `causal.py` | Evidence ladder, difference-in-differences, assumption tests |
| `agent.py` / `llm_client.py` | Tool-calling loop over DeepSeek, with deterministic fallback |
| `evidence_data.py` | Intervention log + experimentation-platform mirror |
| `eval_data.py` | Live answer-quality sampling scored by an LLM judge |
| `data/generate.py` | Builds the DuckDB warehouse (16 markets, 4 regions) |
| `docs/` | Product requirements per segment |

## Honest limitations

- Data is synthetic. The story it carries — a paid-search cut in Rome, with untreated
  control markets — is planted so the causal engine has something real to find.
- Standard errors are classical, not clustered by market.
- The judge scoring answer quality is itself a model, and needs calibrating against
  human labels before its scores should drive decisions.
- Experiment scorecards are a mocked read of a platform that would be owned elsewhere.
  Integrating rather than rebuilding is the deliberate call.
