#!/usr/bin/env python3
"""Fail fast on structural errors reported by the Skill Forge scanner."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import scan_skill


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("--json", action="store_true", help="Print the complete scan payload.")
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Also return non-zero for reviewed CI policies that treat warnings as blockers.",
    )
    args = parser.parse_args()
    report = scan_skill.scan(args.target)
    if report.get("schema_version") != scan_skill.SCHEMA_VERSION:
        print("ERROR scanner_schema: unexpected scanner result schema.", file=sys.stderr)
        return 2

    errors = [item for item in report["findings"] if item["severity"] == "error"]
    warnings = [item for item in report["findings"] if item["severity"] == "warning"]
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif errors or (args.fail_on_warning and warnings):
        for item in errors + (warnings if args.fail_on_warning else []):
            location = item.get("path", ".")
            if item.get("line"):
                location += f":{item['line']}"
            print(
                f"{item['severity'].upper()} {item['code']} ({location}): {item['message']}",
                file=sys.stderr,
            )
    else:
        print(
            f"OK: {args.target} has no structural errors "
            f"({len(warnings)} judgment-required warning(s))."
        )
    return 1 if errors or (args.fail_on_warning and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())

