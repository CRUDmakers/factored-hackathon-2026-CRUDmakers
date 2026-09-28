"""Build the offline fixture (`eval/fixtures/data/`) from the raw dataset in the repo's `data/`.

    python -m eval.fixtures.download --start 2025-12-20 --end 2026-06-17
    python -m eval.fixtures.extract

Customers are chosen by stratified, seeded sampling so that the fixture covers every status,
decline code, currency, product type and escalation trigger the scenarios need. The output is
deterministic for a given window, seed and size. The frontend's demo customers are always
included, so the demo and the eval use the same people.

Personal data is dropped: only the columns in `ai_backend.bank.fixture.COLUMNS` are written, and
card numbers keep only their last 4 digits. Account numbers stay, because Node transfers to
another customer by account number.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ai_backend.bank.fixture import COLUMNS, MANIFEST
from eval.fixtures.download import DATA_DIR

OUT_DIR = Path(__file__).resolve().parent / "data"

DEFAULT_START = date(2025, 12, 20)
DEFAULT_END = date(2026, 6, 17)
MIN_TRANSACTIONS = 3
FRAUD_SCORE_HIGH = 40  # same initial value as policy.yaml thresholds.fraud_score_escalate
FOREIGN_COUNTRIES = {"USA", "Spain", "Brazil"}
LOAN_TYPES = {"Préstamo Personal", "Préstamo Hipotecario"}
CARD_TYPES = {"Tarjeta Crédito", "Tarjeta Débito"}

# frontend/src/testCustomers.ts: the 4 demo customers + the suspended one.
DEMO_CUSTOMERS = (
    "CLI-25NDK326VNE4",
    "CLI-EF70WD91TBJQ",
    "CLI-QITAGXCUR83U",
    "CLI-7T6B34S2O9UL",
    "CLI-CSV0VF8IA55L",
)

# tag → minimum number of fixture customers carrying it. Filled in this order.
STRATA: dict[str, int] = {
    "declined_51": 3,
    "declined_14": 2,
    "declined_05": 3,
    "declined_54": 2,
    "declined_no_code": 1,
    "pending": 5,
    "reversed": 5,
    "fraud_score_high": 6,
    "is_fraud": 3,
    "brazil_tx": 3,
    "foreign_tx": 5,
    "product_blocked": 4,
    "product_suspended": 3,
    "past_due": 5,
    "same_merchant_7d": 5,
    "loan_adjustment": 3,
    "credit_card": 10,
    "multi_currency": 3,
    "currency_COP": 12,
    "currency_ARS": 10,
    "segment_Student": 3,
    "segment_Premium": 4,
    "country_México": 15,
    "country_Colombia": 12,
    "country_Argentina": 10,
    "customer_not_active": 2,
}


def read_daily(table: str, start: date, end: date) -> pd.DataFrame:
    frames = []
    day = start
    while day <= end:
        path = (
            DATA_DIR / table / f"year={day:%Y}" / f"month={day:%m}" / f"day={day:%d}"
            / f"{table}_{day:%Y%m%d}.csv"
        )
        if not path.exists():
            raise SystemExit(f"{path} missing: run `python -m eval.fixtures.download` first")
        frames.append(pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False))
        day += timedelta(days=1)
    return pd.concat(frames, ignore_index=True)


def read_dim(table: str) -> pd.DataFrame:
    return pd.read_csv(
        DATA_DIR / f"{table}.csv", dtype=str, encoding="utf-8-sig", keep_default_na=False
    )


def tag_customers(
    tx: pd.DataFrame, products: pd.DataFrame, customers: pd.DataFrame
) -> dict[str, set[str]]:
    """customer_id → tags, for every eligible customer (≥ MIN_TRANSACTIONS in the window, or a
    demo customer)."""
    counts = tx.groupby("customer_id").size()
    eligible = (set(counts[counts >= MIN_TRANSACTIONS].index) | set(DEMO_CUSTOMERS)) & set(
        customers.customer_id
    )
    tags: dict[str, set[str]] = {c: set() for c in eligible}

    def add(tag: str, ids: pd.Series | set[str]) -> None:
        for c in set(ids) & eligible:
            tags[c].add(tag)

    declined = tx[tx.transaction_status == "Declined"]
    for code in ("51", "14", "05", "54"):
        add(f"declined_{code}", declined[declined.response_code == code].customer_id)
    add("declined_no_code", declined[declined.response_code == ""].customer_id)
    add("pending", tx[tx.transaction_status == "Pending"].customer_id)
    add("reversed", tx[tx.transaction_status == "Reversed"].customer_id)
    score = pd.to_numeric(tx.fraud_score, errors="coerce")
    add("fraud_score_high", tx[score >= FRAUD_SCORE_HIGH].customer_id)
    add("is_fraud", tx[tx.is_fraud == "True"].customer_id)
    add("brazil_tx", tx[tx.transaction_country == "Brazil"].customer_id)
    add("foreign_tx", tx[tx.transaction_country.isin(FOREIGN_COUNTRIES)].customer_id)
    for cur in ("COP", "ARS"):
        add(f"currency_{cur}", tx[tx.currency == cur].customer_id)

    add("product_blocked", products[products.product_status == "Blocked"].customer_id)
    add("product_suspended", products[products.product_status == "Suspended"].customer_id)
    dpd = pd.to_numeric(products.days_past_due, errors="coerce")
    add("past_due", products[dpd > 0].customer_id)
    add("credit_card", products[products.product_type == "Tarjeta Crédito"].customer_id)
    cur_per_customer = products.groupby("customer_id").currency.nunique()
    add("multi_currency", cur_per_customer[cur_per_customer > 1].index)

    tx_types = tx.merge(products[["product_id", "product_type"]], on="product_id")
    add(
        "loan_adjustment",
        tx_types[
            (tx_types.transaction_type == "Adjustment") & tx_types.product_type.isin(LOAN_TYPES)
        ].customer_id,
    )

    # Two transactions at the same merchant within 7 days: raw material for ambiguity scenarios.
    m = tx[tx.merchant_name != ""][["customer_id", "merchant_name", "transaction_date"]].copy()
    m["ts"] = pd.to_datetime(m.transaction_date)
    m = m.sort_values(["customer_id", "merchant_name", "ts"])
    gap = m.groupby(["customer_id", "merchant_name"]).ts.diff()
    add("same_merchant_7d", m[gap <= pd.Timedelta(days=7)].customer_id)

    add("demo_customer", set(DEMO_CUSTOMERS))

    info = customers.set_index("customer_id")
    for c in eligible:
        row = info.loc[c]
        tags[c].add(f"segment_{row.segment}")
        tags[c].add(f"country_{row.country}")
        if row.customer_status != "Active":
            tags[c].add("customer_not_active")
    return tags


def select(tags: dict[str, set[str]], n: int, seed: int) -> list[str]:
    rng = np.random.default_rng(seed)
    chosen: list[str] = [c for c in DEMO_CUSTOMERS if c in tags]
    for tag, target in STRATA.items():
        have = sum(tag in tags[c] for c in chosen)
        pool = sorted(c for c, t in tags.items() if tag in t and c not in chosen)
        need = min(target - have, len(pool))
        if need > 0:
            chosen.extend(rng.choice(pool, size=need, replace=False).tolist())
    rest = sorted(set(tags) - set(chosen))
    if len(chosen) < n:
        chosen.extend(rng.choice(rest, size=n - len(chosen), replace=False).tolist())
    return sorted(chosen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--customers", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    # A daily batch runs 06:00 → 06:00, so the last partition ends at 06:00 the next day.
    as_of = datetime.combine(args.end + timedelta(days=1), time(6, 0))

    tx = read_daily("transactions", args.start, args.end)
    products = read_dim("products")
    customers = read_dim("customers")
    branches = read_dim("branches")
    rates = read_dim("daily_exchange_rates")

    tags = tag_customers(tx, products, customers)
    chosen = select(tags, args.customers, args.seed)
    chosen_set = set(chosen)

    out: dict[str, pd.DataFrame] = {}
    cust = customers[customers.customer_id.isin(chosen_set)].copy()
    cust["tags"] = cust.customer_id.map(lambda c: ";".join(sorted(tags[c])))
    out["customers"] = cust
    prods = products[products.customer_id.isin(chosen_set)].copy()
    cards = prods.product_type.isin(CARD_TYPES)
    prods.loc[cards, "product_number"] = prods.loc[cards, "product_number"].str[-4:]
    out["products"] = prods
    out["transactions"] = tx[tx.customer_id.isin(chosen_set)]
    used_branches = set(out["transactions"].branch_id) - {""}
    out["branches"] = branches[branches.branch_id.isin(used_branches)]
    out["exchange_rates"] = rates[
        (rates.date >= args.start.isoformat()) & (rates.date <= args.end.isoformat())
    ]

    args.out.mkdir(parents=True, exist_ok=True)
    for table, frame in out.items():
        cols = COLUMNS[table]
        frame[cols].sort_values(cols[:2]).to_csv(args.out / f"{table}.csv", index=False)

    strata = {tag: sum(tag in tags[c] for c in chosen) for tag in STRATA}
    manifest = {
        "source": "Factored Datathon 2026, Banco LATAM (synthetic data), S3 prefix data/",
        "window": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "as_of": as_of.isoformat(),
        "seed": args.seed,
        "counts": {table: len(frame) for table, frame in out.items()},
        "strata": strata,
        "strata_targets": STRATA,
        "notes": [
            "Personal data (names, documents, contacts, addresses) is excluded; card numbers"
            " keep their last 4 digits; account numbers stay (Node transfers by them).",
            "Values are copied as Node's ETL loads them (e.g. 'Mexico' and 'México' both occur).",
            "Balances are the dataset's current snapshot, not balances at transaction time.",
            "Pending and Reversed transactions also carry non-00 response codes (ARCHITECTURE"
            " §16, R5).",
            f"Always included: the frontend's demo customers {list(DEMO_CUSTOMERS)}.",
        ],
    }
    (args.out / MANIFEST).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    short = {t: (strata[t], STRATA[t]) for t in STRATA if strata[t] < STRATA[t]}
    print(json.dumps(manifest["counts"], indent=2))
    if short:
        print(f"WARNING: strata below target (have, target): {short}")


if __name__ == "__main__":
    main()
