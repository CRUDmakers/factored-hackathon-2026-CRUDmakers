# AI Backend: Architecture

**Status:** draft v0.2 (2026-09-28) · **Owner:** Gabriel · **Scope:** Python service that powers the Transaccional customer-service assistant.

Related: `SPEC.md` (implementation contract), `../backend/README.md` (Node mock-bank API), `../frontend/README.md` (demo internet banking), `../docs/features.md` (team scope), `../docs/transaccional_scope.md` (what the data supports).

### What changed in v0.2

The Node mock bank (`../backend`) now exists, so this version aligns the design with its real API.

- **The P0 write action is now a payment:** a transfer or a bill payment through Node. Node previews it (dry run), the customer confirms, Node executes it and the AI backend reads it back. This replaces `open_case`, because Node has no cases (ADR-003).
- **Sessions are checked by asking Node** (`GET /auth/sessions/current`). The AI backend never holds the JWT signing secret (ADR-002).
- **Repeat contact is counted from the assistant's own conversations**, because Node doesn't load call-center history.
- **Requests to the Node team** are listed in §16. Until they land, the design works around them.

---

## 1. Purpose

The AI backend turns a customer's chat message (Spanish or Portuguese) into one of three outcomes:

1. **A verified answer** about their accounts or transactions.
2. **A payment or transfer** that Node simulates, the customer confirmed and the system verified by reading it back.
3. **A structured handoff** to a human agent.

It stores no bank data of its own. It reads and acts only through the Node mock-bank API, using the customer's own session, and it stores only conversations, checkpoints and traces.

### Challenge requirements → where they are handled

| Requirement (problem statement) | Handled by |
|---|---|
| Keep conversational context, clarify ambiguity | Agent graph state + `clarify` route (§5, §6) |
| Ground answers in permitted records | Tools + verified facts (§8) |
| Report only verified actions | `verify` node: read-back from Node (§5) |
| Rules enforced outside the model | Policy engine (§9) |
| Auth; access per customer enforced in the tool layer | Node session check + Node scoping (§11) |
| Human handoff with facts, actions, evidence, open questions | Handoff builder (§10) |
| Spanish + Portuguese | Language detection + prompts (§5) |
| Learned component vs baseline, no leakage | Route classifier (§14) |
| Injection, tool failures, expired sessions, multilingual ambiguity | Security, reliability and eval (§11, §12, §14) |
| Tracing, bounded retries, safe fallback, reproducible setup | §12, §13, §15 |
| Latency and cost per case | Traces + eval metrics (§13, §14) |

---

## 2. System context

```
                                 1. POST /auth/test-sessions (service key)
┌──────────────────────────────┐ ───────────────────────────► ┌────────────────────────────┐
│ Frontend (../frontend)       │ ◄──────── JWT (15 min) ───── │ Node mock bank (../backend)│
│ Vite + React                 │                              │ Fastify + Prisma           │
│ internet banking +           │                              │ test IdP · sessions ·      │
│ Assistant panel              │                              │ scoping · balances ·       │
└──────────┬───────────────────┘                              │ transactions · FX ·        │
           │ 2. POST /v1/chat, Bearer <same JWT>              │ payments (dry run) ·       │
           ▼                                                  │ scheduled payments         │
┌──────────────────────────────┐                              └─────────────┬──────────────┘
│ AI backend (Python)          │ ───────────────────────────────────────────┘
│ FastAPI + LangGraph agent    │  3. same JWT: session check, reads, payments
│ policy · classifier · eval   │
└──────┬────────────────┬──────┘
       │ LLM calls      │ conversations, checkpoints, traces
       ▼                ▼
┌───────────────────┐ ┌────────────────────────────┐
│ Model providers   │ │ Postgres 17                │
│ Anthropic, open   │ │ banking    (Node, ./data)  │
│ models            │ │ ai_backend (AI backend)    │
└───────────────────┘ └────────────────────────────┘
```

