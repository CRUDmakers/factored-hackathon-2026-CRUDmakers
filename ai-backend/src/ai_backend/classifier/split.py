"""Freeze the train/validation/test split, by template family, before any tuning (SPEC §10).

    python -m ai_backend.classifier.split     # once; writes classifier_data/split.json

Families (paraphrases and their translations) never cross splits. Routes are stratified so
every split has each route in roughly the dataset's proportions. The file records a hash of
utterances.csv; training refuses a dataset that no longer matches it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sklearn.model_selection import StratifiedGroupKFold

from ai_backend.classifier.dataset import DATA_DIR, Utterance, read_csv

SPLIT_FILE = DATA_DIR / "split.json"
SEED = 42


class SplitError(Exception):
    pass


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_split(rows: list[Utterance], seed: int = SEED) -> dict[str, list[str]]:
    """About 60% train, 20% validation, 20% test of the rows, whole families only."""
    routes = np.array([r.route for r in rows])
    groups = np.array([r.template_id for r in rows])
    index = np.arange(len(rows))

    outer = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    rest, test = next(outer.split(index, routes, groups))
    inner = StratifiedGroupKFold(n_splits=4, shuffle=True, random_state=seed)
    train, validation = next(inner.split(rest, routes[rest], groups[rest]))
    train, validation = rest[train], rest[validation]
    return {
        name: sorted({groups[i] for i in part})
        for name, part in (("train", train), ("validation", validation), ("test", test))
    }


def freeze(csv_path: Path, out: Path = SPLIT_FILE, force: bool = False) -> dict:
    if out.exists() and not force:
        raise SplitError(f"{out} exists: the split is frozen (use --force only for a new dataset)")
    split = make_split(read_csv(csv_path))
    record = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "seed": SEED,
        "method": "StratifiedGroupKFold by template_id, stratified by route",
        "utterances_sha256": file_hash(csv_path),
        **split,
    }
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def load(csv_path: Path, path: Path = SPLIT_FILE) -> dict[str, list[Utterance]]:
    """The frozen split, checked against the dataset it was made for."""
    if not path.exists():
        raise SplitError(f"{path} missing: run `python -m ai_backend.classifier.split` first")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["utterances_sha256"] != file_hash(csv_path):
        raise SplitError(
            f"{csv_path} changed since the split was frozen; a changed dataset needs a new, "
            "reported split (and the old test results no longer apply)"
        )
    rows = read_csv(csv_path)
    parts = {name: set(record[name]) for name in ("train", "validation", "test")}
    if (
        parts["train"] & parts["test"]
        or parts["validation"] & parts["test"]
        or (parts["train"] & parts["validation"])
    ):
        raise SplitError("a template family is in more than one split")
    return {name: [r for r in rows if r.template_id in ids] for name, ids in parts.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    record = freeze(DATA_DIR / "utterances.csv", force=args.force)
    split = load(DATA_DIR / "utterances.csv")
    for name, rows in split.items():
        routes = {r: sum(u.route == r for u in rows) for r in sorted({u.route for u in rows})}
        pt = sum(u.lang == "pt" for u in rows) / len(rows)
        print(f"{name:10} {len(record[name]):3} families {len(rows):3} rows  pt={pt:.0%}  {routes}")


if __name__ == "__main__":
    main()
