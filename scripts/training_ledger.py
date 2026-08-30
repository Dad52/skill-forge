#!/usr/bin/env python3
"""Create reproducible skill snapshots and compute a guarded Pareto frontier."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SCHEMA_VERSION = "1.0"
IGNORED_PARTS = {
    ".DS_Store", ".git", ".skill-forge", "__pycache__", ".mypy_cache", ".pytest_cache",
}
GOALS = {"max", "min"}


class LedgerError(ValueError):
    pass


def required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LedgerError(f"{field} must be a non-empty string.")
    return value.strip()


def included_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in IGNORED_PARTS for part in parts) or path.is_symlink():
            continue
        if path.is_file():
            files.append(path)
    return sorted(files)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(target: Path) -> dict[str, Any]:
    root = target.resolve()
    if not root.is_dir():
        raise LedgerError("target must be a readable directory.")
    records: list[dict[str, str]] = []
    aggregate = hashlib.sha256()
    for path in included_files(root):
        relative = path.relative_to(root).as_posix()
        digest = file_sha256(path)
        records.append({"path": relative, "sha256": digest})
        aggregate.update(relative.encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(digest.encode("ascii"))
        aggregate.update(b"\n")
    return {
        "schema_version": SCHEMA_VERSION,
        "target": str(root),
        "tree_sha256": aggregate.hexdigest(),
        "files": records,
        "file_count": len(records),
        "provenance": {
            "network_calls": 0,
            "model_calls": 0,
            "excluded_paths": sorted(IGNORED_PARTS),
            "note": "Snapshot is a content fingerprint, not a behavioral quality claim.",
        },
    }


def number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LedgerError(f"{field} must be a number.")
    return float(value)


def candidate_records(payload: Any) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise LedgerError("Frontier input must be a JSON object.")
    raw_directions = payload.get("directions")
    if not isinstance(raw_directions, dict) or not raw_directions:
        raise LedgerError("directions must be a non-empty object.")
    directions: dict[str, str] = {}
    for name, goal in raw_directions.items():
        metric = required_string(name, "directions key")
        if goal not in GOALS:
            raise LedgerError(f"directions.{metric} must be one of {sorted(GOALS)}.")
        directions[metric] = goal

    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise LedgerError("candidates must be a non-empty list.")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_candidates):
        if not isinstance(raw, dict):
            raise LedgerError(f"candidates[{index}] must be an object.")
        candidate_id = required_string(raw.get("candidate_id"), f"candidates[{index}].candidate_id")
        if candidate_id in seen:
            raise LedgerError("candidate_id values must be unique.")
        seen.add(candidate_id)
        mutation = raw.get("mutation")
        if not isinstance(mutation, dict):
            raise LedgerError(f"candidates[{index}].mutation must be an object.")
        required_string(mutation.get("summary"), f"candidates[{index}].mutation.summary")
        requirement_ids = mutation.get("requirement_ids")
        if not isinstance(requirement_ids, list) or not requirement_ids:
            raise LedgerError(
                f"candidates[{index}].mutation.requirement_ids must be a non-empty list."
            )
        gates = raw.get("gates")
        if not isinstance(gates, dict) or not gates:
            raise LedgerError(f"candidates[{index}].gates must be a non-empty object.")
        if any(not isinstance(value, bool) for value in gates.values()):
            raise LedgerError(f"candidates[{index}].gates values must be boolean.")
        metrics = raw.get("metrics")
        if not isinstance(metrics, dict):
            raise LedgerError(f"candidates[{index}].metrics must be an object.")
        values = {
            metric: number(metrics.get(metric), f"candidates[{index}].metrics.{metric}")
            for metric in directions
        }
        records.append(
            {
                "candidate_id": candidate_id,
                "mutation": mutation,
                "gates": gates,
                "metrics": values,
                "eligible": all(gates.values()),
            }
        )
    return directions, records


def dominates(
    left: dict[str, Any], right: dict[str, Any], directions: dict[str, str]
) -> bool:
    better_or_equal = True
    strictly_better = False
    for metric, goal in directions.items():
        a = left["metrics"][metric]
        b = right["metrics"][metric]
        if goal == "max":
            better_or_equal = better_or_equal and a >= b
            strictly_better = strictly_better or a > b
        else:
            better_or_equal = better_or_equal and a <= b
            strictly_better = strictly_better or a < b
    return better_or_equal and strictly_better


def frontier(payload: Any) -> dict[str, Any]:
    directions, records = candidate_records(payload)
    eligible = [record for record in records if record["eligible"]]
    selected = [
        record
        for record in eligible
        if not any(
            other["candidate_id"] != record["candidate_id"]
            and dominates(other, record, directions)
            for other in eligible
        )
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "directions": directions,
        "candidates_considered": len(records),
        "candidates_rejected_by_gate": [
            {
                "candidate_id": record["candidate_id"],
                "failed_gates": [
                    name for name, passed in record["gates"].items() if not passed
                ],
            }
            for record in records
            if not record["eligible"]
        ],
        "pareto_frontier": selected,
        "provenance": {
            "network_calls": 0,
            "model_calls": 0,
            "note": "Pareto membership is a guarded comparison, not automatic promotion.",
        },
    }


def write_payload(payload: dict[str, Any], output: Path | None) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(data, encoding="utf-8")
    else:
        sys.stdout.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot_parser = subparsers.add_parser("snapshot")
    snapshot_parser.add_argument("--target", required=True, type=Path)
    snapshot_parser.add_argument("--output", type=Path)
    frontier_parser = subparsers.add_parser("frontier")
    frontier_parser.add_argument("--input", required=True, type=Path)
    frontier_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            write_payload(snapshot(args.target), args.output)
        else:
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            write_payload(frontier(payload), args.output)
    except (OSError, json.JSONDecodeError, LedgerError) as error:
        print(f"INVALID TRAINING LEDGER INPUT: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
