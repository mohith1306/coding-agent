#!/usr/bin/env python3
"""SWE-bench benchmark runner."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

from tqdm import tqdm

try:
    from .config import get_available_providers, get_total_rpd
    from .providers import ProviderRotation
    from .runner import run_instance
except ImportError:
    # Support direct execution: python benchmarks/swebench/run.py
    import sys as _sys
    from pathlib import Path as _Path
    _root = _Path(__file__).resolve().parent.parent.parent
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))
    from benchmarks.swebench.config import get_available_providers, get_total_rpd
    from benchmarks.swebench.providers import ProviderRotation
    from benchmarks.swebench.runner import run_instance

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("swebench")


def load_instances(dataset: str, split: str = "dev") -> list[dict[str, Any]]:
    from datasets import load_dataset
    dataset_map = {"lite": "SWE-bench/SWE-bench_Lite", "verified": "SWE-bench/SWE-bench_Verified", "full": "SWE-bench/SWE-bench"}
    ds_name = dataset_map.get(dataset, dataset)
    ds = load_dataset(ds_name, split=split)
    return [dict(row) for row in ds]


def save_predictions(predictions: list[dict[str, Any]], output_path: str) -> None:
    preds_dict = {p["instance_id"]: {"model_patch": p["model_patch"], "model_name_or_path": p.get("model_name_or_path", "coding-agent")} for p in predictions}
    Path(output_path).write_text(json.dumps(preds_dict, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-bench benchmark runner")
    parser.add_argument("--dataset", default="lite", choices=["lite", "verified", "full"])
    parser.add_argument("--split", default="dev")
    parser.add_argument("--max-instances", type=int, default=0)
    parser.add_argument("--instance-id", default="")
    parser.add_argument("--output", default="preds.json")
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("-v", "--verbose", dest="verbose", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    providers = get_available_providers()
    if not providers:
        print("ERROR: No LLM providers configured. Set at least one API key.")
        sys.exit(1)

    print(f"Providers: {', '.join(p.name for p in providers)} | {get_total_rpd()} req/day")

    instances = load_instances(args.dataset, args.split)
    if args.instance_id:
        instances = [i for i in instances if i["instance_id"] == args.instance_id]
    if args.max_instances > 0:
        instances = instances[:args.max_instances]

    print(f"Running {len(instances)} instances...")

    rotation = ProviderRotation(providers)
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="swebench_") as tmpdir:
        for instance in tqdm(instances, desc="Instances"):
            result = run_instance(instance, rotation, Path(tmpdir), max_turns=args.max_turns)
            results.append(result)
            icon = "✓" if result["status"] == "success" else "✗"
            logger.info("%s %s — %s (%.1fs, %d turns)", icon, result["instance_id"], result["status"], result["latency_s"], result["turns"])
            save_predictions(results, args.output)

    save_predictions(results, args.output)

    total = len(results)
    success = sum(1 for r in results if r["status"] == "success")
    no_changes = sum(1 for r in results if r["status"] == "no_changes")
    errors = sum(1 for r in results if r["status"] == "error")
    avg_lat = sum(r["latency_s"] for r in results) / total if total else 0

    print(f"\n{'='*50}")
    print(f"Results: {success} success, {no_changes} no_changes, {errors} errors")
    print(f"Avg latency: {avg_lat:.1f}s | Total: {total}")
    print(f"Provider usage: {rotation.usage}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
