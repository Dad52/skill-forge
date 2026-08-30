#!/usr/bin/env python3
"""Validate a bounded, explicit Skill Forge train plan without model calls."""

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
MINIMUM_CANDIDATE_EVALUATIONS = 50


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


def cases(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PlanError(f"{field} must be a non-empty list.")
    result = [required_string(item, f"{field}[{index}]") for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise PlanError(f"{field} contains duplicate case IDs.")
    return result


def strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PlanError(f"{field} must be a non-empty list.")
    return [required_string(item, f"{field}[{index}]") for index, item in enumerate(value)]


def early_stop_contract(value: Any, judge_mode: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError("early_stop must be an object.")
    allowed = value.get("allowed")
    if not isinstance(allowed, bool):
        raise PlanError("early_stop.allowed must be boolean.")
    if not allowed:
        return {"allowed": False}
    for field in (
        "requires_pareto_eligibility",
        "requires_full_developer_panel",
        "requires_blind_judgment",
        "requires_final_holdout",
    ):
        if value.get(field) is not True:
            raise PlanError(f"early_stop.{field} must be true when early stopping is allowed.")
    if judge_mode != "blind_pairwise":
        raise PlanError("early_stop requires judge_mode=blind_pairwise.")
    confirmation_repeats = positive_int(
        value.get("minimum_confirmation_repeats"),
        "early_stop.minimum_confirmation_repeats",
        10,
    )
    if confirmation_repeats < 3:
        raise PlanError("early_stop.minimum_confirmation_repeats must be at least 3.")
    improvements = strings(
        value.get("required_metric_improvements"),
        "early_stop.required_metric_improvements",
    )
    return {
        "allowed": True,
        "requires_pareto_eligibility": True,
        "requires_full_developer_panel": True,
        "requires_blind_judgment": True,
        "requires_final_holdout": True,
        "minimum_confirmation_repeats": confirmation_repeats,
        "required_metric_improvements": improvements,
    }


def validate(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise PlanError("Train plan must be a JSON object.")
    target_version = required_string(plan.get("target_version"), "target_version")
    baseline_version = required_string(plan.get("baseline_version"), "baseline_version")
    eval_set_version = required_string(plan.get("eval_set_version"), "eval_set_version")
    worker = model_role(plan.get("worker"), "worker")
    developer_cases = cases(plan.get("developer_cases"), "developer_cases")
    holdout_cases = cases(plan.get("final_holdout_cases"), "final_holdout_cases")
    overlap = sorted(set(developer_cases) & set(holdout_cases))
    if overlap:
        raise PlanError(f"developer_cases and final_holdout_cases overlap: {', '.join(overlap)}.")
    if plan.get("active_skill_immutable") is not True:
        raise PlanError("active_skill_immutable must be true.")
    if plan.get("promotion_requires_explicit_approval") is not True:
        raise PlanError("promotion_requires_explicit_approval must be true.")
    if plan.get("conditions_equivalent") is not True:
        raise PlanError("conditions_equivalent must be true.")
    if plan.get("final_holdout_access") != "blocked_during_authoring":
        raise PlanError("final_holdout_access must be blocked_during_authoring.")

    batch_size = positive_int(plan.get("candidate_batch_size"), "candidate_batch_size", 4)
    max_rounds = positive_int(plan.get("max_rounds"), "max_rounds", 50)
    minimum_candidates = positive_int(
        plan.get("minimum_candidate_evaluations"),
        "minimum_candidate_evaluations",
        200,
    )
    if minimum_candidates < MINIMUM_CANDIDATE_EVALUATIONS:
        raise PlanError(
            f"minimum_candidate_evaluations must be at least {MINIMUM_CANDIDATE_EVALUATIONS}."
        )
    no_improvement = positive_int(
        plan.get("max_no_improvement_rounds"), "max_no_improvement_rounds", max_rounds
    )
    developer_repeats = positive_int(
        plan.get("developer_runs_per_case", 1), "developer_runs_per_case", 10
    )
    holdout_repeats = positive_int(
        plan.get("final_runs_per_case", 1), "final_runs_per_case", 10
    )
    concurrency = positive_int(plan.get("concurrency", 1), "concurrency", 8)
    token_budget = positive_int(plan.get("token_budget"), "token_budget", 100_000_000)
    time_budget = positive_int(
        plan.get("time_budget_seconds"), "time_budget_seconds", 604_800
    )
    protected_metrics = strings(plan.get("protected_metrics"), "protected_metrics")
    hard_gates = strings(plan.get("hard_gates"), "hard_gates")
    stop_condition = required_string(plan.get("stop_condition"), "stop_condition")

    judge_mode = required_string(plan.get("judge_mode", "none"), "judge_mode")
    if judge_mode not in JUDGE_MODES:
        raise PlanError(f"judge_mode must be one of {sorted(JUDGE_MODES)}.")
    judge: dict[str, str] | None = None
    warnings: list[str] = []
    if judge_mode == "blind_pairwise":
        judge = model_role(plan.get("judge"), "judge")
        if plan.get("judge_stronger_confirmed") is not True:
            raise PlanError(
                "judge_stronger_confirmed must be true when model judgment is used."
            )
        required_string(plan.get("judge_strength_basis"), "judge_strength_basis")
        if judge == worker:
            warnings.append(
                "Judge and worker configurations are identical; independence is not established."
            )

    max_candidates = batch_size * max_rounds
    if max_candidates < minimum_candidates:
        raise PlanError(
            "candidate_batch_size * max_rounds must cover minimum_candidate_evaluations."
        )
    early_stop = early_stop_contract(plan.get("early_stop"), judge_mode)
    baseline_developer_calls = len(developer_cases) * developer_repeats
    candidate_developer_calls = max_candidates * baseline_developer_calls
    final_worker_calls = 2 * len(holdout_cases) * holdout_repeats
    judge_calls = (
        len(holdout_cases) * holdout_repeats if judge_mode == "blind_pairwise" else 0
    )
    early_confirmation_worker_calls = (
        2
        * len(developer_cases)
        * early_stop.get("minimum_confirmation_repeats", 0)
    )
    early_confirmation_judge_calls = (
        len(developer_cases) * early_stop.get("minimum_confirmation_repeats", 0)
        if early_stop["allowed"]
        else 0
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": True,
        "target_version": target_version,
        "baseline_version": baseline_version,
        "eval_set_version": eval_set_version,
        "worker": worker,
        "judge_mode": judge_mode,
        "judge": judge or "not_used",
        "developer_case_count": len(developer_cases),
        "final_holdout_case_count": len(holdout_cases),
        "max_candidates": max_candidates,
        "minimum_candidate_evaluations": minimum_candidates,
        "candidate_batch_size": batch_size,
        "max_rounds": max_rounds,
        "max_no_improvement_rounds": no_improvement,
        "protected_metrics": protected_metrics,
        "hard_gates": hard_gates,
        "early_stop": early_stop,
        "estimated_calls": {
            "baseline_developer_worker": baseline_developer_calls,
            "candidate_developer_worker_max": candidate_developer_calls,
            "early_stop_confirmation_worker": early_confirmation_worker_calls,
            "final_worker": final_worker_calls,
            "early_stop_confirmation_judge": early_confirmation_judge_calls,
            "judge": judge_calls,
            "total_max": (
                baseline_developer_calls
                + candidate_developer_calls
                + early_confirmation_worker_calls
                + final_worker_calls
                + early_confirmation_judge_calls
                + judge_calls
            ),
        },
        "budgets": {
            "tokens": token_budget,
            "wall_time_seconds": time_budget,
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
        print(f"INVALID TRAIN PLAN: {error}", file=sys.stderr)
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
