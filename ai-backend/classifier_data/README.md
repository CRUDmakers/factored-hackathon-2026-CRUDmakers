# Route-classifier data

| File | What |
|---|---|
| `templates.yaml` | **Source of truth.** Template families: one request, paraphrased in Spanish and Portuguese. |
| `utterances.csv` | Generated: `python -m ai_backend.classifier.dataset`. Columns `text, lang, route, intent, template_id, author`. |
| `split.json` | The train/validation/test split by family, **frozen before any tuning** (`python -m ai_backend.classifier.split`). It records a hash of `utterances.csv`; training refuses a changed dataset. |
| `report.md`, `report.json` | Results of `python -m ai_backend.classifier.train` (baseline vs model on the test split, thresholds, errors). |
| `report_v1_embeddings_only.json` | The first run (embeddings only), kept for the record; see the report's history note. |

## Provenance: model-drafted

Every utterance was **drafted by a language model** (`author = model:claude-opus-5-5`, 2026-09-28), not written by the team and not taken from customers. The reasons:

- The dataset has no Portuguese.
- Its call transcripts are two fixed sentences (both balance questions) plus filler phrases, so they can't supply varied training text.

The dataset did shape the content: the human-route topics follow its complaint categories (unrecognised charge, improper fee, service quality, app problems, branch service) and contact reasons (transactional, product, complaint, technical, commercial, retention). The amounts, merchants, product types and account numbers match the fixture.

Treat the results as a measure of the method on this data, not of accuracy on real customer traffic.

## Labels

| Route | Meaning | Examples |
|---|---|---|
| `answer` | A clear request the tools can resolve | balance, payment status, decline reason, statements, conversion, product details, a transfer or bill payment with its details, spending |
| `clarify` | In scope, but the message lacks what it's about | "Quiero hacer una transferencia", "¿Por qué no pasó?", "Olha minha conta" |
| `human` | Needs a person by policy | unrecognised charge, fraud, stolen card, disputes and improper fees, complaints, debt negotiation, cancellations, asking for a person, unresolved follow-ups |
| `out_of_scope` | Not this assistant's job, or not allowed | investments, new credit, limit increases, personal data changes, tech support, small talk, other banks, other customers, prompt injection |

The intents are `balance`, `tx_status`, `decline_reason`, `recent_tx`, `fx`, `product_info`, `transfer`, `bill_payment`, `follow_up`, `spending` and `other`. The intent head is only used for the repeat-contact check.

## Note on `split.json`

`split.json` was rewritten once, after training, only to update the data file's hash: the CSV had been written with CRLF line endings, which git stores as LF. The rows and the family assignment are identical (verified); the split itself was fixed before any tuning.

## Changing the data

Edit `templates.yaml`, then regenerate the CSV. A changed dataset needs a **new split** (`split --force`), and the old test results no longer apply. Say so in the report.
