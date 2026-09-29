# AI backend

Python service for the Transaccional customer-service assistant. Design: `ARCHITECTURE.md`. Implementation contract: `SPEC.md` (v0.2, aligned with the Node mock bank in `../backend`).

**Status:** M5. The evaluation harness compares the full system (S) with a plain tool loop on the same model (B1) and a keyword bot (B0) on 262 frozen test scenarios × 3: S resolves 99.3% of in-scope cases safely, with 0 unsafe outcomes in 786 cases (B1: 140). Report, error analysis and model comparison: `eval/reports/m5-test/report.md`.

**M4:** A route classifier triages each message before the agent (direct handoff, refusal, or a note for the agent): data, split, baseline, model and report in `classifier_data/` (start with `report.md`).

**M3:** Runs in Docker Compose next to Node, Postgres and the frontend (below). Chat API for the frontend: `CHAT_API.md`.

**M2:** The assistant answers from the bank (read tools), makes transfers and bill payments (Node's preview → the customer confirms → executed once → verified by read-back, with reconciliation after a timeout), and hands off to a human with a structured record (`GET /v1/handoffs/{id}`), all under a code-enforced policy engine. M0 (bank layer, fixture, contract tests) is below.

## Setup

```bash
cd ai-backend
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # fake mode needs nothing
```

## Run with Docker Compose (from the repo root)

```bash
docker compose up -d db && docker compose run --rm etl   # once: load the dataset into Node's database
docker compose up -d --build                              # db + api (3000) + ai-backend (8000) + frontend (5173)
curl localhost:8000/v1/health                             # models, bank (Node) and storage (Postgres)
```

The model settings come from `ai-backend/.env` (optional). The local 9router is reached as `host.docker.internal:20128`; override it with `AI_OPENAI_COMPAT_BASE_URL`. The `ai_backend` database is created on first start.

## Run locally

```bash
.venv/bin/uvicorn ai_backend.api.app:app --reload                  # BANK_MODE=fake (default)
BANK_MODE=http BANK_BASE_URL=http://localhost:3000 \
  .venv/bin/uvicorn ai_backend.api.app:app --reload                  # against Node
curl localhost:8000/v1/health
```

Chat (the token is a Node session token; in fake mode, tests and the eval issue them from the fake bank):

```bash
curl -s localhost:8000/v1/chat -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"message": "Meu pagamento de ontem na Uber foi aprovado?"}'
curl -s localhost:8000/v1/conversations/<conversation_id>/trace -H "Authorization: Bearer <token>"
```

Confirming a payment (the previous response had `status: "awaiting_confirmation"`):

```bash
curl -s localhost:8000/v1/chat -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"conversation_id": "<id>", "confirmation": {"action_id": "<pending_action.action_id>", "decision": "approve"}}'
```

The agent model comes from `AGENT_MODEL` in `.env` (see `.env.example`; development uses Gemini through a local 9router). `CLOCK_OVERRIDE` pins "today" for the fake bank and the agent, for reproducible runs.

In http mode, the AI backend checks every session with Node (`GET /auth/sessions/current`) and forwards the customer's token. It never holds Node's JWT secret or service key.

## Bank layer

| Module | What it is |
|---|---|
| `bank/client.py` | The `BankClient` interface and errors, modelled on Node's API |
| `bank/http_client.py` | Node client: token forwarding, retries for reads only, error mapping, exact decimals |
| `bank/fake_client.py` | Offline bank that behaves like Node (sessions, scoping, payments, declines), for tests and eval |
| `bank/faults.py` | Fault injection for either client: `timeout`, `error_500`, `malformed`, `slow`, `lost_response` |

## Offline fixture

`BANK_MODE=fake` reads a stratified extract of the same dataset Node loads, from `eval/fixtures/data/`. It has 80 customers, including the frontend's demo customers. Personal data is removed, and card numbers keep only their last 4 digits. To rebuild it, you need the S3 credentials in the repo-root `.env`:

```bash
.venv/bin/pip install -e ".[fixtures]"
.venv/bin/python -m eval.fixtures.download --start 2025-12-20 --end 2026-06-17   # into ../data (gitignored)
.venv/bin/python -m eval.fixtures.extract
```

## Route classifier

```bash
.venv/bin/python -m ai_backend.classifier.dataset   # templates.yaml → utterances.csv (with checks)
.venv/bin/python -m ai_backend.classifier.split     # only for a new dataset: the split is frozen
.venv/bin/python -m ai_backend.classifier.train     # → models/route_classifier.joblib + report.md
```

The trained model is committed and shipped as is, because retraining on another platform can pick different hyperparameters. The embedding weights (~240 MB) are downloaded on first use into `models/fastembed/`. Set `CLASSIFIER_PATH=` (empty) to run without the classifier.

## Evaluation

```bash
.venv/bin/python -m eval.build_scenarios            # fixture → eval/scenarios/{dev,test}/*.yaml (gitignored)
.venv/bin/python -m eval.runner --systems B0,B1,S --split dev              # debug on dev
.venv/bin/python -m eval.runner --systems B0,B1,S --split test --repeats 3 --judge
.venv/bin/python -m eval.runner --systems S --model gpt-oss-120b --split test --repeats 3 --judge
.venv/bin/python -m eval.report eval/runs/<run> eval/runs/<run>   # merge runs into one report
.venv/bin/python -m eval.judge agreement eval/runs/<run>/judge_validation.csv   # after labelling
```

The scenarios are generated from the fixture, so they are rebuilt locally rather than committed. `eval/scenarios.lock.json` pins the test split, and the runner refuses to run test if the rebuilt files differ. Reports go to `eval/reports/` (committed). Raw transcripts and the judge's labelling sheet go to `eval/runs/` (gitignored: whole conversations). The runs need the models in `.env`; the harness itself is tested offline with a scripted model (`tests/unit/test_eval_grading.py`, `tests/integration/test_eval_runner.py`).

## Test

```bash
.venv/bin/python -m pytest -q        # unit + integration + contract suite against the fake
.venv/bin/ruff check .
```

### Live model tests

`tests/live/` runs the M1 and M2 acceptance cases (ES and PT questions, payments with confirmation, a handoff; real fixture) against the model configured in `.env`. They're excluded by default because they call the model:

```bash
.venv/bin/python -m pytest -m llm tests/live -s   # -s prints each answer, its tools, tokens and latency
```

### Postgres storage

```bash
docker run -d --name ai-backend-pg-test -e POSTGRES_USER=banking -e POSTGRES_PASSWORD=banking -p 55432:5432 postgres:17-alpine
TEST_POSTGRES_URL=postgresql://banking:banking@localhost:55432/banking .venv/bin/python -m pytest -m postgres
```

### Against the running stack

```bash
# Chat service ↔ live Node, scripted model (deterministic), plus the bank contract suite
BANK_BASE_URL=http://localhost:3000 EVAL_SERVICE_KEY=demo-service-key .venv/bin/python -m pytest -m node tests/live tests/contract
# The whole stack over HTTP with the real model: login at Node, chat with the container, check in Node
AI_BASE_URL=http://localhost:8000 BANK_BASE_URL=http://localhost:3000 EVAL_SERVICE_KEY=demo-service-key \
  .venv/bin/python -m pytest -m "node and llm" tests/live/test_stack_smoke.py -s
```

These make small real transfers between one demo customer's own accounts; `npm run db:reset` in `../backend` restores Node's data.

### Contract tests against a live Node

`tests/contract/` runs the same cases against the fake and against Node, so the fake can't drift from what we ship. Against Node, start the stack from the repo root and load the data, then run the suite:

```bash
docker compose up -d db && docker compose run --rm etl && docker compose up -d api
BANK_BASE_URL=http://localhost:3000 EVAL_SERVICE_KEY=demo-service-key \
  .venv/bin/python -m pytest -q -m node tests/contract
```

The suite makes a small real transfer (1.00 USD between one demo customer's own accounts). Reset Node's database afterwards if you need a clean state (`cd ../backend && npm run db:reset`).

If ports 3000 or 5432 are taken, run the stack as a separate project with an override file that remaps them. For example, use `ports: !reset []` for `db`, and `ports: !override ["3100:3000"]` for `api`:

```bash
docker compose -p bcs-contract -f docker-compose.yml -f <override.yml> up -d db
```
