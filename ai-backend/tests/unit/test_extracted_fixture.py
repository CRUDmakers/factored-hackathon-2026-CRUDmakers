"""M0 acceptance on the real extracted fixture (skipped when it hasn't been built locally)."""

import csv
from pathlib import Path

import pytest

from ai_backend.bank.fixture import load_fixture

FIXTURE = Path(__file__).parents[2] / "eval" / "fixtures" / "data"
PERSONAL = {
    "document_number", "document_type", "first_name", "last_name", "email", "mobile_phone",
    "landline_phone", "address", "postal_code", "date_of_birth", "estimated_monthly_income",
}
DEMO_CUSTOMERS = {
    "CLI-25NDK326VNE4", "CLI-EF70WD91TBJQ", "CLI-QITAGXCUR83U", "CLI-7T6B34S2O9UL",
    "CLI-CSV0VF8IA55L",
}

pytestmark = pytest.mark.skipif(
    not (FIXTURE / "manifest.json").exists(), reason="run `python -m eval.fixtures.extract`"
)


def test_fixture_covers_what_the_scenarios_need():
    fx = load_fixture(FIXTURE)
    txs = list(fx.transactions.values())
    with_tx = {t.customer_id for t in txs}
    assert len(with_tx) >= 50
    assert with_tx == set(fx.customers)
    assert set(fx.customers) >= DEMO_CUSTOMERS
    assert {t.status for t in txs} == {"Approved", "Declined", "Pending", "Reversed"}
    assert {t.currency for t in txs} == {"USD", "COP", "ARS"}
    assert {t.response_code for t in txs if t.status == "Declined"} >= {"51", "14", "05", "54"}
    product_types = {p.product_type for p in fx.products.values()}
    assert product_types >= {
        "Cuenta Ahorro", "Cuenta Corriente", "Tarjeta Crédito", "Tarjeta Débito",
        "Préstamo Personal",
    }
    assert {p.status for p in fx.products.values()} >= {"Active", "Blocked", "Suspended"}
    assert any((p.days_past_due or 0) > 0 for p in fx.products.values())
    assert any(t.is_fraud for t in txs)
    # Every transaction date has a COP→USD quote on or before it.
    first_quote = fx.rates[("COP", "USD")][0].date
    assert all(t.transaction_date.date() >= first_quote for t in txs)


def test_fixture_has_no_personal_data():
    for path in FIXTURE.glob("*.csv"):
        if path.name == "branches.csv":
            continue  # a branch's address is public, not personal
        with path.open(encoding="utf-8") as fh:
            header = set(next(csv.reader(fh)))
        assert not (header & PERSONAL), path.name


def test_card_numbers_keep_only_last_4_digits():
    fx = load_fixture(FIXTURE)
    cards = [p for p in fx.products.values() if p.product_type.startswith("Tarjeta")]
    assert cards and all(p.product_number is None or len(p.product_number) <= 4 for p in cards)
