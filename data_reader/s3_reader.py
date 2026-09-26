from __future__ import annotations

import argparse
import io
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import boto3
import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "data" / "raw"

TABULAR_FORMATS = {".csv", ".tsv", ".txt", ".parquet", ".json", ".jsonl", ".ndjson", ".xlsx", ".xls"}


@dataclass
class S3File:
    key: str
    size: int

    @property
    def extension(self) -> str:
        suffixes = PurePosixPath(self.key).suffixes
        # "file.csv.gz" -> ".csv.gz", so compressed files are grouped by their real format
        if len(suffixes) >= 2 and suffixes[-1] in {".gz", ".zip", ".bz2"}:
            return "".join(suffixes[-2:]).lower()
        return suffixes[-1].lower() if suffixes else "(none)"


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:,.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:,.1f} PB"


class S3DataReader:
    def __init__(self, bucket: str | None = None):
        load_dotenv(PROJECT_ROOT / ".env")
        self.bucket = bucket or os.environ["S3_BUCKET"]
        self.s3 = boto3.client("s3", region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-2"))

    # ---------- discovery ----------

    def list_files(self, prefix: str = "") -> list[S3File]:
        paginator = self.s3.get_paginator("list_objects_v2")
        files = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith("/"):
                    files.append(S3File(obj["Key"], obj["Size"]))
        return files

    def summary(self, prefix: str = "", depth: int = 2) -> None:
        """Print how the bucket is organised: folders, file types, sizes."""
        files = self.list_files(prefix)
        if not files:
            print(f"No files found under '{prefix or '/'}'")
            return

        total = sum(f.size for f in files)
        print(f"Bucket: s3://{self.bucket}/{prefix}")
        print(f"Files:  {len(files):,}   Total size: {human_size(total)}\n")

        by_ext: dict[str, list[S3File]] = defaultdict(list)
        for f in files:
            by_ext[f.extension].append(f)
        print("By file type:")
        for ext, group in sorted(by_ext.items(), key=lambda kv: -sum(f.size for f in kv[1])):
            print(f"  {ext:<14} {len(group):>7,} files  {human_size(sum(f.size for f in group)):>12}")

        by_folder: dict[str, list[S3File]] = defaultdict(list)
        for f in files:
            parts = PurePosixPath(f.key).parts[:-1][:depth]
            by_folder["/".join(parts) or "(root)"].append(f)
        print(f"\nBy folder (depth {depth}):")
        for folder, group in sorted(by_folder.items()):
            example = PurePosixPath(group[0].key).name
            print(f"  {folder:<50} {len(group):>7,} files  {human_size(sum(f.size for f in group)):>12}   e.g. {example}")

    # ---------- reading ----------

    def _open(self, key: str) -> io.BytesIO:
        """Return file contents, using the local cache in ./data/raw when available."""
        local = CACHE_DIR / key
        if local.exists():
            return io.BytesIO(local.read_bytes())
        body = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(body)
        return io.BytesIO(body)

    def read(self, key: str, nrows: int | None = None, **kwargs) -> pd.DataFrame:
        """Load a tabular file into a DataFrame. Extra kwargs go to the pandas reader."""
        ext = S3File(key, 0).extension
        compression = None
        if ext.endswith(".gz"):
            compression, ext = "gzip", ext.removesuffix(".gz")
        elif ext.endswith(".zip"):
            compression, ext = "zip", ext.removesuffix(".zip")

        buf = self._open(key)
        if ext in {".csv", ".txt"}:
            return pd.read_csv(buf, nrows=nrows, compression=compression, sep=kwargs.pop("sep", None), encoding="utf-8-sig",
                               engine="python", **kwargs)
        if ext == ".tsv":
            return pd.read_csv(buf, nrows=nrows, compression=compression, sep="\t", encoding="utf-8-sig", **kwargs)
        if ext == ".parquet":
            df = pd.read_parquet(buf, **kwargs)
            return df.head(nrows) if nrows else df
        if ext in {".jsonl", ".ndjson"}:
            return pd.read_json(buf, lines=True, nrows=nrows, compression=compression, **kwargs)
        if ext == ".json":
            df = pd.read_json(buf, compression=compression, **kwargs)
            return df.head(nrows) if nrows else df
        if ext in {".xlsx", ".xls"}:
            return pd.read_excel(buf, nrows=nrows, **kwargs)
        raise ValueError(f"Don't know how to read '{ext}' files. Use read_raw() to inspect the bytes.")

    def read_raw(self, key: str, num_bytes: int = 2000) -> str:
        """Show the start of any file as text — useful for unknown formats."""
        body = self.s3.get_object(Bucket=self.bucket, Key=key, Range=f"bytes=0-{num_bytes - 1}")["Body"].read()
        return body.decode("utf-8", errors="replace")

    def download(self, prefix: str) -> list[Path]:
        """Copy every file under `prefix` into ./data/raw (skipping ones already there)."""
        paths = []
        for f in self.list_files(prefix):
            local = CACHE_DIR / f.key
            if not local.exists() or local.stat().st_size != f.size:
                local.parent.mkdir(parents=True, exist_ok=True)
                print(f"downloading {f.key} ({human_size(f.size)})")
                self.s3.download_file(self.bucket, f.key, str(local))
            paths.append(local)
        return paths

    # ---------- understanding ----------

    @staticmethod
    def profile(df: pd.DataFrame) -> pd.DataFrame:
        """One row per column: type, null share, unique count, and example values."""
        rows = []
        for col in df.columns:
            s = df[col]
            rows.append({
                "column": col,
                "dtype": str(s.dtype),
                "null_%": round(s.isna().mean() * 100, 1),
                "unique": s.nunique(dropna=True),
                "examples": list(s.dropna().unique()[:3]),
                "min": s.min() if pd.api.types.is_numeric_dtype(s) else None,
                "max": s.max() if pd.api.types.is_numeric_dtype(s) else None,
            })
        return pd.DataFrame(rows).set_index("column")


def _main() -> None:
    parser = argparse.ArgumentParser(description="Explore the datathon S3 bucket")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ls"); p.add_argument("prefix", nargs="?", default="")
    p = sub.add_parser("summary"); p.add_argument("prefix", nargs="?", default=""); p.add_argument("--depth", type=int, default=2)
    p = sub.add_parser("peek"); p.add_argument("key"); p.add_argument("-n", type=int, default=10)
    p = sub.add_parser("profile"); p.add_argument("key"); p.add_argument("-n", type=int, default=None,
                                                                       help="only profile the first N rows")
    p = sub.add_parser("raw"); p.add_argument("key"); p.add_argument("--bytes", type=int, default=2000)
    p = sub.add_parser("download"); p.add_argument("prefix")
    args = parser.parse_args()

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    reader = S3DataReader()

    if args.cmd == "ls":
        for f in reader.list_files(args.prefix):
            print(f"{human_size(f.size):>12}  {f.key}")
    elif args.cmd == "summary":
        reader.summary(args.prefix, args.depth)
    elif args.cmd == "peek":
        df = reader.read(args.key, nrows=args.n)
        print(f"columns ({len(df.columns)}): {list(df.columns)}\n")
        print(df)
    elif args.cmd == "profile":
        df = reader.read(args.key, nrows=args.n)
        print(f"{len(df):,} rows x {len(df.columns)} columns\n")
        print(reader.profile(df).to_string())
    elif args.cmd == "raw":
        print(reader.read_raw(args.key, args.bytes))
    elif args.cmd == "download":
        paths = reader.download(args.prefix)
        print(f"{len(paths)} files in {CACHE_DIR}")


if __name__ == "__main__":
    _main()