| Component | Owns |
|---|---|
| Frontend (`../frontend`) | Internet banking UI, the Assistant chat panel (a placeholder today), confirmation buttons, human-agent panel (handoff JSON + trace). Holds the demo service key that issues test sessions. |
| **AI backend** | Understanding, routing, dialogue, policy, tool orchestration, handoff, traces, evaluation |
| Node mock bank (`../backend`) | Test identity provider and sessions (issue, check, revoke), **per-customer data scoping**, balances, transactions, reports, FX, simulated payments (transfer, Pix, bill) with dry run, scheduled payments |
| Postgres | `banking` database (Node: the dataset loaded from `./data` plus simulated operations) and `ai_backend` database (conversations, checkpoints, traces) |
| S3 → `./data` | Raw dataset. Node's ETL loads it (`docker compose run --rm etl`) |

---

## 3. Design principles

1. **The model understands and talks; code decides.** Permissions, limits, escalation, amounts, currency maths and the handoff record are deterministic code.
2. **Identity comes from the session only.** No LLM-facing tool takes a customer ID. The bank client builds Node URLs from the session's customer, and Node rejects any mismatch.
3. **Tool output is data, never instructions.** Text inside records (merchant names, descriptions, beneficiary names) can't change behaviour.
4. **Say only what is verified.** Facts come from tool results. An action is "done" only after it has been read back from Node.
5. **No write without a preview.** Every payment is dry-run in Node first. The customer confirms what Node previewed, not what the model wrote.
6. **Everything is bounded:** steps, clarifications, retries, timeouts, tokens, cost.
7. **Fail safe:** when uncertain, clarify or hand off. Never guess, and never retry a payment blindly.
8. **Model-agnostic core.** Domain modules (policy, tools, bank client, handoff, metrics) never import LangGraph, LangChain or a provider SDK.
9. **Every decision leaves a record:** reason codes + traces. Hidden model reasoning is never used as an audit artifact.

---

## 4. Decisions

### ADR-001: orchestration framework

**Context:** we want to use several models (Anthropic + open models), pause for customer confirmation, persist conversation state, and keep strict control over tool execution.

| Option | Assessment |
|---|---|
| **LangGraph** (+ LangChain chat-model integrations) | Model-agnostic; explicit state graph matches Understand → Decide → Act → Verify → Escalate; built-in checkpointing (conversation state) and `interrupt` (confirmation pause). Costs: another abstraction; provider-specific features must be checked per integration; fast-moving APIs. |
| Claude Agent SDK | Claude only, so it doesn't meet the multi-model goal. It's built for autonomous coding/file agents with built-in Bash and file tools, which is the wrong shape for a guarded customer-service flow. |
| Plain provider SDKs + own loop | Maximum control, but we'd have to write multi-provider tool-call normalisation, state persistence and pause/resume ourselves. |

**Decision:** **LangGraph** for orchestration, with **LangChain chat-model integrations** to normalise tool calling across providers. Domain logic stays framework-free (principle 8), so the graph can be replaced without touching policy, tools or evaluation.

**Consequences:**
- Pin exact versions and verify APIs against current docs.
- Anthropic models go through `langchain-anthropic` (official Anthropic SDK underneath), never through an OpenAI-compatible shim.
- Check that prompt caching and effort settings are passed through correctly.
- The confirmation pause is kept in the conversation state rather than with `interrupt` (SPEC §8.1), so checkpointing, not `interrupt`, is what the payment flow relies on.

### ADR-002: session validation through Node

**Context:** Node signs sessions as HS256 JWTs with a shared secret, and logout is recorded in Node's database (`revoked_sessions`).

| Option | Assessment |
|---|---|
| Verify the JWT locally with the shared secret | No network call. But with HS256, whoever can verify can also sign, so the AI backend could mint a session for any customer. It also can't see logouts. |
| **Ask Node** (`GET /auth/sessions/current`) on every turn | One extra call on the same network. It covers expiry, bad signatures and logout, and no signing secret lives in the AI backend. |

**Decision:** ask Node. The AI backend holds neither the JWT secret nor the service key.

**Consequences:**
- The AI backend depends on Node for auth. If Node is down, nothing works anyway.
- The check happens before any LLM call, so an expired or revoked session costs no tokens.

### ADR-003: P0 write action

**Context:** v0.1 used `open_case`. Node has no cases, but it has transfers, Pix and bill payments with `?dry_run=true`. Every operation is recorded as a transaction that can be read back with `GET /transactions/{id}`.

