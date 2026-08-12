# Segment 1 — Business Decision-Makers

**Product:** Insight Copilot · **Segment:** Business decision-makers (beachhead)
**Status:** UI requirements locked, prototype built · **Last updated:** 2026-08-09

---

## 1. Who this segment is

Employees who **own a business outcome but do not write SQL**. In Expedia terms: market
managers, partner-success leads, marketing/advertising leads, and the directors and GMs
above them.

| | |
|---|---|
| **Data fluency** | Low to medium. Reads dashboards; does not query. |
| **Owns** | A market, a partner portfolio, a spend budget — a number they are accountable for. |
| **Core job-to-be-done** | "Tell me what's happening in my area and what to do about it." |
| **Pain today** | Standing dashboards answer last quarter's questions. Anything new means filing a request with an analyst and waiting days — by which point the decision window has moved. |
| **Frequency** | Daily glance, weekly deep-dive, ad-hoc when something breaks. |

**Why this segment first.** Conversational AI creates the most value for people who cannot
self-serve at all — the gap between "wait three days" and "ask and get an answer" is far
larger than the gap analysts experience. Their low fluency also *forces* the governance and
transparency work rather than making it optional, which is the capability the rest of the
portfolio will be built on.

**Explicit non-user:** analysts and data scientists. They are a **stakeholder** here, not a
user. The product's value to them is queue deflection — fewer repetitive ad-hoc requests —
and they are the trust check on answer quality. They become primary users in Segment 2.

---

## 2. Scope

**In scope for Segment 1**

- A persistent, curated dashboard of the metrics this person owns
- A conversational surface for the questions a dashboard cannot anticipate
- Promotion of a one-off answer into a standing metric
- Proactive surfacing of significant movements without being asked
- Visible governance: role-based access, source citation, freshness, refusal

**Out of scope for Segment 1**

- SQL authoring or editing (Segment 2)
- Notebook or export workflows (Segment 2)
- Semantic-layer authoring — metric definitions are governed centrally, not user-editable
- Cross-team sharing, subscriptions, scheduled digests (later phase)
- Write-back or action-taking in source systems

---

## 3. Product principles for this segment

1. **Conversation is the product; the dashboard is a surface of it.** The dashboard is where
   answers accumulate, not a separate destination.
2. **Monitoring is not a mode.** The product leads with the largest unexplained movement
   rather than waiting to be queried.
3. **Store the question, not the answer.** Dashboard tiles persist a definition and recompute
   on every open.
4. **Refusing is a feature.** For a user who cannot check the SQL, a wrong answer is worse
   than no answer.
5. **Every answer shows its work.** Sources, freshness, and confidence travel with the number.

---

## 4. Functional requirements

### 4.1 Insight Dashboard

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| **S1-FR-01** | The dashboard is the default view, open beside the conversation | On load the panel is open with the user's tiles rendered | ✅ Built |
| **S1-FR-02** | The user can close the dashboard to give the conversation full width, and reopen it | Toggle in the top bar; conversation reflows to a centred reading measure when closed | ✅ Built |
| **S1-FR-03** | The dashboard persists per user across sessions | Tiles, order, and sizes return unchanged after quitting and relaunching | ✅ Built |
| **S1-FR-04** | Tile values are recomputed on every open, never cached | Values reflect current data; freshness stamp updates on reload | ✅ Built |
| **S1-FR-05** | A first-time user receives a role-based default dashboard | New Market Manager lands on market metrics, not an empty page | ✅ Built |
| **S1-FR-06** | The user can add any metric they are entitled to | "＋ Add metric" in the panel header; picker lists only permitted metrics | ✅ Built |
| **S1-FR-07** | The user can remove, reorder, and resize tiles | Per-tile menu: full/half width, move up, move down, remove; all persist | ✅ Built |
| **S1-FR-08** | Tiles support two widths so the dashboard reads as a layout, not a list | Half-width tiles pair two per row and render as sparklines; full-width tiles show axes | ✅ Built |
| **S1-FR-09** | Each tile states its recency and provenance | "as of \<timestamp\>" plus source tables and an origin badge (template / pinned / added) | ✅ Built |
| **S1-FR-10** | Direction of movement is legible at a glance | Tile colour derives from the metric's `higher_is_better` definition, not the sign of the change | ✅ Built |

### 4.2 Conversation

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| **S1-FR-11** | The user asks in plain language and receives a narrative answer with a chart | Answer includes written insight plus visualisation | ✅ Built |
| **S1-FR-12** | Suggested prompts are role-appropriate and all answerable | Four prompts per role; every one resolves to a real answer within that role's entitlements | ✅ Built |
| **S1-FR-13** | Conversations persist and can be revisited | History rail lists saved threads, newest first, auto-titled; threads reopen with full transcript | ✅ Built |
| **S1-FR-14** | The user can start a new thread and delete old ones | "＋ New chat" and per-thread delete | ✅ Built |
| **S1-FR-15** | A transcript is a record, not a live view | Reopening a thread shows the numbers as answered at the time | ✅ Built |
| **S1-FR-16** | Every answer exposes its reasoning on demand | "How I got this" reveals the plan steps and the query | ✅ Built |
| **S1-FR-17** | Every answer carries confidence and sources | Confidence band plus the tables the answer drew on | ✅ Built |
| **S1-FR-18** | The user can rate an answer | Thumbs up/down per answer | ⚠️ UI only — not yet stored |

### 4.3 The pin loop

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| **S1-FR-19** | Any chat answer can be promoted to a dashboard tile | "📌 Pin to dashboard" on eligible answers | ✅ Built |
| **S1-FR-20** | Pinning is visibly consequential | Pinning opens the dashboard and the tile appears immediately, marked as pinned | ✅ Built |
| **S1-FR-21** | Pinning is idempotent | Pinning a metric already present is rejected with a message, not duplicated | ✅ Built |
| **S1-FR-22** | Pinning is unavailable where the user lacks entitlement | Pin disabled when the answer's metric is outside the role's policy | ✅ Built |

