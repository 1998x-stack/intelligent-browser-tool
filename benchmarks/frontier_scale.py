"""Repeated, machine-readable frontier comparison and bulk insertion evaluation."""
import argparse
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path

from benchmarks.frontier_compare import run_comparison
from config import Config
from frontier_state import FrontierState
from url_policy import URLPolicy


def summarize(samples):
    ordered=sorted(samples)
    p95=ordered[min(len(ordered)-1, max(0, int((len(ordered)-1)*0.95+0.9999)))]
    return {"repetitions":len(samples),"median_seconds":round(statistics.median(samples),6),
            "p95_seconds":round(p95,6),"min_seconds":round(ordered[0],6),
            "max_seconds":round(ordered[-1],6)}


def bulk_compare(size=200, repetitions=3):
    if not 1 <= size <= 200000 or not 1 <= repetitions <= 100:
        raise ValueError("Invalid size/repetition budget")
    durations={"individual":[],"batch":[]}
    rows=[{"url":f"https://example.com/item-{i:06d}","priority":i%3+1,
           "depth":i%4} for i in range(size)]
    for _ in range(repetitions):
        for method in durations:
            with tempfile.TemporaryDirectory() as temp:
                with FrontierState(Path(temp)/"queue.db",URLPolicy(("example.com",))) as q:
                    start=time.perf_counter()
                    if method=="batch":
                        assert q.enqueue_many(rows)==size
                    else:
                        for row in rows:
                            assert q.enqueue(**row)
                    elapsed=time.perf_counter()-start
                    assert q.counts()["queued"]==size
                    durations[method].append(elapsed)
    return {key:summarize(value) for key,value in durations.items()}


def matrix(sizes=(50,500),repetitions=3):
    if not sizes or any(not 1 <= n <= 200000 for n in sizes):
        raise ValueError("Invalid sizes")
    result=[]
    for size in sizes:
        samples={"legacy":[],"durable":[]}
        checks=[]
        for _ in range(repetitions):
            value=run_comparison(size)
            assert value["order_equal"], f"URL order mismatch at size {size}"
            assert value["legacy"]["completed"]==size
            assert value["durable"]["completed"]==size
            checks.append(value["order_equal"])
            for key in samples:
                samples[key].append(value[key]["seconds"])
        result.append({"pages":size,"order_equal":all(checks),
                       "legacy":summarize(samples["legacy"]),
                       "durable":summarize(samples["durable"]),
                       "bulk_insert":bulk_compare(size,repetitions)})
    return {"kind":"frontier_scaling_v014","python":platform.python_version(),
            "platform":platform.platform(),"data":result}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--sizes",nargs="+",type=int,default=[50,500])
    p.add_argument("--repeat",type=int,default=3)
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    result=matrix(args.sizes,args.repeat)
    encoded=json.dumps(result,indent=2,ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(encoded,encoding="utf-8")
    print(encoded)


if __name__=="__main__":
    main()