**Decision:**
- **P0 writes:** `transfer_money` and `pay_bill`, following the flow Node dry run → customer confirms → execute → read back.
- **Pix:** P1, until the naming question in §16 is settled.
- **`open_case`:** dropped. Follow-ups on pending or reversed transactions go to a human (`FOLLOW_UP_REQUIRED`).

**Consequences:**
- Node has no idempotency key yet (R2), so payments are **never retried automatically**. A timeout is resolved by reconciliation (§12).
- Payments change Node's balances, so the eval runs against the fake bank by default and against a freshly reset Node for smoke runs (§14).

---

## 5. Turn flow (the graph)

```
START
  │
  ▼
auth_guard: Node GET /auth/sessions/current ──(401)──► respond(login_required) ──► END
  │ ok
  ▼
intake: a payment awaiting confirmation? approve ──► execute_write (below) · reject/expired ──► respond
  │ nothing pending (or the customer moved on)
  ▼
preprocess: detect language (es/pt) · route classifier (answer | clarify | human | out_of_scope)
  │          · repeat-contact check (assistant conversation history)
  ├── P(human) ≥ direct threshold, or repeat contact ──────────► handoff ──► respond ──► END
  ├── confident out_of_scope ───► respond(refuse + where to go) ──► END
  ├── P(human) ≥ τ: flag "possibly needs a human" in the agent's prompt (the agent decides)
  └── answer / clarify
        │
        ▼
      agent (LLM with tools) ──(final text)──► respond ──► END
        │ tool calls
        ▼
      policy_gate ── deny ──────────► (error result back to agent)
        │  ├── escalate ────────────► handoff ──► respond ──► END
        │  ├── allow (read) ────────► run_read_tools ──► escalation_check ──► agent
        │  └── confirm (write) ─────► prepare_write (Node dry run) ──► policy_gate on the preview
        │                                ├── declined / invalid ──► (error result back to agent) or handoff
        │                                └── ok ──► turn ends: awaiting confirmation (Node's preview)
        │                                             ├── rejected / expired ──► agent
        │                                             └── approved ──► execute_write ──► verify ──► escalation_check ──► agent
        │                                                                 └── timeout / 5xx ──► reconcile ──► verify, or handoff
        ▼
   (loop bounded: max tool steps per turn, max clarifications per conversation)
```

- **`prepare_write`** calls Node with `?dry_run=true`. Node reports the debit, the exchange rate, the balance afterwards, the recipient's name and any predicted decline. The policy engine decides on that preview, not on the model's arguments.
- **`verify`** reads the transaction back (`GET /transactions/{id}`). It checks that the method, amount, currency and source product match what the customer confirmed. Only an `Approved` read-back is reported as done. A `Declined` read-back is reported truthfully, with its reason.
- **`reconcile`** runs when the execute call times out or fails with a 5xx. It looks for the operation among the customer's recent simulated transactions, and never re-sends it (§12).
- **`escalation_check`** runs the policy engine on the facts that just came back, such as a fraud flag, a blocked product or days overdue. It can send the turn to `handoff` even if the model didn't ask for it. A filtered search that returns at most 3 rows is checked like the transactions themselves (M5 found that one model answered from searches and never opened the flagged record).
- **`clarify`** is a hint from the classifier. The LLM phrases the question. After 2 unanswered clarifications, the system offers a human.
- Every node appends `TraceEvent`s (§13).

---

## 6. Conversation state

| Field | Notes |
|---|---|
| `conversation_id`, `turn_id` | Checkpointer thread ID |
| `customer_id` | From Node's session check. **The token itself is never persisted**; it arrives with each request |
| `language` | `es` / `pt`, updated per message |
| `messages` | Dialogue history (LLM view) |
| `route`, `route_confidence`, `intent` | From the classifier. `intent` is also stored per conversation for the repeat-contact check |
| `verified_facts[]` | `{fact, source_tool, record_id, as_of}` |
| `actions[]` | `{action_id, method, transaction_id, status, verified}` |
| `pending_action` | Awaiting confirmation: `{action_id, method, args, preview, summary, expires_at, idempotency_key, executed}` |
| `policy_decisions[]` | `{tool, decision, reason_code}` |
| `counters` | Tool steps this turn, clarifications, retries |
| `handoff` | Set when escalated |

---

## 7. Model layer

