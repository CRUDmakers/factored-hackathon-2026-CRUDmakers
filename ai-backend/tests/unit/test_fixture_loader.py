import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ai_backend.bank.fixture import FixtureError, load_fixture
from tests.conftest import TEST_FIXTURE


def test_loads_test_fixture():
    fx = load_fixture(TEST_FIXTURE)
    assert len(fx.customers) == 3
    assert len(fx.products) == 10
    assert len(fx.transactions) == 8
    assert fx.customers["CLI-AAAA1111"].tags == {"country_México", "fraud_score_high"}
    assert [q.date for q in fx.rates[("COP", "USD")]] == [date(2026, 6, 12), date(2026, 6, 15)]
    assert fx.as_of.tzinfo is not None


def test_parsing():
    fx = load_fixture(TEST_FIXTURE)
    assert fx.transactions["TRX-A5"].response_code is None
    assert fx.transactions["TRX-A5"].country == "Mexico"  # raw, as Node loads it
    assert fx.transactions["TRX-A4"].is_fraud is True
    assert fx.transactions["TRX-A3"].fraud_score is None
    assert fx.transactions["TRX-A1"].transaction_date.tzinfo is not None
    assert fx.products["PRD-BLOAN"].days_past_due == Decimal("30.0")
    assert fx.products["PRD-ACC"].product_number == "4321"
    assert fx.branches["SUC-TEST0001"].address == "Avenida Insurgentes 760, Centro"


def test_missing_directory(tmp_path: Path):
    with pytest.raises(FixtureError, match="eval.fixtures.extract"):
        load_fixture(tmp_path)


def test_missing_table(tmp_path: Path):
    shutil.copytree(TEST_FIXTURE, tmp_path, dirs_exist_ok=True)
    (tmp_path / "branches.csv").unlink()
    with pytest.raises(FixtureError, match="missing"):
        load_fixture(tmp_path)


def test_wrong_columns(tmp_path: Path):
    shutil.copytree(TEST_FIXTURE, tmp_path, dirs_exist_ok=True)
    (tmp_path / "branches.csv").write_text("branch_id,name\nSUC-1,x\n")
    with pytest.raises(FixtureError, match="expected columns"):
        load_fixture(tmp_path)


@pytest.mark.parametrize(
    ("old", "new"),
    [(",Approved,00,False,12.5", ",Weird,00,False,12.5"), (",False,12.5", ",maybe,12.5")],
)
def test_bad_row_names_the_table(tmp_path: Path, old: str, new: str):
    shutil.copytree(TEST_FIXTURE, tmp_path, dirs_exist_ok=True)
    path = tmp_path / "transactions.csv"
    path.write_text(path.read_text().replace(old, new))
    with pytest.raises(FixtureError, match="transactions.csv"):
        load_fixture(tmp_path)