### 4.4 Proactive insight

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| **S1-FR-23** | The product surfaces the largest significant movement unprompted | Alert leads the dashboard when open, and the conversation when closed | ✅ Built |
| **S1-FR-24** | An alert names a probable driver, not just the movement | Includes the correlated change and its timing | ✅ Built |
| **S1-FR-25** | An alert is a hand-off into conversation | The user can ask why directly from the alert | ✅ Built |
| **S1-FR-26** | Alerts are suppressed below a materiality threshold | Statistical significance **and** business materiality both required to fire | ❌ Not built — see §8 |
| **S1-FR-27** | The user can mute a metric's alerts | Per-metric mute, persisted | ❌ Not built — see §8 |

---

## 5. Governance and responsible-AI requirements

This is the differentiating capability for this segment, because the user cannot verify an
answer themselves.

| ID | Requirement | Acceptance criteria | Status |
|---|---|---|---|
| **S1-GOV-01** | Access is enforced by role, on both surfaces | The same question and the same dashboard return different data by role | ✅ Built |
| **S1-GOV-02** | Entitlement is evaluated at render time, not at save time | A tile pinned under a broader role shows an access-revoked state under a narrower one, and fetches no values | ✅ Built |
| **S1-GOV-03** | PII is never returned, to any role | Requests for traveller contact details are refused, not masked-but-attempted | ✅ Built |
| **S1-GOV-04** | A metric outside the user's policy is refused, not estimated | Explicit refusal naming the metric and the route to request access | ✅ Built |
| **S1-GOV-05** | The product refuses rather than guessing | Unrecognised questions return an honest "I don't know" plus what it *can* answer | ✅ Built |
| **S1-GOV-06** | Causal language is hedged | Driver explanations state correlation and disclose that confounds were not tested | ✅ Built |
| **S1-GOV-07** | Query visibility follows role | SQL shown to analysts; described but hidden for non-technical roles | ✅ Built |
| **S1-GOV-08** | Freshness is disclosed, never implied | Every tile carries an "as of" stamp reflecting warehouse lag; the product never claims real-time | ✅ Built |
| **S1-GOV-09** | Generated SQL is validated before execution | Allow-listed tables, read-only, no DDL/DML, single statement, enforced row limit | ❌ Deferred to backend build |
| **S1-GOV-10** | Every question and query is audit-logged | Who asked what, what ran, under which role | ❌ Deferred to backend build |

---

## 6. Data requirements

- **Semantic layer** — every metric carries a label, unit, canonical definition, source
  lineage, and a `higher_is_better` flag. The flag is a product requirement, not a display
  detail: it is what lets the interface judge a movement rather than merely report it.
- **Domains for this segment** — bookings and sessions, marketing spend, support and
  satisfaction, with market, property, and customer dimensions.
- **Grain** — daily by market, sufficient for week-over-week and 30-day comparison.
- **Freshness** — hourly batch. The product must expose this, not conceal it.
- **Role policy** — a declarative map of role to permitted metrics and tables, resolvable at
  render time.

---

## 7. Success metrics

**North star:** weekly decision-makers who reach an answer without filing an analyst request.

| Layer | Metric | Why it matters |
|---|---|---|
| Adoption | Weekly active users in segment; % of eligible market managers active | Is it reaching the people who couldn't self-serve? |
| Engagement | Questions per user per week; dashboard opens per week | Is it in the workflow or a novelty? |
| **Learning loop** | % of chat answers pinned; **30-day retention of pinned tiles** | Retention is the honest one — it measures whether the product learned what the user actually cares about, not just that they clicked |
| Productivity | Time-to-answer vs. the analyst-request baseline; ad-hoc requests deflected from the analyst queue | The value claim, stated in analyst hours |
| Trust | Thumbs-up rate; **refusal rate and refusal appropriateness**; % of answers whose sources were expanded | A refusal rate near zero is a red flag, not a win |
| Proactive quality | Alert click-through; alert mute rate | Mute rate is the early-warning signal for alert fatigue |

---

## 8. Open questions

1. **Alert materiality (blocks S1-FR-26).** What threshold makes a movement worth
   interrupting someone for? Statistical significance alone will over-fire. Needs a
   materiality floor and probably a per-metric sensitivity default.
2. **Alert fatigue (blocks S1-FR-27).** The demo carries one alert and so dodges the
   question. Real usage needs muting, a cap on alerts per day, and a rule for repeat
   movements.
3. **Dashboard open/closed state** does not persist across sessions; contents do. Should the
   panel remember it was closed?
4. **Feedback capture (S1-FR-18)** is UI-only. Thumbs data is a trust metric — decide where
   it lands and whether it feeds answer ranking.
5. **Cold start beyond templates.** Role templates work at launch. Should the dashboard adapt
   from observed behaviour over time, and if so, does the user get to see and correct what it
   inferred?

---

## 9. Prototype status

Built as a Streamlit prototype in this repository: [`app.py`](../app.py) (interface),
[`dashboard_store.py`](../dashboard_store.py) (tile-spec persistence),
[`chat_store.py`](../chat_store.py) (transcript persistence),
[`mock_data.py`](../mock_data.py) (semantic layer, role policy, synthetic series, canned
agent).

**Real:** layout, persistence, role-based governance, refusal paths, pin loop, tile grid.
**Mocked:** the LLM agent, the warehouse, SQL validation, audit logging, authentication.

The mocked pieces return the same shapes the real modules will, so the interface should not
need to change when the DeepSeek-backed agent and the DuckDB warehouse land.
