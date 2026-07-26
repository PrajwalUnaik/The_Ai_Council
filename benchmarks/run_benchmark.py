"""RQ1 benchmark harness: batch-run the council over a benchmark file.

For each item in a benchmark JSONL file, POSTs the question to the backend's
/api/ask endpoint (execution_mode=full: stage1 responses -> stage2 peer
rankings -> stage3 chairman synthesis), grades the chairman's answer against
the key, and appends one row per item to the analysis outputs:

  results.jsonl  - full record per item (agreement block, per-member answers,
                   conversation_id, cost report) for archival/re-analysis
  results.csv    - tidy analysis table, one row per item

Re-running with the same --out directory resumes: items already present in
results.jsonl are skipped, so failures or interruptions are cheap.

Usage:
    # backend must be running on localhost:8001
    uv run python benchmarks/run_benchmark.py benchmarks/data/mmlu_pro_350.jsonl \
        --out benchmarks/results/pilot \
        --models openrouter:z-ai/glm-4.7 openrouter:openai/o3-mini \
                 openrouter:mistralai/mistral-large-2407 \
        --chairman openrouter:openai/gpt-5.1-chat \
        --limit 5

Omitting --models/--chairman uses the backend's saved council settings.
Hold the model set constant across the whole run (internal validity).
"""

import argparse
import asyncio
import csv
import json
import re
import string
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_BACKEND = "http://localhost:8001"
ANSWER_LINE = 'End your response with a final line in exactly this format: "Final Answer: <letter>"'

CSV_COLUMNS = [
    "item_id", "domain",
    "kendalls_w", "mean_pairwise_tau", "top1_agreement", "top1_entropy",
    "council_state", "n_rankers", "n_complete_rankings",
    "extracted_answer", "correct_answer", "correct",
    "top1_model", "top1_model_correct",
    "n_members_correct", "n_members",
    "total_cost_usd", "elapsed_s", "conversation_id", "error",
]


def build_prompt(item: Dict[str, Any]) -> str:
    letters = string.ascii_uppercase
    options = "\n".join(
        f"{letters[i]}. {opt}" for i, opt in enumerate(item["options"])
    )
    return (
        "Answer the following multiple-choice question.\n\n"
        f"Question: {item['question']}\n\n"
        f"Options:\n{options}\n\n"
        f"Think through the problem, then commit to one option. {ANSWER_LINE}"
    )


def extract_answer(text: Optional[str], n_options: int) -> Optional[str]:
    """Pull the chosen option letter out of a model response."""
    if not text:
        return None
    valid = set(string.ascii_uppercase[:n_options])
    patterns = [
        r"final answer\s*[:\-]?\s*\**\s*\(?([A-Z])\)?",
        r"answer is\s*\**\s*\(?([A-Z])\)?",
        r"answer\s*[:\-]\s*\**\s*\(?([A-Z])\)?",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, flags=re.IGNORECASE)
        matches = [m.upper() for m in matches if m.upper() in valid]
        if matches:
            return matches[-1]  # last occurrence wins (models often restate)
    return None


def load_benchmark(path: Path) -> List[Dict[str, Any]]:
    items = []
    with path.open() as f:
        for n, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            for field in ("item_id", "question", "options", "answer"):
                if field not in item:
                    raise ValueError(f"{path}:{n} missing field {field!r}")
            items.append(item)
    return items


def load_done_ids(results_jsonl: Path) -> set:
    done = set()
    if results_jsonl.exists():
        with results_jsonl.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if not record.get("error"):
                    done.add(record["item_id"])
    return done


async def run_item(
    client: httpx.AsyncClient,
    item: Dict[str, Any],
    args: argparse.Namespace,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "content": build_prompt(item),
        "execution_mode": "full",
    }
    if args.models:
        payload["models"] = args.models
    if args.chairman:
        payload["chairman_model"] = args.chairman

    started = time.monotonic()
    last_error = None
    for attempt in range(1, args.retries + 1):
        try:
            resp = await client.post(f"{args.backend}/api/ask", json=payload)
            resp.raise_for_status()
            data = resp.json()
            break
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < args.retries:
                await asyncio.sleep(5 * attempt)
    else:
        return {"item_id": item["item_id"], "domain": item.get("domain"),
                "error": last_error, "elapsed_s": round(time.monotonic() - started, 1)}

    elapsed = round(time.monotonic() - started, 1)
    n_options = len(item["options"])
    agreement = data.get("agreement") or {}

    # Grade the chairman's synthesized answer (primary DV)
    extracted = extract_answer(data.get("response"), n_options)
    correct = (extracted == item["answer"]) if extracted else False

    # Grade each council member's stage1 response
    members = []
    for r in data.get("responses") or []:
        member_answer = extract_answer(r.get("response"), n_options)
        members.append({
            "model": r.get("model"),
            "answer": member_answer,
            "correct": member_answer == item["answer"] if member_answer else False,
            "error": r.get("error"),
        })

    # Was the council's top-voted response correct?
    top1_model = agreement.get("top1_model")
    top1_model_correct = next(
        (m["correct"] for m in members if m["model"] == top1_model), None
    )

    cost_report = data.get("cost_report") or {}

    return {
        "item_id": item["item_id"],
        "domain": item.get("domain"),
        "correct_answer": item["answer"],
        "extracted_answer": extracted,
        "correct": correct,
        "agreement": agreement,
        "members": members,
        "top1_model": top1_model,
        "top1_model_correct": top1_model_correct,
        "chairman_response": data.get("response"),
        "chairman_model": data.get("chairman_model"),
        "aggregate_rankings": data.get("aggregate_rankings"),
        "conversation_id": data.get("conversation_id"),
        "total_cost_usd": cost_report.get("total_cost"),
        "cost_report": cost_report,
        "elapsed_s": elapsed,
        "error": None,
    }


