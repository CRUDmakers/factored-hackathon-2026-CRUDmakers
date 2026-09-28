"""The trained model as the service loads it (skipped until `classifier.train` has run)."""

from pathlib import Path

import pytest

from ai_backend.classifier.predict import RouteClassifier
from ai_backend.config import load_policy_config

ROOT = Path(__file__).parents[2]
MODEL = ROOT / "models" / "route_classifier.joblib"

pytestmark = pytest.mark.skipif(
    not MODEL.exists(), reason="run python -m ai_backend.classifier.train"
)


@pytest.fixture(scope="module")
def classifier():
    import os

    cwd = os.getcwd()
    os.chdir(ROOT)  # the artifact stores the embedding cache path relative to ai-backend/
    try:
        yield RouteClassifier.load(MODEL)
    finally:
        os.chdir(cwd)


def test_clear_cases_route_as_expected(classifier):
    t = load_policy_config(ROOT / "config" / "policy.yaml").routing.resolve(
        classifier.meta["thresholds"]
    )
    tau = t["human_confidence_tau"]
    person = classifier.predict("Quero falar com um atendente humano agora", tau)
    assert person.route == "human" and person.p_human >= t["human_direct_tau"]
    invest = classifier.predict("¿Me recomiendas invertir en acciones?", tau)
    assert invest.route == "out_of_scope"
    balance = classifier.predict("¿Cuánto dinero tengo en mi cuenta de ahorro?", tau)
    assert balance.p_human < t["human_direct_tau"] and balance.intent == "balance"


def test_artifact_records_its_provenance(classifier):
    meta = classifier.meta
    assert meta["features"] in ("embedding", "tfidf", "both")
    assert len(meta["utterances_sha256"]) == 64 and len(meta["split_sha256"]) == 64
