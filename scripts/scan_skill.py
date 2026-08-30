#!/usr/bin/env python3
"""Dependency-free static scanner for portable Agent Skill folders."""

from __future__ import annotations

import argparse
import ast
import json
import math
import platform
import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SCHEMA_VERSION = "2.0"
SCANNER_VERSION = "2.1.0"
MAX_TEXT_BYTES = 2_000_000
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)")
TEXT_ROUTE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s+|\d+\.\s+)?(?:read|use|see|follow)\s+"
    r"(?:the\s+)?(?:reference\s+)?(?:\x60(?P<quoted>[^\x60\n]+?\.md(?:#[^\x60\n]+)?)\x60|"
    r"(?P<bare>(?:\./)?references/[A-Za-z0-9_./-]+\.md(?:#[A-Za-z0-9_./-]+)?))"
)
TEXT_SUFFIXES = {".md", ".py", ".sh", ".yaml", ".yml", ".json", ".toml", ".txt"}
IGNORED_PARTS = {".git", ".skill-forge", "__pycache__", ".mypy_cache", ".pytest_cache"}
SUPPORTED_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    "openai_key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
MANUAL_ONLY_RE = re.compile(r"manual-only|only when explicitly invoked|explicit-only", re.I)
REFERENCE_LOAD_PREDICATE_RE = re.compile(r"^\s*(?:read|use)\s+this\s+reference\b", re.I)


def relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def add_finding(
    findings: list[dict[str, Any]],
    severity: str,
    code: str,
    category: str,
    message: str,
    path: str = ".",
    line: int | None = None,
    confidence: str = "high",
    evidence: str = "",
    remediation: str = "",
) -> None:
    item: dict[str, Any] = {
        "id": f"{code}:{path}:{line or 0}",
        "category": category,
        "severity": severity,
        "confidence": confidence,
        "status": "open",
        "code": code,
        "message": message,
        "path": path,
        "evidence": evidence,
        "remediation": remediation,
    }
    if line is not None:
        item["line"] = line
    findings.append(item)


def read_text(path: Path, findings: list[dict[str, Any]], root: Path) -> str | None:
    label = relative(path, root)
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            add_finding(
                findings, "warning", "text_file_too_large", "structure",
                "Text file exceeds the scan limit.", label,
                evidence=f"{path.stat().st_size} bytes",
                remediation="Move generated or raw data outside the distributed skill.",
            )
            return None
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        add_finding(
            findings, "error", "utf8", "structure", "File is not valid UTF-8.", label,
            evidence=str(error), remediation="Re-encode the file as UTF-8.",
        )
    except OSError as error:
        add_finding(
            findings, "error", "read_error", "structure", "File could not be read.", label,
            evidence=str(error), remediation="Fix permissions or remove the unreadable file.",
        )
    return None


def parse_scalar(raw: str) -> tuple[str, str | None]:
    value = raw.strip()
    if not value:
        return "", None
    if value.startswith('"'):
        try:
            return str(json.loads(value)), None
        except json.JSONDecodeError as error:
            return value, f"Invalid double-quoted scalar: {error.msg}."
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            return value, "Unterminated single-quoted scalar."
        return value[1:-1].replace("''", "'"), None
    if value.endswith(('"', "'")):
        return value, "Mismatched YAML quote."
    return value, None


