#!/usr/bin/env python3
"""Validate evidence and render a compact one-page Skill Forge report."""

from __future__ import annotations

import argparse
import html
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

STATUSES = {"pass", "fail", "infrastructure_error"}
ASSERTION_OUTCOMES = {"pass", "fail", "not_applicable"}
SEVERITIES = {"error", "warning", "info"}
REPORT_TYPES = {"audit", "eval"}


class ReportError(ValueError):
    pass


def esc(value: Any) -> str:
    return html.escape(str(value))


def require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReportError(f"{field} must be a non-empty string.")
    return value.strip()


def nonnegative_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ReportError(f"{field} must be a non-negative number.")
    return float(value)


def normalize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ReportError("Report input must be a JSON object.")
    report = dict(payload)
    if "report_type" not in report and "target" in report and "findings" in report:
        report["report_type"] = "audit"
        errors = int(report.get("summary", {}).get("errors", 0))
        report["verdict"] = "Blocked by static errors" if errors else "No static release blockers"
        report.setdefault("metadata", {})
        report["metadata"].setdefault("target", report.get("target"))
        report["metadata"].setdefault("scanner", report.get("provenance", {}))
        report.setdefault("cases", [])
    report_type = report.get("report_type")
    if report_type not in REPORT_TYPES:
        raise ReportError(f"report_type must be one of {sorted(REPORT_TYPES)}.")
    report["verdict"] = require_string(report.get("verdict"), "verdict")

    metadata = report.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ReportError("metadata must be an object.")
    report["metadata"] = metadata

    findings = report.get("findings", [])
    if not isinstance(findings, list):
        raise ReportError("findings must be a list.")
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            raise ReportError(f"findings[{index}] must be an object.")
        severity = item.get("severity", "info")
        if severity not in SEVERITIES:
            raise ReportError(f"findings[{index}].severity is invalid.")
        require_string(item.get("code", item.get("id")), f"findings[{index}].code")
        require_string(item.get("message"), f"findings[{index}].message")

    cases = report.get("cases", [])
    if not isinstance(cases, list):
        raise ReportError("cases must be a list.")
    for index, item in enumerate(cases):
        if not isinstance(item, dict):
            raise ReportError(f"cases[{index}] must be an object.")
        require_string(item.get("case_id"), f"cases[{index}].case_id")
        status = item.get("status")
        if status not in STATUSES:
            raise ReportError(f"cases[{index}].status must be one of {sorted(STATUSES)}.")
        if report_type == "eval":
            require_string(item.get("condition"), f"cases[{index}].condition")
        for field in ("wall_time_seconds", "tokens", "quality_score"):
            if field in item and item[field] is not None:
                nonnegative_number(item[field], f"cases[{index}].{field}")
        assertions = item.get("assertions")
        if assertions is not None:
            if not isinstance(assertions, list):
                raise ReportError(f"cases[{index}].assertions must be a list.")
            assertion_ids: set[str] = set()
            for assertion_index, assertion in enumerate(assertions):
                if not isinstance(assertion, dict):
                    raise ReportError(
                        f"cases[{index}].assertions[{assertion_index}] must be an object."
                    )
                assertion_id = require_string(
                    assertion.get("assertion_id"),
                    f"cases[{index}].assertions[{assertion_index}].assertion_id",
                )
                if assertion_id in assertion_ids:
                    raise ReportError(
                        f"cases[{index}].assertions has duplicate assertion_id {assertion_id}."
                    )
                assertion_ids.add(assertion_id)
                if assertion.get("outcome") not in ASSERTION_OUTCOMES:
                    raise ReportError(
                        f"cases[{index}].assertions[{assertion_index}].outcome "
                        f"must be one of {sorted(ASSERTION_OUTCOMES)}."
                    )

    if report_type == "eval":
        require_string(metadata.get("candidate_version"), "metadata.candidate_version")
        require_string(metadata.get("eval_set_version"), "metadata.eval_set_version")
        require_string(metadata.get("worker_model"), "metadata.worker_model")
        if not isinstance(metadata.get("conditions_equivalent"), bool):
            raise ReportError("metadata.conditions_equivalent must be boolean.")
        judge_model = metadata.get("judge_model", "not_used")
        require_string(judge_model, "metadata.judge_model")
    report["findings"] = findings
    report["cases"] = cases
    return report


def percentile_90(values: list[float]) -> float | str:
    if len(values) < 3:
        return "insufficient"
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def fmt_number(value: float | int | str, suffix: str = "") -> str:
    if isinstance(value, str):
        return value
    if float(value).is_integer():
        return f"{int(value)}{suffix}"
    return f"{value:.2f}{suffix}"


