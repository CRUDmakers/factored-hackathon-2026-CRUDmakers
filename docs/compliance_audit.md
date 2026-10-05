# Hackathon compliance audit

**Date:** 2026-10-01 · **Checked against:** *Factored AI & Data Hackathon 2026, Problem Statement* and the *Kickoff* deck (2026-09-25) · **Repo state:** `main` at `09e0c56`

**Submissions close: Sunday, October 5, 2026.**

## Verdict

**The system itself is strong, but as of today it can't be submitted.** The AI design, the safety evidence and the honesty of the reporting are well above what the rules ask for. What's failing is submission logistics plus a few evidence gaps, all fixable before the deadline.

The best evidence the team has: the same model and prompt, **without** the policy engine (B1), produced **141 unsafe outcomes out of 786 cases**. With the policy engine (S), it produced **0 out of 786**, with **0 of 192 handoffs missed** (`ai-backend/eval/reports/m5-test-v2/report.md`).

## Blockers: submission would fail or be marked down

| # | Rule | Status | What was found |
|---|---|---|---|
| 1 | Public repo named `factored-hackathon-2026-[team]` | ⚠️ | **Name fixed** (2026-10-01): renamed to `CRUDmakers/factored-hackathon-2026-CRUDmakers`. Still **private**. **Watch out:** the `dataAnalyse` branch contains the **raw dataset** (`customers.csv` alone is 150k rows of names, emails and phones; about 577k lines in total, from commit `3a358fa`). Making this repo public publishes it. Create the submission repo from `main` only. |
| 2 | Link to the deployed tool | ❌ | There's no deployment config and no URL. `ai-backend/config/models.yaml` itself says the dev model (Gemini through the local router) is "not usable for the final eval or the deployment", so the deploy also needs a real provider and API key. |
| 3 | The evaluated system is the shipped system | ❌ | The report measured prompt **`system_v4`**. The code runs **`system_v6`**. Recurring payments, Excel/CSV exports, scheduled payments and spending analysis have **0 of 262** test scenarios. The judges will look at a system that was never measured. |
| 4 | Cost per attempted case and per resolution | ❌ | The report says "not defined", but the rule only allows that wording "when there are no successful resolutions", and S has 414. Every `price_per_mtok` in `models.yaml` is `null`. Latency is also distorted by the router's hidden prompt, as the report itself says. |
| 5 | Slides (4–6) and the video pitch | ? | Not in the repo, so they couldn't be checked. |

## Rule-by-rule