def parse_frontmatter(
    text: str, findings: list[dict[str, Any]]
) -> tuple[dict[str, str], str, str]:
    if text.startswith("\ufeff"):
        add_finding(
            findings, "warning", "utf8_bom", "structure",
            "SKILL.md starts with a UTF-8 BOM.", "SKILL.md", 1,
            evidence="BOM before frontmatter", remediation="Remove the BOM for parser portability.",
        )
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        add_finding(
            findings, "error", "frontmatter_open", "frontmatter",
            "Frontmatter must start on line 1 with an exact --- delimiter.", "SKILL.md", 1,
            evidence=lines[0] if lines else "empty file",
            remediation="Put an exact --- delimiter on line 1.",
        )
        return {}, text, ""
    close = next((index for index in range(1, len(lines)) if lines[index] == "---"), None)
    if close is None:
        add_finding(
            findings, "error", "frontmatter_close", "frontmatter",
            "Frontmatter closing delimiter is missing.", "SKILL.md", 1,
            evidence="No exact closing --- line",
            remediation="Add a closing --- delimiter before the body.",
        )
        return {}, "", "\n".join(lines)

    fields: dict[str, str] = {}
    i = 1
    while i < close:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[0].isspace():
            add_finding(
                findings, "error", "frontmatter_orphan_indent", "frontmatter",
                "Indented content has no top-level owner.", "SKILL.md", i + 1,
                evidence=line.strip(), remediation="Attach it to a valid top-level key.",
            )
            i += 1
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):(?:[ \t]*(.*))?$", line)
        if not match:
            add_finding(
                findings, "error", "frontmatter_malformed_line", "frontmatter",
                "Malformed top-level frontmatter line.", "SKILL.md", i + 1,
                evidence=line, remediation="Use a key: value mapping.",
            )
            i += 1
            continue
        key, raw = match.group(1), (match.group(2) or "")
        if key in fields:
            add_finding(
                findings, "error", "frontmatter_duplicate_key", "frontmatter",
                f"Duplicate frontmatter key: {key}.", "SKILL.md", i + 1,
                evidence=line, remediation="Keep one authoritative value.",
            )
        if key not in SUPPORTED_FIELDS:
            add_finding(
                findings, "info", "frontmatter_unknown_field", "portability",
                f"Host-specific or unknown field: {key}.", "SKILL.md", i + 1, "medium",
                evidence=line, remediation="Confirm support in every target host.",
            )
        if re.fullmatch(r"[|>][+-]?", raw.strip()):
            style = raw.strip()[0]
            block: list[str] = []
            j = i + 1
            while j < close and (not lines[j].strip() or lines[j][0].isspace()):
                block.append(lines[j])
                j += 1
            indents = [len(item) - len(item.lstrip()) for item in block if item.strip()]
            indent = min(indents) if indents else 0
            parts = [item[indent:] if len(item) >= indent else "" for item in block]
            fields[key] = (
                "\n".join(parts).strip()
                if style == "|"
                else " ".join(part.strip() for part in parts).strip()
            )
            i = j
            continue
        value, error = parse_scalar(raw)
        if error:
            add_finding(
                findings, "error", "frontmatter_scalar", "frontmatter",
                error, "SKILL.md", i + 1, evidence=line,
                remediation="Use a valid plain, quoted, or block scalar.",
            )
        fields[key] = value
        if not raw.strip():
            j = i + 1
            nested = False
            while j < close and (not lines[j].strip() or lines[j][0].isspace()):
                nested = nested or bool(lines[j].strip())
                j += 1
            if nested and key in {"name", "description"}:
                add_finding(
                    findings, "error", "frontmatter_required_scalar", "frontmatter",
                    f"{key} must be a scalar string.", "SKILL.md", i + 1,
                    evidence=line, remediation=f"Provide a scalar {key}.",
                )
            elif nested:
                add_finding(
                    findings, "info", "unverified_yaml", "portability",
                    f"Nested YAML under {key} was not fully schema-validated.",
                    "SKILL.md", i + 1, "medium", line,
                    "Confirm nested fields against the target host schema.",
                )
            i = j
        else:
            i += 1
    return fields, "\n".join(lines[close + 1 :]), "\n".join(lines[: close + 1])


def strip_fences(text: str) -> str:
    return re.sub(r"\x60\x60\x60.*?\x60\x60\x60|~~~.*?~~~", "", text, flags=re.S)


def markdown_links(text: str) -> list[tuple[str, int]]:
    clean = strip_fences(text)
    output: list[tuple[str, int]] = []
    for match in LINK_RE.finditer(clean):
        target = match.group(1).strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        output.append((target, clean.count("\n", 0, match.start()) + 1))
    return output


def textual_routes(text: str) -> list[tuple[str, int]]:
    """Return only explicit imperative Markdown routes, never casual prose."""
    clean = strip_fences(text)
    output: list[tuple[str, int]] = []
    for match in TEXT_ROUTE_RE.finditer(clean):
        target = (match.group("quoted") or match.group("bare") or "").strip()
        if target:
            output.append((target, clean.count("\n", 0, match.start()) + 1))
    return output


def local_target(source: Path, raw: str) -> tuple[Path | None, str]:
    if raw.startswith("#"):
        return source, raw[1:]
    if re.match(r"^(?:https?://|mailto:|data:)", raw, re.I):
        return None, ""
    target, _, fragment = raw.split("?", 1)[0].partition("#")
    return ((source.parent / target).resolve() if target else source), fragment