def to_csv_row(record: Dict[str, Any]) -> Dict[str, Any]:
    agreement = record.get("agreement") or {}
    members = record.get("members") or []
    return {
        "item_id": record.get("item_id"),
        "domain": record.get("domain"),
        "kendalls_w": agreement.get("kendalls_w"),
        "mean_pairwise_tau": agreement.get("mean_pairwise_tau"),
        "top1_agreement": agreement.get("top1_agreement"),
        "top1_entropy": agreement.get("top1_entropy"),
        "council_state": agreement.get("council_state"),
        "n_rankers": agreement.get("n_rankers"),
        "n_complete_rankings": agreement.get("n_complete_rankings"),
        "extracted_answer": record.get("extracted_answer"),
        "correct_answer": record.get("correct_answer"),
        "correct": record.get("correct"),
        "top1_model": record.get("top1_model"),
        "top1_model_correct": record.get("top1_model_correct"),
        "n_members_correct": sum(1 for m in members if m.get("correct")),
        "n_members": len(members),
        "total_cost_usd": record.get("total_cost_usd"),
        "elapsed_s": record.get("elapsed_s"),
        "conversation_id": record.get("conversation_id"),
        "error": record.get("error"),
    }


def rewrite_csv(results_jsonl: Path, results_csv: Path) -> None:
    """Regenerate the CSV from the JSONL so resume never duplicates rows."""
    records = []
    with results_jsonl.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    with results_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for record in records:
            writer.writerow(to_csv_row(record))


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("benchmark", type=Path, help="Benchmark JSONL file")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory (results.jsonl / results.csv)")
    parser.add_argument("--models", nargs="+", default=None,
                        help="Fixed council model ids (default: backend settings)")
    parser.add_argument("--chairman", default=None,
                        help="Chairman model id (default: backend settings)")
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--limit", type=int, default=None,
                        help="Run at most N pending items (pilot runs)")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Parallel items in flight (default 1)")
    parser.add_argument("--timeout", type=float, default=600,
                        help="Per-request timeout in seconds")
    parser.add_argument("--retries", type=int, default=3)
    args = parser.parse_args()

    items = load_benchmark(args.benchmark)
    args.out.mkdir(parents=True, exist_ok=True)
    results_jsonl = args.out / "results.jsonl"
    results_csv = args.out / "results.csv"

    done = load_done_ids(results_jsonl)
    pending = [i for i in items if i["item_id"] not in done]
    if args.limit is not None:
        pending = pending[: args.limit]
    print(f"{len(items)} items in benchmark, {len(done)} already done, "
          f"{len(pending)} to run (concurrency={args.concurrency})")
    if not pending:
        rewrite_csv(results_jsonl, results_csv)
        return 0

    # Save the run configuration alongside results for provenance
    config_path = args.out / "run_config.json"
    config_path.write_text(json.dumps({
        "benchmark": str(args.benchmark),
        "models": args.models,
        "chairman": args.chairman,
        "backend": args.backend,
    }, indent=2) + "\n")

    semaphore = asyncio.Semaphore(args.concurrency)
    write_lock = asyncio.Lock()
    stats = {"done": 0, "correct": 0, "errors": 0, "cost": 0.0}

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        async def worker(item: Dict[str, Any]) -> None:
            async with semaphore:
                record = await run_item(client, item, args)
            async with write_lock:
                with results_jsonl.open("a") as f:
                    f.write(json.dumps(record) + "\n")
                stats["done"] += 1
                if record.get("error"):
                    stats["errors"] += 1
                    print(f"[{stats['done']}/{len(pending)}] {record['item_id']} "
                          f"ERROR: {record['error']}")
                else:
                    stats["correct"] += bool(record.get("correct"))
                    stats["cost"] += record.get("total_cost_usd") or 0.0
                    agreement = record.get("agreement") or {}
                    print(f"[{stats['done']}/{len(pending)}] {record['item_id']} "
                          f"answer={record.get('extracted_answer')} "
                          f"correct={record.get('correct')} "
                          f"state={agreement.get('council_state')} "
                          f"W={agreement.get('kendalls_w')} "
                          f"({record.get('elapsed_s')}s, "
                          f"${record.get('total_cost_usd') or 0:.4f})")

        await asyncio.gather(*(worker(item) for item in pending))

    rewrite_csv(results_jsonl, results_csv)
    graded = stats["done"] - stats["errors"]
    accuracy = (stats["correct"] / graded) if graded else 0.0
    print(f"\nRun complete: {graded} graded, {stats['errors']} errors, "
          f"accuracy={accuracy:.3f}, total cost=${stats['cost']:.2f}")
    print(f"Results: {results_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
