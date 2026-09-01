#!/usr/bin/env python3
"""SWE-bench Lite benchmark runner using free LLM providers.

Usage:
    python run.py --max-instances 10 --output preds.json
    python run.py --dataset lite --output preds.json
    python run.py --instance-id sympy__sympy-20590
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from tqdm import tqdm

from .config import get_available_providers, get_total_rpd
from .providers import ProviderRotation
from .runner import run_instance

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("swebench")


def load_instances(dataset: str, split: str = "dev") -> list[dict[str, Any]]:
    """Load SWE-bench instances from HuggingFace."""
    from datasets import load_dataset

    dataset_map = {
        "lite": "SWE-bench/SWE-bench_Lite",
        "verified": "SWE-bench/SWE-bench_Verified",
        "full": "SWE-bench/SWE-bench",
    }

    ds_name = dataset_map.get(dataset, dataset)
    logger.info("Loading dataset %s (split=%s)...", ds_name, split)
    ds = load_dataset(ds_name, split=split)
    instances = [dict(row) for row in ds]
    logger.info("Loaded %d instances", len(instances))
    return instances


def save_predictions(predictions: list[dict[str, Any]], output_path: str) -> None:
    """Save predictions in sb-cli format (JSON dict keyed by instance_id)."""
    preds_dict = {}
    for p in predictions:
        preds_dict[p["instance_id"]] = {
            "model_patch": p["model_patch"],
            "model_name_or_path": p.get("model_name_or_path", "coding-agent"),
        }

    Path(output_path).write_text(
        json.dumps(preds_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved %d predictions to %s", len(preds_dict), output_path)


def print_summary(results: list[dict[str, Any]]) -> None:
    """Print a summary of the run."""
    total = len(results)
    success = sum(1 for r in results if r["status"] == "success")
    no_changes = sum(1 for r in results if r["status"] == "no_changes")
    errors = sum(1 for r in results if r["status"] == "error")
    avg_latency = (
        sum(r["latency_s"] for r in results) / total if total else 0
    )
    avg_turns = (
        sum(r["turns"] for r in results) / total if total else 0
    )

    print("\n" + "=" * 60)
    print("SWE-bench Run Summary")
    print("=" * 60)
    print(f"  Total instances:   {total}")
    print(f"  Success (patches): {success}")
    print(f"  No changes:        {no_changes}")
    print(f"  Errors:            {errors}")
    print(f"  Avg latency:       {avg_latency:.1f}s")
    print(f"  Avg turns:         {avg_turns:.1f}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SWE-bench benchmark runner with free LLM providers"
    )
    parser.add_argument(
        "--dataset",
        default="lite",
        choices=["lite", "verified", "full"],
        help="SWE-bench dataset (default: lite)",
    )
    parser.add_argument(
        "--split",
        default="dev",
        help="Dataset split (default: dev)",
    )
    parser.add_argument(
        "--max-instances",
        type=int,
        default=0,
        help="Max instances to run (0 = all, default: 0)",
    )
    parser.add_argument(
        "--instance-id",
        type=str,
        default="",
        help="Run a single instance by ID",
    )
    parser.add_argument(
        "--output",
        default="preds.json",
        help="Output predictions file (default: preds.json)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=15,
        help="Max agent turns per instance (default: 15)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="",
        help="Override model name for all providers",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check providers
    providers = get_available_providers()
    if not providers:
        print("ERROR: No LLM providers configured. Set at least one API key:")
        print("  export GOOGLE_API_KEY=...      # 14,400 req/day free")
        print("  export GROQ_API_KEY=...        # 1,000 req/day free")
        print("  export CEREBRAS_API_KEY=...    # 1,000 req/day free")
        print("  export OPENROUTER_API_KEY=...  # 1,000 req/day free")
        sys.exit(1)

    print(f"Available providers: {', '.join(p.name for p in providers)}")
    print(f"Total daily capacity: {get_total_rpd()} requests")

    # Load instances
    instances = load_instances(args.dataset, args.split)

    # Filter by instance ID if specified
    if args.instance_id:
        instances = [i for i in instances if i["instance_id"] == args.instance_id]
        if not instances:
            print(f"ERROR: Instance {args.instance_id} not found")
            sys.exit(1)

    # Limit count
    if args.max_instances > 0:
        instances = instances[: args.max_instances]

    print(f"Running {len(instances)} instances...")

    # Run
    rotation = ProviderRotation(providers)
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="swebench_") as tmpdir:
        tmpdir_path = Path(tmpdir)

        for instance in tqdm(instances, desc="Instances"):
            iid = instance["instance_id"]
            logger.info("Starting %s", iid)

            result = run_instance(
                instance=instance,
                provider=rotation,
                tmpdir=tmpdir_path,
                max_turns=args.max_turns,
                model_override=args.model or None,
            )
            results.append(result)

            status_icon = "✓" if result["status"] == "success" else "✗"
            logger.info(
                "%s %s — %s (%.1fs, %d turns)",
                status_icon, iid, result["status"],
                result["latency_s"], result["turns"],
            )

            # Save intermediate results
            save_predictions(results, args.output)

    # Final save and summary
    save_predictions(results, args.output)
    print_summary(results)

    # Print provider usage
    print("\nProvider usage:")
    for name, count in rotation.usage.items():
        print(f"  {name}: {count} requests")


if __name__ == "__main__":
    main()