def heading_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    counts: Counter[str] = Counter()
    for line in strip_fences(text).splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        heading = re.sub(r"<[^>]+>", "", match.group(1)).strip().lower()
        slug = re.sub(r"[^\w\- ]", "", heading, flags=re.UNICODE)
        slug = re.sub(r"[\s\-]+", "-", slug).strip("-")
        if slug:
            number = counts[slug]
            anchors.add(slug if number == 0 else f"{slug}-{number}")
            counts[slug] += 1
    return anchors


def parse_openai_paths(
    text: str, findings: list[dict[str, Any]]
) -> dict[str, tuple[str, int]]:
    values: dict[str, tuple[str, int]] = {}
    stack: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped.startswith("- "):
            add_finding(
                findings, "info", "unverified_openai_yaml", "metadata",
                "List-valued openai.yaml content was not fully schema-validated.",
                "agents/openai.yaml", number, "medium", stripped,
                "Confirm list fields against the current host schema.",
            )
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$", stripped)
        if not match:
            add_finding(
                findings, "warning", "openai_yaml_malformed_line", "metadata",
                "Could not validate an openai.yaml line.", "agents/openai.yaml",
                number, "medium", stripped, "Check it with the host YAML parser.",
            )
            continue
        key, raw = match.group(1), (match.group(2) or "")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        dotted = ".".join([item[1] for item in stack] + [key])
        if dotted in values:
            add_finding(
                findings, "error", "openai_yaml_duplicate_key", "metadata",
                f"Duplicate openai.yaml key: {dotted}.", "agents/openai.yaml",
                number, evidence=stripped, remediation="Keep one authoritative value.",
            )
        value, error = parse_scalar(raw)
        if error:
            add_finding(
                findings, "error", "openai_yaml_scalar", "metadata",
                error, "agents/openai.yaml", number, evidence=stripped,
                remediation="Use a valid scalar.",
            )
        values[dotted] = (value, number)
        if not raw:
            stack.append((indent, key))
    return values


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 4)