| Requirement | Status | Evidence / gap |
|---|---|---|
| One coherent workflow | ✅ ⚠️ | Account and payment inquiries, with self-service payments; the kickoff explicitly allows "authorized self-service transactions". But the feature list keeps growing (scheduled and recurring payments, file exports, spending analysis), and the rules say more workflows earn no bonus. Present everything as one workflow. |
| Normal, ambiguous/unsupported and human paths | ✅ | All three are categories in the eval; human, unsupported and attack cases pass 100% for S. |
| Spanish and Portuguese, with limitations reported | ✅ | Results are broken down by language (pt 99.7%, es 99.5% checks passed), and the missing Portuguese in the data is reported. |
| **1. Problem supported by data** | ⚠️ | The figures in `docs/transaccional_scope.md` (H1 2025) and the data-quality notes in `README.md` are good. But no analysis code is committed; the kickoff asks to "justify workflow selection using reproducible logs". `docs/hackathon_strategy.md` recommended **disputes**, and nothing records why the team chose Transaccional. There's no cost-per-resolution or ROI figure. |
| **2. Functioning AI system** | ✅ | Conversation context, clarification, answers grounded in tool results, and payments read back from the bank before they're reported. |
| **3. Controlled automation** | ✅ | Policy enforced in code, a preview and confirmation before every payment, and a structured handoff JSON. |
| **4a. Data engineering** | ❌ | The Node ETL (`backend/src/etl/load.ts`) deletes everything and reloads it. There's no schema contract beyond Postgres types, no quality report, no lineage record, and no incremental or freshness policy. "Update correctness with a clearly labeled test fixture" isn't demonstrated. The Node tests **can't run from a clone**, because `backend/tests/fixtures/data` was never committed. |
| **4b. Learned component vs baseline** | ✅ | The route classifier (`ai-backend/classifier_data/report.md`), with the split by template family and the threshold reasoning written up. The report openly admits the test split was influenced by design decisions. The model loses on macro-F1 (0.717 vs 0.810) but wins on human-route recall (24/24 vs 18/24), which is a fair trade to argue. |
| **5. Held-out quality and failures** | ✅ ⚠️ | Expired, missing and revoked sessions, another customer's data, prompt injection, bank 500s and timeouts, lost payment responses, mixed languages: all covered. v2 isn't held-out, and the report says so. The gap is blocker 3. |
| LLM judge validated | ❌ | 0 human labels in all 6 `judge_validation.csv` sheets under `ai-backend/eval/runs/`. Either label 30 rows (`python -m eval.judge agreement <file>`) or drop the judge scores from the report. |
| Results by language and segment | ✅ | Both tables are in the report. |
| **6. Route to operation** | ✅ ⚠️ | Tracing, bounded retries, payment reconciliation, safe fallback, and the trace-retention purge are all implemented in code (`ai-backend/ARCHITECTURE.md` §12–13). Nothing is written yet on capacity limits, monitoring and alerting, or remaining deployment work. |
| Reproducible setup | ⚠️ | The root `README.md` describes the dataset, in Portuguese; it has no setup, architecture, results or links. A clone can't rerun the eval: the scenarios, the fixture and the raw data are all gitignored. |
| Authentication | ✅ ⚠️ | The simulated identity provider is documented well (`backend/README.md`). But the service key ships in the frontend bundle, so on a public deployment anyone can open a session for **any** of the 150k customers by typing an ID. That looks a lot like "a customer number alone does not prove identity". Limit sessions to the demo customers when deployed, and label the login screen as a test identity provider. |
| Data provenance (real, synthetic, team-generated) | ⚠️ | The information is spread across files: the synthetic organizer dataset, the AI-drafted classifier phrases, the templated scenarios, the `seed-marta-recurring.sql` demo data. The rules ask for one explicit statement. |
| No real money moved | ✅ | All payments run in the mock bank only. |

## Plan for the remaining days

### P0: required to submit

1. **Repo:** a new public `factored-hackathon-2026-<team>` pushed from `main` only. Also check whether the dataset's terms allow publishing the derived fixtures.
2. **Deploy:** use a real model provider, limit test sessions to the demo customers, and label payments "simulado".
3. **Final eval:** run it on the deployed model with `system_v6`, with prices filled in so cost is defined and latency is real. Add scenarios for recurring payments, spending and exports, or label those features "not evaluated".
4. **Root README in English:** workflow choice with the data behind it, architecture, how to run (including the offline fixture mode), the results table, limitations, the data provenance table, and links to the deployment, slides and video.
5. **Slides and video.**

### P1: raises the score

- Label 30 judge cases.
- ETL: schema validation, a count of rejected rows, a lineage manifest (file, rows, checksum, load time), an incremental load by daily partition with a labeled fixture test, and a committed Node test fixture.
- A reproducible analysis script for contact reasons and demand over the full three years that justifies the workflow choice, plus a clearly labeled projected-savings estimate.
- A short operations section: capacity, monitoring and alerting, remaining deployment work.

### P2

- Retrain the classifier for saving-advice questions (today "¿cómo puedo ahorrar dinero?" is refused as out of scope); that needs a new split and a new report.
- Rename or drop "Pix", since the bank operates in MX, CO and AR.
- Remove the old `/app/*` frontend routes.

## Risks

- **Model quota:** the router's quota for `gpt-oss-120b` and `claude-sonnet-4-6` resets on **October 5**, the deadline day. Don't plan the final eval on it.
- **Not verified in this audit:** the slides, the video, and the dataset's terms of use.
