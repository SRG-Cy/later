"""Run the 30 test captures through the real pipeline (Gemma extraction + deadline resolver).

    python eval/run.py [--model gemma-4-31b-it] [--concurrency 3]

Failed model calls are retried with backoff, like the Temporal read_item activity.
Writes eval/results/<model>.json and eval/results/<model>.md.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from later.llm import extract_facts  # noqa: E402
from later.resolve import DUBLIN, resolve  # noqa: E402

CAPTURED = datetime(2026, 10, 24, 12, 0, tzinfo=DUBLIN)  # every case is "captured" at noon today
BACKOFF = [5, 10, 20, 40, 60]  # seconds between attempts; 6 attempts in total


async def run_case(case: dict, sem: asyncio.Semaphore) -> dict:
    image = (ROOT / case["image"]).read_bytes() if case.get("image") else None
    row = {"id": case["id"], "input": "photo" if image else "text", "expected_due": case["due"],
           "attempts": 0, "errors": []}
    async with sem:
        start = time.perf_counter()
        facts = None
        for attempt, wait in enumerate([0, *BACKOFF], start=1):
            await asyncio.sleep(wait)
            row["attempts"] = attempt
            t = time.perf_counter()
            try:
                facts = await extract_facts(case.get("text"), image, CAPTURED.date())
                row["call_secs"] = round(time.perf_counter() - t, 1)
                break
            except Exception as e:  # a server error: retry, as Temporal would
                row["errors"].append(type(e).__name__)
        else:
            row["gave_up"] = True
        row["total_secs"] = round(time.perf_counter() - start, 1)
    resolved = resolve(facts, CAPTURED) if facts else None
    due = resolved.due_at.astimezone(DUBLIN).date().isoformat() if resolved else None
    row.update(kind=facts.kind if facts else None, got_due=due,
               evidence=facts.evidence if facts else None)
    row["kind_ok"] = facts is not None and facts.kind in case["kinds"] if case["due"] else True
    row["due_ok"] = due == case["due"]
    row["due_within_1"] = row["due_ok"] or (
        due is not None and case["due"] is not None
        and abs((date.fromisoformat(due) - date.fromisoformat(case["due"])).days) <= 1)
    print(f"{'OK ' if row['due_ok'] else 'MISS'} {case['id']:22} expected {case['due']} got {due} "
          f"kind={row['kind']} attempts={row['attempts']} {row['total_secs']}s", flush=True)
    return row


def summarise(model: str, rows: list[dict]) -> str:
    n = len(rows)
    calls = [r["call_secs"] for r in rows if "call_secs" in r]
    errors = sum(len(r["errors"]) for r in rows)
    attempts = sum(r["attempts"] for r in rows)
    line = lambda label, k: f"| {label} | {sum(r[k] for r in rows)}/{n} |"
    misses = [r for r in rows if not r["due_ok"]]
    out = [
        f"# Eval: {model}", "",
        f"30 hand-written captures (27 typed, 3 drawn images), captured {CAPTURED:%Y-%m-%d %H:%M} Dublin.", "",
        "| Metric | Result |", "|---|---|",
        line("Due date exactly right", "due_ok"),
        line("Due date within 1 day", "due_within_1"),
        line("Kind right", "kind_ok"),
        f"| Model calls that failed (500 etc.) | {errors}/{attempts} ({errors / attempts:.0%}) |",
        f"| Captures that needed a retry | {sum(1 for r in rows if r['errors'])}/{n} |",
        f"| Captures never read after 6 tries | {sum(1 for r in rows if r.get('gave_up'))}/{n} |",
        f"| Successful call time, median / max | {statistics.median(calls):.0f} s / {max(calls):.0f} s |" if calls else "",
        f"| Time to read incl. retries, median | {statistics.median(r['total_secs'] for r in rows):.0f} s |",
        "", "## Misses", "",
    ]
    out += [f"- `{r['id']}`: expected {r['expected_due']}, got {r['got_due']} (kind {r['kind']}). "
            f"Evidence: {r['evidence']!r}" for r in misses] or ["None."]
    return "\n".join(out) + "\n"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL", "gemma-4-31b-it"))
    ap.add_argument("--concurrency", type=int, default=3)
    args = ap.parse_args()
    os.environ["LLM_MODEL"] = os.environ["LLM_VISION_MODEL"] = args.model
    cases = [json.loads(l) for l in (ROOT / "eval/cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    sem = asyncio.Semaphore(args.concurrency)
    rows = await asyncio.gather(*(run_case(c, sem) for c in cases))
    out = ROOT / "eval/results"
    out.mkdir(exist_ok=True)
    (out / f"{args.model}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    summary = summarise(args.model, rows)
    (out / f"{args.model}.md").write_text(summary, encoding="utf-8")
    print("\n" + summary)


if __name__ == "__main__":
    asyncio.run(main())
