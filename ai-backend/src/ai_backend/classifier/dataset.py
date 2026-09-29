"""The route-classifier dataset (SPEC §10): template families → `utterances.csv`.

python -m ai_backend.classifier.dataset        # validate templates.yaml, write utterances.csv
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

DATA_DIR = Path("classifier_data")
ROUTES = ("answer", "clarify", "human", "out_of_scope")
INTENTS = (
    "balance",
    "tx_status",
    "decline_reason",
    "recent_tx",
    "fx",
    "product_info",
    "transfer",
    "bill_payment",
    "follow_up",
    "spending",
    "other",
)
AUTHOR = "model:claude-opus-5-5"
COLUMNS = ["text", "lang", "route", "intent", "template_id", "author"]
MIN_ROWS = 600
MIN_PT_SHARE = 0.40


@dataclass(frozen=True)
class Utterance:
    text: str
    lang: str
    route: str
    intent: str
    template_id: str
    author: str


class DatasetError(Exception):
    pass


def from_templates(path: Path) -> list[Utterance]:
    families = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows: list[Utterance] = []
    seen_ids: set[str] = set()
    for family in families:
        tid = family["id"]
        if tid in seen_ids:
            raise DatasetError(f"duplicate template id {tid}")
        seen_ids.add(tid)
        if family["route"] not in ROUTES or family["intent"] not in INTENTS:
            raise DatasetError(f"{tid}: unknown route or intent")
        for lang in ("es", "pt"):
            for text in family.get(lang, []):
                rows.append(
                    Utterance(text.strip(), lang, family["route"], family["intent"], tid, AUTHOR)
                )
    check(rows)
    return rows


def check(rows: list[Utterance]) -> None:
    texts = Counter(r.text.casefold() for r in rows)
    duplicates = [t for t, n in texts.items() if n > 1]
    if duplicates:
        raise DatasetError(f"duplicate texts: {duplicates[:5]}")
    if len(rows) < MIN_ROWS:
        raise DatasetError(f"{len(rows)} rows; at least {MIN_ROWS} needed")
    pt_share = sum(r.lang == "pt" for r in rows) / len(rows)
    if pt_share < MIN_PT_SHARE:
        raise DatasetError(f"{pt_share:.0%} Portuguese; at least {MIN_PT_SHARE:.0%} needed")
    missing = set(ROUTES) - {r.route for r in rows}
    if missing:
        raise DatasetError(f"routes without examples: {missing}")


def write_csv(rows: list[Utterance], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        # LF, not csv's default CRLF: git stores LF, and split.json pins this file's hash.
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(COLUMNS)
        writer.writerows([[getattr(r, c) for c in COLUMNS] for r in rows])


def read_csv(path: Path) -> list[Utterance]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != COLUMNS:
            raise DatasetError(f"{path}: expected columns {COLUMNS}")
        rows = [Utterance(**row) for row in reader]
    check(rows)
    return rows


def main() -> None:
    rows = from_templates(DATA_DIR / "templates.yaml")
    write_csv(rows, DATA_DIR / "utterances.csv")
    routes = Counter(r.route for r in rows)
    langs = Counter(r.lang for r in rows)
    families = len({r.template_id for r in rows})
    print(f"{len(rows)} utterances in {families} families; {dict(langs)}; {dict(routes)}")


if __name__ == "__main__":
    main()
