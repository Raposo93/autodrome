#!/usr/bin/env python3
"""Opt-in entry point for reproducible disposable chaos campaigns."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from autodrome.logger import logger
from tests.chaos import ChaosFailure, run_chaos


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run seeded chaos only against disposable local fixtures."
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--scenario",
        choices=("all", "album-download", "selection-race"),
        default="all",
    )
    parser.add_argument("--max-events", type=int, default=160)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs must be positive")
    return args


def run_selection_races(seeds: list[int]) -> None:
    environment = os.environ.copy()
    environment["AUTODROME_CHAOS_SEEDS"] = ",".join(map(str, seeds))
    subprocess.run(
        [
            "npm",
            "run",
            "test:e2e",
            "--prefix",
            "frontend",
            "--",
            "--grep",
            "seeded selection chaos",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
    )


async def run_backend(args: argparse.Namespace, seeds: list[int]) -> list[dict]:
    results = []
    for seed in seeds:
        result = await run_chaos(
            seed,
            max_events=args.max_events,
            timeout_seconds=args.timeout_seconds,
        )
        results.append(result)
        if not args.json:
            print(
                f"PASS scenario=album-download seed={seed} "
                f"events={len(result['events'])} statuses={result['status_counts']}"
            )
    return results


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger.disabled = not args.verbose
    seeds = [args.seed + offset for offset in range(args.runs)]
    results = []
    try:
        if args.scenario in {"all", "album-download"}:
            results = asyncio.run(run_backend(args, seeds))
        if args.scenario in {"all", "selection-race"}:
            run_selection_races(seeds)
    except ChaosFailure as error:
        print(error, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(
            json.dumps(
                {
                    "result": "FAIL",
                    "scenario": "selection-race",
                    "seeds": seeds,
                    "reason": f"Playwright exited with status {error.returncode}",
                    "reproduce": (
                        "python scripts/chaos_test.py --scenario selection-race "
                        f"--seed {args.seed} --runs {args.runs}"
                    ),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