def assertion_diagnostics(cases: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Identify EVAL assertions that cannot separate paired conditions."""
    grouped: dict[str, dict[str, dict[str, set[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(set))
    )
    for item in cases:
        if item.get("status") not in {"pass", "fail"}:
            continue
        condition = item.get("condition")
        if condition not in {"baseline", "with_skill"}:
            continue
        for assertion in item.get("assertions", []):
            grouped[item["case_id"]][condition][assertion["assertion_id"]].add(
                assertion["outcome"]
            )
    diagnostics: list[dict[str, str]] = []
    for case_id, by_condition in sorted(grouped.items()):
        baseline = by_condition.get("baseline", {})
        candidate = by_condition.get("with_skill", {})
        if not baseline or not candidate:
            diagnostics.append({"case_id": case_id, "state": "missing_paired_assertions"})
            continue
        if any(
            len(outcomes) > 1
            for condition in (baseline, candidate)
            for outcomes in condition.values()
        ):
            diagnostics.append({"case_id": case_id, "state": "unstable"})
            continue
        baseline_values = {name: next(iter(values)) for name, values in baseline.items()}
        candidate_values = {name: next(iter(values)) for name, values in candidate.items()}
        state = (
            "non_discriminating"
            if baseline_values == candidate_values
            else "discriminating"
        )
        diagnostics.append({"case_id": case_id, "state": state})
    return diagnostics


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    cases = report["cases"]
    completed = [item for item in cases if item["status"] in {"pass", "fail"}]
    infrastructure = [item for item in cases if item["status"] == "infrastructure_error"]
    metadata = report["metadata"]
    report_type = report["report_type"]

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in cases:
        grouped[str(item.get("condition", "audit"))].append(item)

    condition_summaries: dict[str, dict[str, Any]] = {}
    for condition, items in sorted(grouped.items()):
        usable = [item for item in items if item["status"] in {"pass", "fail"}]
        token_values = [float(item["tokens"]) for item in usable if item.get("tokens") is not None]
        latency_values = [
            float(item["wall_time_seconds"])
            for item in usable
            if item.get("wall_time_seconds") is not None
        ]
        quality_values = [
            float(item["quality_score"])
            for item in usable
            if item.get("quality_score") is not None
        ]
        passes = sum(item["status"] == "pass" for item in usable)
        condition_summaries[condition] = {
            "completed": len(usable),
            "pass": passes,
            "fail": len(usable) - passes,
            "infrastructure_error": sum(
                item["status"] == "infrastructure_error" for item in items
            ),
            "pass_rate": round(passes / len(usable), 4) if usable else "unknown",
            "median_tokens": statistics.median(token_values) if token_values else "unknown",
            "median_latency_seconds": (
                statistics.median(latency_values) if latency_values else "unknown"
            ),
            "p90_latency_seconds": percentile_90(latency_values),
            "median_judged_quality": (
                statistics.median(quality_values) if quality_values else "unknown"
            ),
        }

    paired_cases = 0
    evidence_level = "static_only"
    if report_type == "eval":
        baseline = {
            item["case_id"]
            for item in completed
            if item.get("condition") == "baseline"
        }
        candidate = {
            item["case_id"]
            for item in completed
            if item.get("condition") == "with_skill"
        }
        paired_cases = len(baseline & candidate)
        equivalent = bool(metadata["conditions_equivalent"])
        if not equivalent or paired_cases == 0:
            evidence_level = "insufficient"
        elif paired_cases < 3:
            evidence_level = "directional"
        else:
            evidence_level = "comparable"

    status_counts = Counter(item["status"] for item in cases)
    diagnostics = assertion_diagnostics(cases) if report_type == "eval" else []
    return {
        "evidence_level": evidence_level,
        "paired_cases": paired_cases,
        "completed_runs": len(completed),
        "infrastructure_errors": len(infrastructure),
        "status_counts": dict(status_counts),
        "conditions": condition_summaries,
        "assertion_diagnostics": diagnostics,
        "assertion_diagnostic_counts": dict(
            Counter(item["state"] for item in diagnostics)
        ),
        "can_claim_comparison": evidence_level == "comparable",
        "sufficiency_note": {
            "static_only": "Static evidence only; behavioral quality and live token use were not measured.",
            "insufficient": "Conditions or paired completed cases are insufficient for a causal comparison.",
            "directional": "Equivalent paired evidence exists, but fewer than three paired cases support only a directional conclusion.",
            "comparable": "At least three paired cases completed under declared equivalent conditions; inspect variance and raw evidence before generalizing.",
        }[evidence_level],
    }


def cards(report: dict[str, Any], derived: dict[str, Any]) -> str:
    metadata = report["metadata"]
    values = [
        ("Evidence", derived["evidence_level"]),
        ("Paired cases", derived["paired_cases"] if report["report_type"] == "eval" else "not applicable"),
        ("Completed runs", derived["completed_runs"]),
        ("Infrastructure errors", derived["infrastructure_errors"]),
    ]
    if report["report_type"] == "eval":
        values.extend(
            [
                ("Worker", metadata.get("worker_model", "unknown")),
                ("Judge", metadata.get("judge_model", "not_used")),
                (
                    "Non-discriminating cases",
                    derived["assertion_diagnostic_counts"].get(
                        "non_discriminating", "not recorded"
                    ),
                ),
                (
                    "Unstable assertion cases",
                    derived["assertion_diagnostic_counts"].get("unstable", "not recorded"),
                ),
            ]
        )
    return "".join(
        "<article class='card'><span>"
        + esc(name)
        + "</span><strong>"
        + esc(value)
        + "</strong></article>"
        for name, value in values
    )


def finding_table(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<p class="muted">No findings recorded.</p>'
    rows: list[str] = []
    for item in items:
        location = item.get("path", "—")
        if item.get("line"):
            location = f"{location}:{item['line']}"
        rows.append(
            "<tr>"
            f"<td><span class='severity {esc(item.get('severity', 'info'))}'>{esc(item.get('severity', 'info'))}</span></td>"
            f"<td>{esc(item.get('code', item.get('id', '')))}</td>"
            f"<td>{esc(item.get('message', ''))}<br><small>{esc(item.get('evidence', ''))}</small></td>"
            f"<td>{esc(location)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Severity</th><th>Code</th><th>Finding and evidence</th>"
        "<th>Location</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def condition_table(conditions: dict[str, dict[str, Any]]) -> str:
    if not conditions:
        return '<p class="muted">No completed conditions.</p>'
    rows: list[str] = []
    for name, values in conditions.items():
        pass_rate = values["pass_rate"]
        if isinstance(pass_rate, float):
            pass_rate = f"{pass_rate * 100:.1f}%"
        rows.append(
            "<tr>"
            f"<td>{esc(name)}</td><td>{esc(values['completed'])}</td>"
            f"<td>{esc(pass_rate)}</td><td>{esc(fmt_number(values['median_tokens']))}</td>"
            f"<td>{esc(fmt_number(values['median_latency_seconds'], 's'))}</td>"
            f"<td>{esc(fmt_number(values['p90_latency_seconds'], 's'))}</td>"
            f"<td>{esc(fmt_number(values['median_judged_quality']))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Condition</th><th>Completed</th><th>Pass rate</th>"
        "<th>Median tokens</th><th>Median latency</th><th>P90 latency</th>"
        "<th>Median judged quality</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def details(title: str, items: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    if not items:
        return ""
    rows: list[str] = []
    for item in items:
        values = " · ".join(
            f"<b>{esc(field)}:</b> {esc(item.get(field, 'unknown'))}"
            for field in fields
        )
        rows.append(
            f"<li>{values}<br><span class='muted'>{esc(item.get('evidence', 'No evidence recorded.'))}</span></li>"
        )
    return f"<details><summary>{esc(title)} ({len(items)})</summary><ol>{''.join(rows)}</ol></details>"


def render(report: dict[str, Any]) -> str:
    derived = summarize(report)
    metadata = report["metadata"]
    return f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Skill Forge report</title>
<style>
:root {{ color-scheme:light dark; --ink:#1d2733; --muted:#637083; --paper:#f6f8fb; --line:#dfe5ec; --good:#087f5b; --warn:#a15c00; --bad:#bb2d3b; }}
body {{ max-width:1120px; margin:32px auto; padding:0 20px 48px; font:15px/1.55 ui-sans-serif,system-ui,sans-serif; color:var(--ink); }}
h1 {{ margin-bottom:4px; }} .muted,small {{ color:var(--muted); }} .banner {{ border-left:5px solid #3b82f6; background:var(--paper); padding:16px 18px; border-radius:8px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:20px 0; }}
.card {{ border:1px solid var(--line); border-radius:10px; padding:14px; }} .card span {{ display:block; color:var(--muted); }} .card strong {{ display:block; font-size:1.2rem; margin-top:4px; overflow-wrap:anywhere; }}
table {{ width:100%; border-collapse:collapse; margin:12px 0 20px; }} th,td {{ text-align:left; vertical-align:top; padding:8px; border-bottom:1px solid var(--line); }}
.severity {{ font-size:.78rem; font-weight:700; text-transform:uppercase; }} .error {{ color:var(--bad); }} .warning {{ color:var(--warn); }} .info {{ color:var(--good); }}
details {{ border:1px solid var(--line); border-radius:8px; padding:10px 14px; margin:12px 0; }} summary {{ cursor:pointer; font-weight:700; }} li {{ margin:10px 0; }} pre {{ white-space:pre-wrap; overflow-wrap:anywhere; }}
</style>
<body>
<h1>Skill Forge report</h1>
<p class="muted">Rendered from validated recorded evidence; no tests or model calls occur during rendering.</p>
<section class="banner"><strong>{esc(report['verdict'])}</strong><br>{esc(derived['sufficiency_note'])}</section>
<section class="grid">{cards(report, derived)}</section>
<h2>Conditions</h2>{condition_table(derived['conditions'])}
<h2>Findings</h2>{finding_table(report['findings'])}
{details("Cases", report["cases"], ("case_id", "condition", "status", "wall_time_seconds", "tokens", "quality_score"))}
{details("Assertion diagnostics", derived["assertion_diagnostics"], ("case_id", "state"))}
{details("Failure clusters", report.get("failure_clusters", []), ("name", "count"))}
<details><summary>Run metadata and provenance</summary><pre>{esc(json.dumps(metadata, ensure_ascii=False, indent=2))}</pre></details>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        report = normalize(payload)
        document = render(report)
    except (OSError, json.JSONDecodeError, ReportError) as error:
        print(f"INVALID REPORT: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(document, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
