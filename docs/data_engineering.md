# Data engineering: ETL, data contract, lineage and quality

The bank API (`backend/`) serves the assistant from Postgres. The data gets there through the ETL in
`backend/src/etl/load.ts`, which loads the organizer's CSVs (`data/`) into Postgres.

```
data/*.csv (4 snapshot tables)                         ┌─ header check (fails the run)
data/transactions/year=/month=/day=/*.csv (daily)  ──► │  COPY → temp staging table (all text)
                                                       │  per-row checks: type + domain rules + partition
                                                       │  INSERT valid rows → target table
                                                       └─ etl_files: file, sha256, rows read/loaded/rejected, reasons
```

## Data contract

Each file is checked against a contract. The checks run in SQL (`pg_input_is_valid`), so one bad value
can't abort the load.

| Level | Rule | On violation |
|---|---|---|
| File | Header must match the expected columns exactly, in order (the target table's columns; 22 columns for transactions) | Run stops with the expected and received headers |
| File | Transaction files must sit in `transactions/year=YYYY/month=MM/day=DD/` | Run stops |
| File | CSV must be well formed (no extra columns, no unclosed quotes) | That file rolls back. Nothing partial is loaded and no lineage is written |
| Row | Every value must parse as its column's Postgres type (`timestamp`, `numeric(20,2)`, `boolean`, ...), and required columns can't be empty | Row rejected, reason = column name |
| Row | `currency` ∈ USD, MXN, COP, ARS (transactions, products, exchange rates) | Row rejected |
| Row | `transaction_status` ∈ Approved, Declined, Pending, Reversed | Row rejected |
| Row | `process_date` = the file's partition day | Row rejected, reason `partition` |
| Row | Primary key not already loaded | Row rejected, reason `duplicate_key` (the first copy wins) |
| Row | `transaction_country = 'Mexico'` → `'México'` | Normalized, not rejected |

**The partition key is `process_date`, not `transaction_date`.** Every row matches its partition on
`process_date`. 25% of rows (183,170) have a `transaction_date` that falls on the next day: late-night
transactions processed under the previous day.

## Lineage

- **Per file:** the `etl_files` table is the load manifest. It stores the relative path, target table,
  partition date, sha256, rows read/loaded/rejected, rejection reasons as JSON (e.g.
  `{"currency": 1, "duplicate_key": 1}`) and load time.
- **Per row:** every historical transaction stores its source file in `transactions.source_file`.
  Simulated transactions (from payments made through the API) have `source_file = NULL` and
  `origin = 'simulated'`.

## Incremental load and freshness

- A file is loaded only if its sha256 differs from the one in `etl_files`. Unchanged files are skipped.
- **New or re-delivered transaction partition:** the old rows *from that file* are deleted and the new
  version is inserted, in one database transaction. Other partitions and simulated transactions aren't
  touched.
- **Changed snapshot table** (customers, products, branches, exchange rates): the table is replaced.
  These files are full snapshots.
- `--force`, or an empty manifest (first load, or a database loaded before lineage existed), triggers a
  full reload. A full reload also clears simulated operations and scheduled payments.
- **Freshness policy:** partition D must be loaded by D+1. The run prints a warning when the latest
  partition is older than that. The organizer's dataset ends on 2026-06-17, so today it always warns.
  That is the expected result for a historical dataset.

The ETL is idempotent: `docker compose run --rm etl` can run on a daily schedule, and a run with no
changes does nothing.

## Measured on the dataset

These are the 180 daily partitions in our local copy of `data/` (2025-12-20 → 2026-06-17), on Postgres 17
(laptop):

| | Files | Rows read | Loaded | Rejected |
|---|---:|---:|---:|---:|
| transactions | 180 | 732,908 | 732,908 | 0 |
| products | 1 | 400,000 | 400,000 | 0 |
| customers | 1 | 150,000 | 150,000 | 0 |
| daily_exchange_rates | 1 | 13,164 | 13,164 | 0 |
| branches | 1 | 350 | 350 | 0 |

- Full load: **21 s**. Re-run with no changes: **1.2 s** (184 files skipped).
- No missing partitions between the first and the last.
- No row breaks the contract. The dataset's problems are referential and semantic, so they are reported
  as warnings instead of being rejected. The API already handles each one:

| Warning | Rows | How the system handles it |
|---|---:|---|
| `transaction_date` on a different day than the partition | 183,170 | Expected (see above). Reports filter on `transaction_date` |
| Customers whose `registration_branch_id` is not in branches | 149,995 | Field is not used by the API |
| Transactions in countries where the bank doesn't operate (USA, Spain, Brazil) | 20,108 | Real foreign card use. Transfers only go to MX/CO/AR |
| Non-USD transactions with no `amount_usd` | 16,492 | API converts with the exchange rate on the transaction day |
| `Mexico` spelled without the accent | 6,641 | Normalized to `México` on load |
| Customers with no e-mail | 2,984 | That customer can't receive Pix by e-mail |
| Branches with invalid coordinates (≈ 0,0) | 167 | API hides coordinates within 1° of 0,0 |
| Account numbers shared by two accounts | 2 | Transfers to that number are declined as ambiguous |

Reproduce: `psql "$DATABASE_URL" -f backend/scripts/quality_report.sql` (read-only).

## Test fixtures (synthetic, made by the team)

Neither fixture comes from the organizer's dataset. Both were hand-written for the tests.

- `backend/tests/fixtures/data/`: a mini bank with 4 customers, 18 products, 24 exchange rates and 18
  transactions in 3 daily partitions. Every value is chosen to exercise a test case: blocked, expired and
  closed products, a card with no limit, an orphan product, an ambiguous account number, rates on 2 days,
  the `Mexico` spelling. The API test suite (174 tests, 100% line and branch coverage) runs on it.
- `backend/tests/fixtures/incremental/`: a labeled **second delivery** (see its README). It re-delivers one
  partition with a correction and a deleted row, and adds a new partition with 2 good rows plus one bad row
  for each rejection reason. `tests/etl.test.ts` checks that only those 2 files reload, the right rows are
  rejected with the right reasons, simulated operations survive, and a second run changes nothing.

Run: `cd backend && npm test` (needs Postgres, see `backend/README.md`).

## Known limits

- Rejected rows are counted by reason but not stored. To debug, re-run the file's checks on the CSV.
- A partition file deleted from the source is not deleted from the database.
- One row can break several rules, so the reason counts can add up to more than `rows_rejected`.
- Replacing the products snapshot resets balances changed by simulated payments. This is by design: the
  new snapshot is the bank's state of record.