def called_name(node: ast.expr) -> str | None:
    """Return a direct Python call target without guessing from surrounding text."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return None


def build_result(
    root: Path,
    findings: list[dict[str, Any]],
    files_scanned: int,
    context_budget: dict[str, Any],
) -> dict[str, Any]:
    findings.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(item["severity"], 9),
            item.get("path", ""),
            item.get("line", 0),
            item["code"],
        )
    )
    counts = Counter(item["severity"] for item in findings)
    categories = Counter(item["category"] for item in findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "target": str(root),
        "target_type": "agent_skill",
        "passes": [
            "target_and_encoding",
            "frontmatter",
            "links_and_reachability",
            "openai_metadata",
            "ownership_signals",
            "security_and_side_effects",
            "dependencies_and_portability",
            "context_budget_estimate",
        ],
        "findings": findings,
        "summary": {
            "errors": counts["error"],
            "warnings": counts["warning"],
            "info": counts["info"],
            "by_category": dict(sorted(categories.items())),
        },
        "context_budget": context_budget,
        "provenance": {
            "scanner_version": SCANNER_VERSION,
            "python": platform.python_version(),
            "files_scanned": files_scanned,
            "network_calls": 0,
            "model_calls": 0,
            "estimate_note": "Character-based estimates are not observed token usage.",
        },
    }


def scan(root: Path) -> dict[str, Any]:
    root = root.resolve()
    findings: list[dict[str, Any]] = []
    empty_budget = {
        "method": "ceil(characters/4)",
        "discovery_estimated_tokens": 0,
        "core_estimated_tokens": 0,
        "deferred_estimated_tokens": 0,
        "deferred_by_file": [],
    }
    if not root.is_dir():
        add_finding(
            findings, "error", "target", "structure", "Target is not a directory.",
            str(root), evidence=str(root), remediation="Pass the exact skill directory.",
        )
        return build_result(root, findings, 0, empty_budget)

    skill_file = root / "SKILL.md"
    if not skill_file.is_file():
        add_finding(
            findings, "error", "missing_skill", "structure", "Missing required SKILL.md.",
            "SKILL.md", evidence="File does not exist",
            remediation="Create the required SKILL.md entrypoint.",
        )
        return build_result(root, findings, 0, empty_budget)

    files: list[Path] = []
    for path in root.rglob("*"):
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in IGNORED_PARTS for part in parts):
            continue
        if path.is_symlink():
            add_finding(
                findings, "warning", "symlink", "portability",
                "Symlinked resource requires host-specific review.", relative(path, root),
                confidence="medium", evidence=f"resolves to {path.resolve()}",
                remediation="Prefer an in-package file or document host support.",
            )
            continue
        if path.is_file():
            files.append(path)

    texts: dict[Path, str] = {}
    for path in sorted(files):
        if path.suffix.lower() in TEXT_SUFFIXES or path.name == "SKILL.md":
            text = read_text(path, findings, root)
            if text is not None:
                texts[path] = text
    skill_text = texts.get(skill_file)
    if skill_text is None:
        return build_result(root, findings, len(texts), empty_budget)

    fields, body, frontmatter_text = parse_frontmatter(skill_text, findings)
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name:
        add_finding(
            findings, "error", "name_missing", "frontmatter",
            "Missing frontmatter name.", "SKILL.md",
            remediation="Add a scalar name field.",
        )
    elif not NAME_RE.fullmatch(name) or len(name) > 64:
        add_finding(
            findings, "error", "name_format", "frontmatter",
            "Name must be lowercase kebab-case and at most 64 characters.",
            "SKILL.md", evidence=name, remediation="Use a short lowercase kebab-case name.",
        )
    elif name != root.name:
        add_finding(
            findings, "error", "name_match", "frontmatter",
            "Frontmatter name must match the directory name.", "SKILL.md",
            evidence=f"name={name}; directory={root.name}",
            remediation="Rename the field or directory so they match.",
        )
    if not description:
        add_finding(
            findings, "error", "description_missing", "frontmatter",
            "Missing frontmatter description.", "SKILL.md",
            remediation="Describe what the skill does and when it applies.",
        )
    elif len(description) > 1024:
        add_finding(
            findings, "warning", "description_length", "discovery",
            "Description exceeds 1024 characters.", "SKILL.md",
            evidence=f"{len(description)} characters",
            remediation="Keep routing metadata concise and discriminating.",
        )
    if len(body.splitlines()) > 500:
        add_finding(
            findings, "warning", "core_length", "context",
            "SKILL.md body exceeds 500 lines.", "SKILL.md", confidence="medium",
            evidence=f"{len(body.splitlines())} body lines",
            remediation="Move genuinely conditional detail to routed references.",
        )

    anchors = {
        path: heading_anchors(text)
        for path, text in texts.items()
        if path.suffix.lower() == ".md"
    }
    edges: dict[Path, set[Path]] = {}
    for source, text in texts.items():
        if source.suffix.lower() != ".md":
            continue
        routes = [(raw, line_number, "link") for raw, line_number in markdown_links(text)]
        routes.extend(
            (raw, line_number, "textual_route")
            for raw, line_number in textual_routes(text)
        )
        for raw, line_number, route_kind in routes:
            candidate, fragment = local_target(source, raw)
            if candidate is None:
                continue
            label = relative(source, root)
            if not candidate.is_relative_to(root):
                add_finding(
                    findings, "error",
                    "link_escape" if route_kind == "link" else "textual_route_escape",
                    "links",
                    "Local route escapes the target skill.", label, line_number,
                    evidence=raw, remediation="Use an in-package path or explicit external URL.",
                )
            elif not candidate.is_file():
                add_finding(
                    findings, "error",
                    "broken_link" if route_kind == "link" else "broken_textual_route",
                    "links",
                    "Routed local file is missing.", label, line_number,
                    evidence=raw, remediation="Fix the path or remove the stale link.",
                )
            elif candidate.suffix.lower() == ".md":
                edges.setdefault(source, set()).add(candidate)
                if fragment and fragment not in anchors.get(candidate, set()):
                    add_finding(
                        findings, "warning", "broken_anchor", "links",
                        "Markdown anchor was not found.", label, line_number, "medium",
                        raw, "Update the fragment to a current heading.",
                    )

    depths: dict[Path, int] = {skill_file: 0}
    queue: deque[Path] = deque([skill_file])
    while queue:
        source = queue.popleft()
        for target in edges.get(source, set()):
            if target not in depths:
                depths[target] = depths[source] + 1
                queue.append(target)
    references_dir = root / "references"
    if references_dir.is_dir():
        for reference in sorted(references_dir.rglob("*.md")):
            resolved = reference.resolve()
            if resolved not in depths:
                add_finding(
                    findings, "warning", "unreachable_reference", "ownership",
                    "Reference is not reachable from SKILL.md.", relative(reference, root),
                    evidence="No direct Markdown or textual route from SKILL.md",
                    remediation="Link it from its route or remove it.",
                )
            elif depths[resolved] > 1:
                add_finding(
                    findings, "warning", "deep_reference", "context",
                    "Reference needs more than one disclosure hop.", relative(reference, root),
                    confidence="medium", evidence=f"depth={depths[resolved]}",
                    remediation="Prefer a direct route from SKILL.md.",
                )
            reference_text = texts.get(reference)
            if reference_text is not None:
                for line_number, line in enumerate(reference_text.splitlines(), start=1):
                    if line.startswith("## "):
                        break
                    if REFERENCE_LOAD_PREDICATE_RE.search(line):
                        add_finding(
                            findings, "warning", "reference_load_predicate", "ownership",
                            "Reference repeats its own load predicate.", relative(reference, root),
                            line_number, "high", line.strip(),
                            "Move the load condition to the caller and start this file with post-load behavior.",
                        )
                        break

    openai_path = root / "agents" / "openai.yaml"
    openai_text = texts.get(openai_path)
    manual_only = bool(MANUAL_ONLY_RE.search(description + "\n" + body))
    if openai_text is not None:
        values = parse_openai_paths(openai_text, findings)
        policy, policy_line = values.get("policy.allow_implicit_invocation", ("", 0))
        if manual_only and policy.lower() != "false":
            add_finding(
                findings, "error", "manual_policy_mismatch", "discovery",
                "Explicit-only skill does not disable implicit invocation.",
                "agents/openai.yaml", policy_line or None,
                evidence=f"allow_implicit_invocation={policy or 'missing'}",
                remediation="Set policy.allow_implicit_invocation to false.",
            )
        if policy.lower() == "false" and not manual_only:
            add_finding(
                findings, "warning", "manual_policy_undocumented", "discovery",
                "Implicit invocation is disabled but the description does not disclose it.",
                "agents/openai.yaml", policy_line or None, "medium",
                "allow_implicit_invocation=false",
                "State the explicit-only boundary in the description.",
            )
        default_prompt, prompt_line = values.get("interface.default_prompt", ("", 0))
        invocation = "$" + name
        if name and default_prompt and invocation not in default_prompt:
            add_finding(
                findings, "warning", "default_prompt_invocation", "metadata",
                "Default prompt does not mention the skill invocation.",
                "agents/openai.yaml", prompt_line or None, evidence=default_prompt,
                remediation=f"Include {invocation} in default_prompt.",
            )
        short_description, short_line = values.get("interface.short_description", ("", 0))
        if short_description and not 25 <= len(short_description) <= 64:
            add_finding(
                findings, "warning", "short_description_length", "metadata",
                "short_description should be 25-64 characters.",
                "agents/openai.yaml", short_line or None,
                evidence=f"{len(short_description)} characters",
                remediation="Use a concise 25-64 character UI description.",
            )
    elif manual_only:
        add_finding(
            findings, "error", "manual_policy_missing_file", "discovery",
            "Explicit-only skill has no agents/openai.yaml.",
            "agents/openai.yaml", evidence="File does not exist",
            remediation="Add allow_implicit_invocation: false.",
        )

    normalized: Counter[str] = Counter()
    locations: dict[str, list[tuple[str, int]]] = {}
    for path, text in texts.items():
        if path.suffix.lower() != ".md":
            continue
        for number, line in enumerate(strip_fences(text).splitlines(), start=1):
            compact = re.sub(r"\s+", " ", line).strip()
            if len(compact) >= 70 and not compact.startswith(("#", "|")):
                normalized[compact] += 1
                locations.setdefault(compact, []).append((relative(path, root), number))
    for compact, count in normalized.items():
        distinct = sorted({item[0] for item in locations[compact]})
        if count > 1 and len(distinct) > 1:
            first_path, first_line = locations[compact][0]
            add_finding(
                findings, "warning", "duplicate_text", "ownership",
                "Exact long instruction appears in multiple files.",
                first_path, first_line, "medium", ", ".join(distinct),
                "Keep one owner and route to it where needed.",
            )

    shell_risks = (
        ("recursive_delete", re.compile(r"\brm\s+-[A-Za-z]*r[A-Za-z]*f\b|\brm\s+-[A-Za-z]*f[A-Za-z]*r\b")),
        ("pipe_to_shell", re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba|z|fi)?sh\b")),
    )
    side_effects = (
        ("git_push", re.compile(r"\bgit\s+push\b")),
        ("network_write", re.compile(r"\bcurl\b[^\n]*(?:POST|PUT|PATCH|DELETE)", re.I)),
        ("delete_command", re.compile(r"\brm\s+")),
    )
    injection_patterns = (
        re.compile(r"ignore (?:all )?(?:previous|prior) instructions", re.I),
        re.compile(r"reveal (?:the )?(?:system prompt|hidden instructions)", re.I),
    )
    local_modules: set[str] = set()
    for path in files:
        if path.suffix != ".py":
            continue
        parts = path.relative_to(root).parts
        local_modules.add(path.stem)
        if len(parts) > 1:
            local_modules.add(parts[0])
    dependency_declared = any(
        (root / candidate).is_file()
        for candidate in ("requirements.txt", "pyproject.toml")
    )
    stdlib_modules = getattr(sys, "stdlib_module_names", set())

    for path, text in texts.items():
        label = relative(path, root)
        for secret_name, pattern in SECRET_PATTERNS.items():
            match = pattern.search(text)
            if match:
                add_finding(
                    findings, "error", f"secret_{secret_name}", "security",
                    "Secret-like credential detected.", label,
                    text.count("\n", 0, match.start()) + 1,
                    evidence=f"matched {secret_name}; value redacted",
                    remediation="Remove and rotate the credential.",
                )
        if path.suffix.lower() == ".md":
            for pattern in injection_patterns:
                match = pattern.search(text)
                if match:
                    add_finding(
                        findings, "warning", "prompt_injection_like", "security",
                        "Prompt-injection-like wording needs contextual review.",
                        label, text.count("\n", 0, match.start()) + 1, "medium",
                        match.group(0),
                        "Remove executable hostile instructions or quarantine quoted content.",
                    )
        if path.suffix.lower() in {".py", ".sh"}:
            for risk_name, pattern in shell_risks:
                match = pattern.search(text)
                if match:
                    add_finding(
                        findings, "warning", f"shell_risk_{risk_name}", "side_effects",
                        "Potentially unsafe executable construct needs review.",
                        label, text.count("\n", 0, match.start()) + 1, "medium",
                        match.group(0),
                        "Validate exact targets, authority, stop conditions, and recovery.",
                    )
            for effect_name, pattern in side_effects:
                match = pattern.search(text)
                if match:
                    add_finding(
                        findings, "warning", f"side_effect_{effect_name}", "side_effects",
                        "Script contains a state-changing or external command.",
                        label, text.count("\n", 0, match.start()) + 1, "medium",
                        match.group(0),
                        "Confirm that core discloses scope, approval, and recovery.",
                    )
        if path.suffix.lower() == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError as error:
                add_finding(
                    findings, "error", "python_syntax", "scripts",
                    "Python script does not parse.", label, error.lineno,
                    evidence=error.msg, remediation="Fix syntax before distribution.",
                )
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                target = called_name(node.func)
                if target in {"eval", "exec", "builtins.eval", "builtins.exec"}:
                    add_finding(
                        findings, "warning", "shell_risk_dynamic_eval", "side_effects",
                        "Script calls Python dynamic evaluation.", label, node.lineno,
                        "high", target,
                        "Avoid dynamic execution or tightly validate the input and authority.",
                    )
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".", 1)[0])
            third_party = sorted(
                item for item in imported
                if item not in stdlib_modules
                and item not in local_modules
                and item != "__future__"
            )
            if third_party and not dependency_declared:
                add_finding(
                    findings, "warning", "undeclared_dependency", "dependencies",
                    "Python imports non-stdlib modules without a declaration.",
                    label, confidence="high", evidence=", ".join(third_party),
                    remediation="Declare the dependency or use the standard library.",
                )

    deferred: list[dict[str, Any]] = []
    deferred_total = 0
    for path, text in sorted(texts.items()):
        if path in {skill_file, openai_path}:
            continue
        tokens = estimate_tokens(text)
        deferred_total += tokens
        deferred.append({"path": relative(path, root), "estimated_tokens": tokens})
    discovery = frontmatter_text + (f"\n{openai_text}" if openai_text else "")
    budget = {
        "method": "ceil(characters/4)",
        "discovery_estimated_tokens": estimate_tokens(discovery),
        "core_estimated_tokens": estimate_tokens(body),
        "deferred_estimated_tokens": deferred_total,
        "deferred_by_file": deferred,
        "policy": "Deferred resources are separate estimates, not loaded-context penalties.",
    }
    return build_result(root, findings, len(texts), budget)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument(
        "--output", type=Path,
        help="Write JSON only to this explicit path; otherwise use stdout.",
    )
    args = parser.parse_args()
    report = scan(args.target)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 1 if report["summary"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
