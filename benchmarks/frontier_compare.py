"""Reproducible old-vs-durable frontier regression benchmark.

Usage: python -m benchmarks.frontier_compare --pages 200 --output frontier.json
Metrics are measured on the executing machine; no precomputed speed claims.
"""
import argparse
import json
import platform
import tempfile
import time
from pathlib import Path

from config import Config
from durable_queue import DurableURLQueue
from url_queue import URLQueue


def run_comparison(pages: int = 100) -> dict:
    if not 1 <= pages <= 100000:
        raise ValueError("pages must be between 1 and 100000")
    cases = [(f"https://example.com/page-{i}", i % 3 + 1, i % 3)
             for i in range(pages)]
    data = {}
    with tempfile.TemporaryDirectory() as temporary:
        tmp = Path(temporary)
        for mode in ("legacy", "durable"):
            cfg = Config()
            cfg.storage.base_dir = tmp / mode
            cfg.browser.allowed_domains = ["example.com"]
            cfg.crawl.max_depth = 3
            q = (URLQueue(cfg) if mode == "legacy" else
                 DurableURLQueue(cfg, start_url="https://example.com/",
                                 intent="benchmark"))
            started = time.perf_counter()
            admitted = sum(bool(q.add(url, priority=priority, depth=depth))
                           for url, priority, depth in cases)
            duplicates = sum(not q.add(cases[i][0], priority=1, depth=0)
                             for i in range(min(10, pages)))
            order = []
            while q.has_next():
                item = q.get_next()
                if item is None:
                    break
                order.append(item.url)
                q.mark_processed(item.url, success=True)
            elapsed = time.perf_counter() - started
            if mode == "durable":
                counts = q.counts()
                q.close()
                final_count = counts.get("completed", 0)
            else:
                final_count = len(order)
            data[mode] = {
                "admitted": admitted,
                "duplicates_rejected": duplicates,
                "completed": final_count,
                "seconds": round(elapsed, 6),
                "pages_per_second": round(len(order) / elapsed, 2) if elapsed else 0,
            }
            data[mode]["order"] = order
    original = data["legacy"].pop("order")
    durable = data["durable"].pop("order")
    return {
        "scenario": "priority_depth_dedup_v01",
        "pages": pages,
        "python": platform.python_version(),
        "os": platform.system(),
        "order_equal": original == durable,
        "first_order_difference": next(
            (i for i, (a, b) in enumerate(zip(original, durable)) if a != b),
            None if len(original) == len(durable) else min(len(original), len(durable))),
        "legacy": data["legacy"],
        "durable": data["durable"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_comparison(args.pages)
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded)
    if not result["order_equal"] or any(
        result[k]["completed"] != args.pages or
        result[k]["duplicates_rejected"] != min(10, args.pages)
        for k in ("legacy", "durable")
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