| Role | What it does | Initial choice |
|---|---|---|
| **Agent** | Dialogue + tool selection | `claude-opus-5-5` (default). Compared in the eval against cheaper Claude models (`claude-sonnet-5`, `claude-haiku-4-5`) and at least one open model with tool calling |
| **Judge** (eval only) | Grades response quality where deterministic checks can't | A different model from the agent under test; validated against human labels |
| **Classifier** | Route/intent | Local multilingual embeddings + logistic regression (not an LLM) |

- **Model registry:** `config/models.yaml` lists each model: provider, model name, parameters, price per million tokens and capabilities. The agent model is chosen by config, so switching models needs no code change.
- **Providers:**
  - Anthropic through `langchain-anthropic`.
  - Open models through an OpenAI-compatible endpoint (for example vLLM or Ollama locally, or a hosted provider) via `langchain-openai`.
- **Anthropic specifics:**
  - Cache the system prompt and tool definitions.
  - Tune the effort level with the eval.
  - A `refusal` stop reason counts as a failure, which leads to a safe fallback (handoff).
- **Open-model specifics:** tool-calling reliability varies. Safety doesn't depend on the model, because the policy gate, the Node preview and Node scoping enforce it.
- **Data:** everything is synthetic, but tools still send the LLM the minimum fields it needs (§8).

---

## 8. Tools

Tools are thin, typed wrappers over the `BankClient`. Each returns a Pydantic model with a **field allowlist**: the *LLM view*. The *policy view* can carry extra fields (such as `flagged_as_fraud`) that are **never shown to the LLM or the customer**.

| Tool | Class | Node endpoint (`/api/customers/{id}/…` unless noted) | Team feature | Priority |
|---|---|---|---|---|
| `get_balances` | read | `GET /balances` | #1 balances, amount owed, available credit | **P0** |
| `search_transactions` | read | `GET /transactions` | #6 recent transactions (filters) | **P0** |
| `get_transaction` | read | `GET /transactions/{id}` | #5 status + decline reason, #8 ATM/branch | **P0** |
| `convert_currency` | read (maths in Python) | `GET /api/exchange-rates` | #4 exchange rates | **P0** |
| `transfer_money` | write → preview → confirm | `POST /transfers` | #2 transfers (own products, same bank, other bank) | **P0** |
| `pay_bill` | write → preview → confirm | `POST /bill-payments` | #2 bill payments | **P0** |
| `handoff_to_human` | escalate | none | the human path | **P0** |
| `generate_files` | read (no bank call) | none: builds xlsx/csv from rows the agent already read; download at `GET /v1/files/{id}` (`CHAT_API.md`) | exports | P1 |
| `generate_report` | read | the template's reads (`/transactions`, `/balances`, `/reports/spending`, `/recurring-payments`, `/transactions/{id}`) | PDF reports from fixed templates; the model passes only the report and its parameters (`CHAT_API.md`) | P1 |
| `get_product_details` | read | `GET /products/{id}` | #10 expiry/interest | **P1** |
| `get_spending_summary` | read | `GET /reports/spending` | #7 spending by category | **P1** |
| `get_loan_adjustments` | read | `GET /adjustments` | #9 loan adjustment | **P1** |
| `send_pix` | write → preview → confirm | `POST /pix` | #2 Pix | **P1** (after naming, §16) |
| `schedule_payment` (+ list, cancel) | write → confirm | `/scheduled-payments` | #3 scheduled payments | **P2** |
| investments | — | — | out of scope | — |

Rules:
- Amounts and conversions are computed in code with `Decimal`. Node's money fields are parsed as `Decimal`, never `float`.
- Every result carries its source (tool, record IDs, `as_of`).
- **LLM view allowlists:** the model never sees `flagged_as_fraud` or `fraud_score`, full card or account numbers (last 4 digits only), counterparty document numbers, or branch phone numbers.
- **Language:** Node's free text is in pt-BR (`reason`, `status_description`, `decline_detail`, error messages). The model gets codes and structured fields, plus free text labelled as data, and replies in the customer's language.
- **Missing filters:** Node's `GET /transactions` has no merchant or amount filter. The tool applies them in Python until Node supports them (R3). This is cheap because customers have few transactions.
- **Dates:** the dataset ends on 2026-06-17, but Node uses the real clock (card expiry, schedules, new operations). The agent is told today's date and where the history ends. The fake bank's clock is injectable, and the eval pins it.
- **Idempotency:** write tools carry an idempotency key (sent as `Idempotency-Key`). Node ignores it until R2.

