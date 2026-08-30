#!/usr/bin/env python3
"""Audit an explicitly scoped collection of Agent Skills without network calls."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

sys.dont_write_bytecode = True

SCHEMA_VERSION = "1.0"
MAX_SKILLS_DEFAULT = 500
IGNORED_PARTS = {".git", ".skill-forge", "__pycache__", ".mypy_cache", ".pytest_cache"}
MANUAL_ONLY_RE = re.compile(
    r"manual-only|only when explicitly invoked|explicit-only", re.IGNORECASE
)
POLICY_RE = re.compile(
    r"(?m)^\s*allow_implicit_invocation:\s*(true|false)\s*$", re.IGNORECASE
)
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.IGNORECASE)
ROUTING_STOPWORDS = {
    "agent", "agents", "audit", "build", "codex", "create", "explicitly",
    "improve", "only", "skill", "skills", "the", "this", "use", "when",
}


def add_finding(
    findings: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    paths: list[str],
    evidence: str,
    remediation: str,
) -> None:
    findings.append(
        {
            "id": f"{code}:{'|'.join(sorted(paths))}",
            "category": "catalog",
            "severity": severity,
            "confidence": "medium",
            "status": "open",
            "code": code,
            "message": message,
            "paths": sorted(paths),
            "evidence": evidence,
            "remediation": remediation,
        }
    )


def frontmatter_fields(text: str) -> dict[str, str]:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0] != "---":
        return {}
    try:
        close = lines.index("---", 1)
    except ValueError:
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:close]:
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            try:
                value = str(json.loads(value))
            except json.JSONDecodeError:
                pass
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("''", "'")
        fields.setdefault(key, value)
    return fields


def description_tokens(description: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(description)
        if token.lower() not in ROUTING_STOPWORDS
    }


def iter_skill_files(root: Path) -> Iterator[Path]:
    for directory, children, filenames in os.walk(root):
        children[:] = [
            child for child in children
            if child not in IGNORED_PARTS
        ]
        if "SKILL.md" in filenames:
            yield Path(directory) / "SKILL.md"


def record_for(skill_file: Path, scope: Path) -> dict[str, Any]:
    text = skill_file.read_text(encoding="utf-8")
    fields = frontmatter_fields(text)
    description = fields.get("description", "")
    openai_path = skill_file.parent / "agents" / "openai.yaml"
    policy = "unknown"
    if openai_path.is_file():
        match = POLICY_RE.search(openai_path.read_text(encoding="utf-8"))
        if match:
            policy = match.group(1).lower()
    return {
        "path": str(skill_file.parent),
        "scope": str(scope),
        "name": fields.get("name", ""),
        "description": description,
        "description_tokens": sorted(description_tokens(description)),
        "manual_only": bool(MANUAL_ONLY_RE.search(description)),
        "allow_implicit_invocation": policy,
    }


def scan(roots: list[Path], max_skills: int = MAX_SKILLS_DEFAULT) -> dict[str, Any]:
    if not roots:
        raise ValueError("At least one explicit catalog root is required.")
    findings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    seen: set[Path] = set()
    limit_reached = False

    for scope in roots:
        resolved_scope = scope.resolve()
        if not resolved_scope.is_dir():
            add_finding(
                findings, "error", "catalog_root_missing",
                "Catalog root is not a readable directory.", [str(scope)],
                str(scope), "Pass an exact existing skill directory or catalog root.",
            )
            continue
        for skill_file in iter_skill_files(resolved_scope):
            resolved = skill_file.parent.resolve()
            if resolved in seen:
                continue
            if len(records) >= max_skills:
                limit_reached = True
                break
            seen.add(resolved)
            try:
                records.append(record_for(skill_file, resolved_scope))
            except (OSError, UnicodeDecodeError) as error:
                add_finding(
                    findings, "warning", "catalog_unreadable_skill",
                    "Skill metadata could not be read for catalog comparison.",
                    [str(skill_file.parent)], str(error),
                    "Repair encoding or inspect the skill with the detailed static scanner.",
                )
        if limit_reached:
            break

    if limit_reached:
        add_finding(
            findings, "warning", "catalog_limit_reached",
            "Catalog scan stopped at its explicit skill limit.", [str(root) for root in roots],
            f"max_skills={max_skills}",
            "Narrow the supplied roots or raise --max-skills after reviewing scope.",
        )

    by_name: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        name = record["name"]
        if not name:
            add_finding(
                findings, "warning", "catalog_missing_name",
                "Skill has no readable frontmatter name for collision analysis.",
                [record["path"]], "name is empty",
                "Fix the skill first, then rerun the detailed static scanner.",
            )
            continue
        by_name.setdefault(name, []).append(record)
    for name, group in sorted(by_name.items()):
        if len(group) > 1:
            paths = [item["path"] for item in group]
            policies = {item["allow_implicit_invocation"] for item in group}
            add_finding(
                findings, "warning", "catalog_duplicate_name",
                "Multiple scoped skills share one name; host precedence may shadow one.",
                paths, f"name={name}",
                "Keep one canonical name per load scope or document host precedence.",
            )
            if len(policies) > 1:
                add_finding(
                    findings, "warning", "catalog_manual_policy_conflict",
                    "Same-name skills declare different implicit-invocation policies.",
                    paths, ", ".join(sorted(policies)),
                    "Align policies or keep the variants in mutually exclusive scopes.",
                )

    for index, left in enumerate(records):
        left_tokens = set(left["description_tokens"])
        if len(left_tokens) < 3:
            continue
        for right in records[index + 1:]:
            right_tokens = set(right["description_tokens"])
            union = left_tokens | right_tokens
            shared = left_tokens & right_tokens
            overlap = len(shared) / len(union) if union else 0.0
            if len(shared) >= 3 and overlap >= 0.60:
                add_finding(
                    findings, "info", "catalog_description_overlap",
                    "Descriptions have a high lexical overlap; review trigger boundaries.",
                    [left["path"], right["path"]],
                    f"shared={', '.join(sorted(shared))}; jaccard={overlap:.2f}",
                    "This is not a collision proof; compare positive and near-miss triggers.",
                )

    findings.sort(key=lambda item: (item["severity"] != "error", item["code"], item["id"]))
    counts = Counter(item["severity"] for item in findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "target": " | ".join(str(root.resolve()) for root in roots),
        "target_type": "skill_catalog",
        "roots": [str(root.resolve()) for root in roots],
        "skills": records,
        "findings": findings,
        "summary": {
            "skills": len(records),
            "errors": counts["error"],
            "warnings": counts["warning"],
            "info": counts["info"],
        },
        "provenance": {
            "network_calls": 0,
            "model_calls": 0,
            "scope_note": "Only explicitly supplied roots were traversed.",
            "overlap_note": "Description overlap is a review signal, not a semantic collision verdict.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--max-skills", type=int, default=MAX_SKILLS_DEFAULT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.max_skills < 1:
        print("INVALID CATALOG PLAN: --max-skills must be positive.", file=sys.stderr)
        return 2
    try:
        report = scan(args.roots, args.max_skills)
    except ValueError as error:
        print(f"INVALID CATALOG PLAN: {error}", file=sys.stderr)
        return 2
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
