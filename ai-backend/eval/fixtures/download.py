"""Download the raw Banco LATAM tables the fixture needs from S3 into the repo's `data/`.

`data/` is gitignored and mirrors the S3 layout (see the repo README). Files that already
exist locally are skipped, so the command is cheap to re-run.

    python -m eval.fixtures.download --start 2025-12-20 --end 2026-06-17
"""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"

DIMENSION_TABLES = ("branches", "customers", "products", "daily_exchange_rates")
DAILY_TABLES = ("transactions", "call_center_interactions")


def daily_key(table: str, day: date) -> str:
    return (
        f"data/{table}/year={day:%Y}/month={day:%m}/day={day:%d}/{table}_{day:%Y%m%d}.csv"
    )


def keys_for(start: date, end: date) -> list[str]:
    keys = [f"data/{t}.csv" for t in DIMENSION_TABLES]
    day = start
    while day <= end:
        keys.extend(daily_key(t, day) for t in DAILY_TABLES)
        day += timedelta(days=1)
    return keys


def main() -> None:
    import boto3
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    bucket = os.environ["S3_BUCKET"]
    s3 = boto3.client("s3")

    todo = [k for k in keys_for(args.start, args.end) if not (REPO_ROOT / k).exists()]
    print(f"{len(todo)} files to download into {DATA_DIR}")

    def fetch(key: str) -> None:
        target = REPO_ROOT / key
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".part")
        s3.download_file(bucket, key, str(tmp))
        tmp.rename(target)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(fetch, todo))
    print("done")


if __name__ == "__main__":
    main()