---

## 9. Policy engine

A pure function: `evaluate(tool_call, session, state, policy_view_facts) → PolicyDecision{decision, reason_code, message_key}`, with `decision ∈ {allow, confirm, deny, escalate}`. Thresholds live in `config/policy.yaml`.

| Reason code | Trigger | Decision |
|---|---|---|
| `AUTH_EXPIRED` | Node answers 401 (`unauthorized`, `session_expired`, `session_revoked`) | deny → ask to log in again |
| `TOOL_UNKNOWN` | Tool not in registry | deny |
| `WRITE_NEEDS_CONFIRMATION` | Any write whose Node preview is approved | confirm |
| `AMOUNT_OVER_LIMIT` | Previewed amount in USD (converted in code) > limit, or no USD rate | escalate |
| `INSUFFICIENT_FUNDS` | Preview declined with `51` | deny (explain, offer another source) |
| `CARD_EXPIRED` | Preview declined with `54` | deny (explain) |
| `INVALID_DESTINATION` | Preview declined with `14`, or Node 422 on the destination or barcode | deny (ask to correct; counts as a clarification) |
| `PRODUCT_BLOCKED` | Product `Blocked`/`Suspended` in a read, or preview declined with `05` | escalate |
| `FRAUD_RISK` | Transaction under discussion has `flagged_as_fraud`, or `fraud_score ≥ 40` once Node exposes it (R1) | escalate |
| `UNRECOGNIZED_CHARGE` | Customer says they don't recognise a charge | escalate |
| `DELINQUENT` | `days_past_due > 0` and customer wants to negotiate or arrange the debt. A plain payment toward the debt is allowed | escalate |
| `FOLLOW_UP_REQUIRED` | Customer wants follow-up on a `Pending` or `Reversed` transaction (there's no case system) | escalate |
| `REPEAT_CONTACT` | ≥ 2 earlier conversations with the assistant in 7 days about the same problem intent (`follow_up`, `decline_reason`) | escalate |
| `HUMAN_ROUTE` | The route classifier's P(human) is at or above its direct-handoff threshold (precision ≥ 0.90 on validation) | escalate |
| `ONE_ACTION_AT_A_TIME` | A second write in the same model message | deny |
| `INVALID_REQUEST` | Node 422 not about the destination (e.g. a credit card as a transfer source), or an unexpected decline code | deny (explain) |
| `CUSTOMER_REQUEST` | Customer asks for a person (`handoff_to_human`) | escalate |
| `ASSISTANT_FAILURE` | The model failed after retries, refused, or returned an unusable answer | escalate |
| `BANK_UNAVAILABLE` | Node timed out, failed (5xx) or answered malformed data, after the client's retries | escalate (safe message) |
| `OUTCOME_UNKNOWN` | A payment timed out and reconciliation can't find it | escalate, never retry |
| `VERIFY_MISMATCH` | The read-back doesn't match the confirmed action | escalate |
| `LIMIT_REACHED` | Max tool steps or clarifications | escalate |
| `OUT_OF_SCOPE` | Classifier route or unsupported request | refuse + redirect |
| `CROSS_CUSTOMER` | Node answers 403, or a record's owner differs from the session (once R4) | deny + security event |

Node answers **404** for another customer's record, exactly as for an unknown ID, so its existence is never revealed. A 403 only happens when the URL's customer differs from the token's, which the bank client never does, so a 403 means a bug and is treated as a security event.

---

## 10. Human handoff

The handoff is built by **code** from the state, not written freely by the model. Only `request_summary` and `open_questions` are model-generated, and they are marked as such.

```json
{
  "handoff_id": "HND-…",
  "conversation_id": "…",
  "customer_id": "CLI-…",
  "language": "pt",
  "priority": "high",
  "reason_codes": ["FRAUD_RISK", "UNRECOGNIZED_CHARGE"],
  "request_summary": {"text": "…", "generated_by": "model:<id>"},
  "verified_facts": [{"fact": "Purchase of 912.40 USD at Cine Premium on 2026-03-14 — Approved", "source": "get_transaction", "record_id": "TRX-…"}],
  "actions_taken": [{"type": "transfer", "status": "Approved", "verified": true, "record_id": "TRX-…"}],
  "evidence": {"transaction_ids": ["TRX-…"], "trace_id": "…"},
  "open_questions": {"items": ["Customer says the card never left their possession"], "generated_by": "model:<id>"},
  "created_at": "…"
}
```

---

## 11. Security

- **Authentication:**
  - The frontend gets a test session from Node (`POST /auth/test-sessions`). This is a simulated identity provider guarded by a service key; the Node README explains its limits.
  - The frontend sends the same bearer token to the AI backend.
  - On every turn, the AI backend checks the token with Node (`GET /auth/sessions/current`), which covers expiry and logout. It then forwards the same token to Node for every call.
  - The AI backend never holds the JWT signing secret or the service key (ADR-002).
- **Authorisation:**
  - Node scopes every `/api/customers/{id}/…` route to the token's customer.
  - The bank client builds those URLs from the session only.
  - LLM-facing tools have no identity parameters.
  - Once Node returns record owners (R4), the AI backend also checks that each record belongs to the session customer (defence in depth).
- **Prompt injection:**
  - Tool results are delimited and labelled as data.
  - No tool can change policy or reach another customer.
  - Eval scenarios inject instructions into customer messages and into record fields (descriptions, beneficiary names).
- **Data minimisation:** per-tool field allowlists (§8). The LLM never sees document numbers, addresses, phones, emails, full card or account numbers, or risk fields.
- **CORS:** only the frontend origins listed in config.
- **Secrets:** env vars only; tokens and keys are redacted from logs and traces.
- **Retention:** conversations and traces are kept `TRACE_RETENTION_DAYS` (config), then deleted.

---

## 12. Reliability

| Concern | Rule |
|---|---|
| Timeouts | Node calls 3 s; LLM calls 30 s |
| Read retries | Max 2 with exponential backoff for reads, session checks and LLM calls |
| Write retries | **None**, until Node supports idempotency keys (R2). After R2: at most 1 retry, with the same key |
| Reconciliation | After a payment times out or fails with a 5xx, list the source product's simulated transactions since the confirmation, and match the method, amount and currency. Found → `verify`. Not found → `OUTCOME_UNKNOWN` handoff. The customer is told the result is unknown, not that it failed |
| Bank failure | After the client's read retries, a timeout, 5xx or malformed answer from Node ends the turn with a safe message and a handoff (`BANK_UNAVAILABLE`) that includes what is known. The model doesn't improvise around a missing answer. During a payment, see reconciliation |
| LLM failure / refusal | Safe message + handoff |
| Budgets | Max 6 tool steps per turn, 2 clarifications per conversation, `max_tokens` per call |
| Confirmation | Pending actions expire after 5 minutes and execute at most once. The action is marked `executed` in state before Node is called |

---

## 13. Observability

One trace per turn: `trace_id`, `conversation_id`, per-node timings, route + confidence, model ID + prompt version, tool calls (redacted arguments), Node calls (endpoint, status, latency), policy decisions with reason codes, tokens in/out/cached, cost, latency, outcome.

- Stored in the `ai_backend` database and emitted as JSON logs (structlog).
- `GET /v1/conversations/{id}/trace` powers the human-agent panel and the demo.
- Aggregates feed the eval report: p50/p95 latency, cost per case, outcome counts.

---

## 14. Evaluation

- **Scenarios** (YAML, built from real transactions in the fixture):
  - The fixture is a stratified extract of the same dataset Node loads. It includes the frontend's demo customers.
  - Categories: normal · ambiguous · unsupported · human-required · attack (injection, another customer's record, expired or revoked session) · failure (Node timeout or 500, malformed response, a payment with an unknown outcome) · multilingual.
  - Split into dev/test, with **test frozen** before tuning.
- **Bank under test:**
  - **Default: the fake bank.** It's deterministic, uses a pinned clock and supports fault injection, and it mirrors Node's contract.
  - **Smoke runs against live Node** after `npm run db:reset`, to catch contract drift.
  - Contract tests keep the fake and Node in agreement (SPEC §5).
- **Systems compared on the same test set:**
  - **B0:** keyword/FAQ bot.
  - **B1:** LLM + tools, without the policy engine or classifier.
  - **S:** full system.
  - Each run 3 times; model variants run as separate configs.
- **Metrics** (as defined in the problem statement):
  - Safe automated resolution (over all in-scope cases, plus the share where automation was attempted).
  - Containment.
  - Escalation quality (missed and unnecessary transfers).
  - Unsafe outcomes (count / denominator). An unconfirmed or unverified payment reported as done counts as unsafe.
  - p50/p95 latency; cost per attempted case and per successful resolution.
  - Everything broken down by language and customer segment.
- **Grading:** deterministic checks first (outcome, reason codes, tool calls, facts, forbidden actions, payments executed). The LLM judge is used only for response quality and is validated on ≥ 30 human-labelled cases.
- **Learned component:** the route classifier (SPEC §10, `classifier_data/report.md`), trained on **model-drafted** ES/PT utterances (the dataset has none usable).
  - Split by template family, frozen before tuning, to prevent leakage.
  - Baseline: keyword rules.
  - Metrics: macro-F1 and **human-route recall**, which sets τ. On the test split the model reaches all 24 human-route cases (the baseline 18) at the cost of more flags; used as triage (direct handoff only at high precision, otherwise a flag to the agent), it made 8/8 correct direct handoffs and 10/10 correct refusals.
- **Results (M5, `eval/reports/m5-test/report.md`):** 262 frozen test scenarios × 3 repeats per system, agent `gemini-3.8-flash` through the development router.

  | | B0 | B1 | S |
  |---|---|---|---|
  | Safe automated resolution | 219/417 (52.5%) | 328/417 (78.7%) | **414/417 (99.3%)** |
  | Missed handoffs | 114/192 | 119/192 | **4/192** |
  | Unnecessary handoffs | 3/594 | 8/594 | **0/594** |
  | Unsafe outcomes | 24/786 | 140/786 | **0/786** |

  - B1's unsafe outcomes are 74 payments nobody asked for and 66 made before the customer confirmed: the same model and prompt without the policy engine.
  - With `gpt-oss-120b` as the agent, S stays at 0 unsafe but misses 44/192 handoffs: blocked-source, over-limit and fraud-flagged escalations depend on the model calling the payment tool or `get_transaction`. That is a design gap to fix (escalation on read results too).
  - The `claude-sonnet-4-6` run is not a valid measurement: the router adds a placeholder argument to tools with an empty schema, and the provider failed on 56 cases in one repeat.
  - The judge (response quality) is not validated yet; latency and tokens include the router's overhead, and cost is a list-price estimate over those tokens (an upper bound).
- **Results after the fixes (M5 v2, `eval/reports/m5-test-v2/report.md`):** language detection by one-language words, escalation on narrow searches, `get_balances` tolerant of a placeholder argument, and prompt v4. S: 0/192 missed handoffs (v1: 4), still 0/786 unsafe; B1 with the same prompt still 141/786 unsafe. `claude-sonnet-4-6` becomes measurable (94.2% safe resolution, 0 unsafe) but still skips some escalations the prompt asks for, which argues for enforcing them in code. The fixes came from reading test failures, so v2 is not a held-out estimate.

---

## 15. Deployment & configuration

- **Docker Compose:** an `ai-backend` service next to `db`, `api` and `frontend` in the root `docker-compose.yml`:
  - Port 8000; the image runs as a non-root user and is healthy only when `/v1/health` is.
  - `BANK_MODE=http` and `BANK_BASE_URL=http://api:3000`.
  - `DB_URL=postgresql://…/ai_backend`. The service creates that database on startup if it's missing (Postgres init scripts only run on a fresh volume, so teammates' existing volumes would never get it). One connection pool serves the LangGraph checkpointer and the stores; an advisory lock keeps one turn at a time per conversation across servers.
  - CORS open to the frontend origin.
  - The model settings come from `ai-backend/.env` if present.
  - The frontend reaches the service from the browser, so it gets the AI backend's URL as a build argument (see `CHAT_API.md`).
- **Offline:** the same image runs with `BANK_MODE=fake` (fixture data) and SQLite for tests and eval.
- **Config:** env vars for secrets and endpoints; `config/models.yaml` and `config/policy.yaml` for behaviour.
- **Health:** `GET /v1/health` checks the configuration, the model registry and its credentials, Node's `/health`, and the database.

---

## 16. Open decisions and requests

**Settled in v0.2:**
- **Database:** Postgres from Compose, in a separate `ai_backend` database. SQLite for tests.
- **Session format:** Node's HS256 JWT, checked through Node (ADR-002).
- **P0 write:** Node payments (ADR-003).
- **Hosting:** the Docker Compose stack in the repo root (Postgres, Node API, AI backend, nginx frontend), with restart policies; the ETL runs on demand. Operations and remaining deployment work are in the root README (English summary).

**Still open:**
1. **Payment method names:** Node uses Pix and boleto, which are Brazilian. The bank operates in México (SPEI), Colombia (PSE/Bre-B) and Argentina (CVU/alias). The recommendation is to keep Node's API names internally and use generic, country-appropriate wording with customers. Pix stays P1 until this is settled.
2. **Model providers for the final eval and the deployment.**
   - During development, the agent and judge run on Gemini through a local 9router (`gemini-3.8-flash` as agent, `gemini-3.1-pro-low` as judge, both via the OpenAI-compatible endpoint).
   - That route can't be used for the submission:
     - Judges can't reproduce it, and the deployed service can't reach a local router.
     - The router adds about 2.1k hidden prompt tokens to every call, which distorts latency, token and cost metrics and adds instructions we don't control.
     - A retired model answered with HTTP 200 and an error message as its content, so the LLM layer must treat a response without `usage` as a provider failure.
   - M5 still ran through the router (no direct keys yet): the agent comparison is `gemini-3.8-flash` vs `gpt-oss-120b` (open-weight) vs `claude-sonnet-4-6`, judged by `gemini-3.1-pro-low`. Its token and latency numbers carry the router's overhead; cost is estimated from the tokens at each model's list price (`models.yaml`).
   - Not done before the submission: rerun the test split on direct providers (for example Anthropic plus `gpt-oss-120b` on a hosted endpoint) with the shipped prompt `system_v6`, with the same commands. Until then the numbers describe `system_v4` on the router models (root README, limitations).
3. **Owner of S3 → `./data`:** the download is manual today; Node's ETL loads from `./data`.

**Requests to the Node team** (each has a workaround until it lands):

| # | Request | Why | Workaround until then |
|---|---|---|---|
| R1 | Expose `fraud_score`, ideally on an internal endpoint that also needs the service key | `FRAUD_RISK` needs the score. `flagged_as_fraud` is the dataset's ground-truth label, not a live signal | Escalate on `flagged_as_fraud` only, and report that honestly |
| R2 | Accept an `Idempotency-Key` header on `POST /transfers`, `/pix`, `/bill-payments`, `/scheduled-payments` | Safe retries after a timeout | Never retry writes; reconcile (§12) |
| R3 | `merchant` (case-insensitive contains), `min_amount` and `max_amount` filters on `GET /transactions` | "My Uber payment" lookups | Filter in Python |
| R4 | Include `customer_id` in transaction and product responses | Defence-in-depth ownership check | Rely on Node's URL scoping |
| R5 | Agree when a status reason is given. `explainStatus` gives a decline reason for `Pending`/`Reversed` rows that have a non-`00` code | The codes don't match the data (§17), so "insufficient funds" on a pending transfer misleads | The AI backend cites a reason only for `Declined` |
| R6 | ~~Compose: create the `ai_backend` database in `backend/docker/initdb`, and add the `ai-backend` service~~ | Deployment | **Done on the AI side (M3):** the service is in `docker-compose.yml` and creates its own database, so Node's files are untouched |

---

## 17. Known data limitations (to report)

- Each transaction has only one status; there's no status history.
- Balances are current snapshots only. Demo payments change them in Node's database, and `npm run db:reset` restores them.
- The history ends on 2026-06-17, but Node uses the real clock. Many cards are expired today, so payments from them are declined with `54`.
- Complaints can't be linked to transactions, and Node loads neither complaints nor call-center contacts.
- There's no credit-card statement data: no due date or minimum payment.
- Mexican products are priced in USD.
- The data has no Portuguese, and the transcripts are templates.
- Decline codes don't match the product data. `Pending` and `Reversed` rows also carry non-`00` codes (R5).
- Statuses are uniform across transaction types and channels.
- Some credit cards are over their limit, so their available credit is negative.
