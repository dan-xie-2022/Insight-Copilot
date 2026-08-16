# Insight Copilot — Architecture

Two diagrams: where a question travels, and how the product learns from every answer it has
already given.

---

## The stack

<img src="docs/images/architecture.png" alt="Layered architecture. Employees and analysts sit at the top; requests flow down and responses flow back up. Application layer: conversational UI, insight workflows, channel integrations. Infra and agent orchestration layer: analytical agents, agent orchestration, tool and MCP ecosystem, LLM gateway and guardrails, over a full-width observability and evaluation band. Semantic and intelligence layer: the governed semantic layer holding metrics, dimensions, definitions and business logic as the single source of semantic truth. Data access and execution layer: a query engine covering text-to-SQL, API calls, search, vector queries and code execution. Data platform layer: enterprise data platform, data lake and raw data, data products and features. Governance runs cross-cutting beneath every layer, with a right-hand rail pairing each layer to a concern — security and access control, privacy and PII protection, policy enforcement, audit and compliance, quality and observability, risk management." width="700">

Five layers, and the boundaries are the design. Employees enter at the top and never touch
anything below the application layer. The orchestration layer plans, routes and evaluates;
it does not compute — which is the same division `agent.py` and `causal.py` enforce in code,
and the entire safety argument rests on it.

Below that, what used to be one "data" box is properly three, because they fail differently.
The **semantic layer** decides what a metric *means* — one definition, every surface, so the
dashboard and the copilot cannot disagree about conversion rate. The **execution layer**
decides what a question is *allowed to run* — text-to-SQL is scoped to governed definitions
rather than turned loose on raw tables. Only then does anything reach the **data platform**.
A single "text-to-SQL over the warehouse" arrow hides both of those decisions, and they are
where the trust is won or lost.

Governance is drawn cross-cutting rather than as a layer because access control, PII
protection, audit and risk are not a step in the flow — they are a property of it. Each
concern on the right pairs with the layer it constrains: PII protection has to sit where
tools execute, not where results are rendered, or it is decoration.

Observability and evaluation span the full width of the orchestration layer for the same
reason, and they are the hinge into the second diagram: every answer this stack produces is
traced on the way out.

---

## The evaluation harness

![Evaluation harness loop: every answer traced, selected for review, scored by a judge and human panel, sorted into a failure taxonomy, routed to an owner for the fix, added to the golden set, and gated in CI before deploy — the fix reaching every future answer.](docs/images/evaluation-harness.png)

Answer quality is a production property, not a launch checklist. Tracing is not sampled —
sampling happens at review. Selection is biased on purpose: every thumbs-down and every
refusal enters review alongside the random sample. The judge is itself a model, so humans
score a fixed slice to calibrate it. The taxonomy exists to route, not to describe: a wrong
metric definition is an analyst's job, a wrong routing decision is a prompt or tool fix.

The payoff is the return edge. A ticket fixes one answer for one person; a golden-set case
behind a CI gate fixes the class of answer for everyone.
