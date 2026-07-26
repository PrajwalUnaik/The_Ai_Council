"""Fetch a stratified MMLU-Pro subset and write it as a benchmark JSONL file.

Downloads the test-split parquet file straight from the HuggingFace hub
(public, no auth), caches the raw test split locally, then samples N items
per category with a fixed seed so the subset is reproducible.

Usage (pyarrow is only needed for the first, uncached download):
    uv run --with pyarrow python benchmarks/fetch_mmlu_pro.py --per-category 30
    uv run --with pyarrow python benchmarks/fetch_mmlu_pro.py --total 350

Output item format (one JSON object per line):
    {"item_id": "mmlu_pro_<question_id>", "domain": "<category>",
     "question": "...", "options": ["...", ...], "answer": "C"}
"""

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import httpx

PARQUET_URL = (
    "https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro/resolve/main/"
    "data/test-00000-of-00001.parquet"
)
CACHE_FILE = Path(__file__).parent / "data" / "mmlu_pro_test_raw.jsonl"


def download_test_split(cache_file: Path) -> list:
    """Download the MMLU-Pro test split (parquet) and cache it as JSONL."""
    if cache_file.exists():
        rows = [json.loads(line) for line in cache_file.read_text().splitlines() if line.strip()]
        print(f"Using cached raw split: {cache_file} ({len(rows)} rows)")
        return rows

    try:
        import pyarrow.parquet as pq
    except ImportError:
        sys.exit("pyarrow is required for the first download — run with: "
                 "uv run --with pyarrow python benchmarks/fetch_mmlu_pro.py ...")

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    parquet_path = cache_file.with_suffix(".parquet")
    print(f"Downloading {PARQUET_URL}")
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        resp = client.get(PARQUET_URL)
        resp.raise_for_status()
        parquet_path.write_bytes(resp.content)

    rows = pq.read_table(parquet_path).to_pylist()
    for row in rows:
        options = row.get("options")
        if options is not None and not isinstance(options, list):
            row["options"] = list(options)
    with cache_file.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    parquet_path.unlink()
    print(f"Cached raw split to {cache_file} ({len(rows)} rows)")
    return rows


def stratified_sample(rows: list, per_category: int, seed: int) -> list:
    by_category = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    rng = random.Random(seed)
    sample = []
    for category in sorted(by_category):
        pool = by_category[category]
        k = min(per_category, len(pool))
        sample.extend(rng.sample(pool, k))
    return sample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-category", type=int, default=None,
                        help="Items to sample per category (14 categories)")
    parser.add_argument("--total", type=int, default=None,
                        help="Approximate total items (divided evenly across categories)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    rows = download_test_split(CACHE_FILE)
    categories = sorted({r["category"] for r in rows})
    print(f"Categories ({len(categories)}): {', '.join(categories)}")

    if args.per_category is None and args.total is None:
        parser.error("Specify --per-category or --total")
    per_category = args.per_category or max(1, round(args.total / len(categories)))

    sample = stratified_sample(rows, per_category, args.seed)
    out = args.out or Path(__file__).parent / "data" / f"mmlu_pro_{len(sample)}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for row in sample:
            f.write(json.dumps({
                "item_id": f"mmlu_pro_{row['question_id']}",
                "domain": row["category"],
                "question": row["question"],
                "options": row["options"],
                "answer": row["answer"],
            }) + "\n")
    print(f"Wrote {len(sample)} items ({per_category}/category, seed={args.seed}) to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
