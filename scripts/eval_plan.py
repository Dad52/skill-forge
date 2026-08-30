#!/usr/bin/env python3
"""Validate an explicit Skill Forge EVAL plan and estimate model-call counts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SCHEMA_VERSION = "1.0"
EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
JUDGE_MODES = {"none", "blind_pairwise"}
CONDITIONS = {"baseline", "with_skill"}


class PlanError(ValueError):
    pass


def required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanError(f"{field} must be a non-empty string.")
    return value.strip()


def positive_int(value: Any, field: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise PlanError(f"{field} must be an integer from 1 to {maximum}.")
    return value


def model_role(value: Any, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise PlanError(f"{field} must be an object.")
    model = required_string(value.get("model"), f"{field}.model")
    effort = required_string(value.get("reasoning_effort"), f"{field}.reasoning_effort")
    if effort not in EFFORTS:
        raise PlanError(f"{field}.reasoning_effort must be one of {sorted(EFFORTS)}.")
    return {"model": model, "reasoning_effort": effort}


def validate(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise PlanError("EVAL plan must be a JSON object.")

    candidate = required_string(plan.get("candidate_version"), "candidate_version")
    baseline = required_string(plan.get("baseline_version"), "baseline_version")
    eval_set = required_string(plan.get("eval_set_version"), "eval_set_version")
    worker = model_role(plan.get("worker"), "worker")

    raw_conditions = plan.get("conditions")
    if not isinstance(raw_conditions, list) or set(raw_conditions) != CONDITIONS:
        raise PlanError("conditions must contain exactly baseline and with_skill.")

    raw_cases = plan.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise PlanError("cases must be a non-empty list.")
    case_ids: list[str] = []
    for index, item in enumerate(raw_cases):
        if not isinstance(item, dict):
            raise PlanError(f"cases[{index}] must be an object.")
        case_ids.append(required_string(item.get("case_id"), f"cases[{index}].case_id"))
        if "holdout" in item and not isinstance(item["holdout"], bool):
            raise PlanError(f"cases[{index}].holdout must be boolean.")
    if len(case_ids) != len(set(case_ids)):
        raise PlanError("case_id values must be unique.")

    repeats = positive_int(plan.get("runs_per_case", 1), "runs_per_case", 10)
    concurrency = positive_int(plan.get("concurrency", 1), "concurrency", 8)
    timeout = positive_int(plan.get("timeout_seconds", 300), "timeout_seconds", 86_400)
    judge_mode = required_string(plan.get("judge_mode", "none"), "judge_mode")
    if judge_mode not in JUDGE_MODES:
        raise PlanError(f"judge_mode must be one of {sorted(JUDGE_MODES)}.")

    judge: dict[str, str] | None = None
    judge_strength_basis: str | None = None
    if judge_mode != "none":
        judge = model_role(plan.get("judge"), "judge")
        if plan.get("judge_stronger_confirmed") is not True:
            raise PlanError(
                "judge_stronger_confirmed must be true when model judgment is used."
            )
        judge_strength_basis = required_string(
            plan.get("judge_strength_basis"), "judge_strength_basis"
        )

    token_budget = plan.get("token_budget")
    if token_budget is not None:
        positive_int(token_budget, "token_budget", 100_000_000)
    time_budget = plan.get("time_budget_seconds")
    if time_budget is not None:
        positive_int(time_budget, "time_budget_seconds", 604_800)

    stop_condition = required_string(plan.get("stop_condition"), "stop_condition")
    worker_calls = len(case_ids) * len(CONDITIONS) * repeats
    judge_calls = len(case_ids) * repeats if judge_mode == "blind_pairwise" else 0
    warnings: list[str] = []
    if judge and judge["model"] == worker["model"] and judge["reasoning_effort"] == worker["reasoning_effort"]:
        warnings.append(
            "Judge and worker configurations are identical; independence and stronger judgment are not established."
        )
    if not plan.get("clean_context_per_run", False):
        warnings.append("clean_context_per_run is not confirmed.")
    if not plan.get("isolated_workspace_per_run", False):
        warnings.append("isolated_workspace_per_run is not confirmed.")
    if not plan.get("conditions_equivalent", False):
        warnings.append("conditions_equivalent is not confirmed; no causal lift may be claimed.")
    if not any(bool(item.get("holdout")) for item in raw_cases):
        warnings.append("No holdout case is identified.")

    return {
        "schema_version": SCHEMA_VERSION,
        "valid": True,
        "candidate_version": candidate,
        "baseline_version": baseline,
        "eval_set_version": eval_set,
        "worker": worker,
        "judge_mode": judge_mode,
        "judge": judge or "not_used",
        "judge_strength_basis": judge_strength_basis or "not_applicable",
        "case_count": len(case_ids),
        "conditions": sorted(CONDITIONS),
        "runs_per_case": repeats,
        "concurrency": concurrency,
        "timeout_seconds": timeout,
        "estimated_calls": {
            "worker": worker_calls,
            "judge": judge_calls,
            "total": worker_calls + judge_calls,
        },
        "budgets": {
            "tokens": token_budget if token_budget is not None else "unknown",
            "wall_time_seconds": time_budget if time_budget is not None else "unknown",
        },
        "stop_condition": stop_condition,
        "warnings": warnings,
        "network_calls": 0,
        "model_calls": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        plan = json.loads(args.input.read_text(encoding="utf-8"))
        result = validate(plan)
    except (OSError, json.JSONDecodeError, PlanError) as error:
        print(f"INVALID EVAL PLAN: {error}", file=sys.stderr)
        return 2
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
