from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import eval_plan
import render_report
import scan_catalog
import scan_skill
import train_plan
import training_ledger


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_skill(base: Path, body: str = "", description: str | None = None) -> Path:
    root = base / "demo-skill"
    root.mkdir(parents=True)
    description = description or (
        "Audit a demo skill. Use only when explicitly invoked as $demo-skill."
    )
    write(
        root / "SKILL.md",
        f"---\nname: demo-skill\ndescription: {description}\n---\n\n# Demo skill\n\n{body}\n",
    )
    write(
        root / "agents" / "openai.yaml",
        'interface:\n'
        '  display_name: "Demo Skill"\n'
        '  short_description: "Create and audit a portable skill"\n'
        '  default_prompt: "Use $demo-skill to audit this target."\n\n'
        'policy:\n'
        '  allow_implicit_invocation: false\n',
    )
    return root


class ScannerTests(unittest.TestCase):
    def codes(self, report: dict) -> set[str]:
        return {item["code"] for item in report["findings"]}

    def test_clean_skill_and_anchor_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(
                Path(temp),
                "Read [the guide](references/guide.md#guide) when detailed checks are needed.",
            )
            write(root / "references" / "guide.md", "# Guide\n\nSpecific checks.\n")
            report = scan_skill.scan(root)
            self.assertEqual(report["summary"]["errors"], 0)
            self.assertNotIn("broken_anchor", self.codes(report))
            self.assertEqual(report["provenance"]["network_calls"], 0)
            self.assertEqual(report["provenance"]["model_calls"], 0)

    def test_scan_is_read_only_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(Path(temp))
            before = sorted(path.relative_to(root) for path in root.rglob("*"))
            scan_skill.scan(root)
            after = sorted(path.relative_to(root) for path in root.rglob("*"))
            self.assertEqual(before, after)
            self.assertFalse((root / ".skill-forge").exists())

    def test_malformed_and_duplicate_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "demo-skill"
            root.mkdir()
            write(
                root / "SKILL.md",
                "---\nname: demo-skill\nname: second\nmalformed line\ndescription: x\n---\n",
            )
            codes = self.codes(scan_skill.scan(root))
            self.assertIn("frontmatter_duplicate_key", codes)
            self.assertIn("frontmatter_malformed_line", codes)

    def test_links_orphans_and_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(
                Path(temp),
                "[missing](references/missing.md) and [outside](../outside.md).",
            )
            write(root / "references" / "orphan.md", "# Orphan\n")
            codes = self.codes(scan_skill.scan(root))
            self.assertIn("broken_link", codes)
            self.assertIn("link_escape", codes)
            self.assertIn("unreachable_reference", codes)

    def test_reference_load_predicate_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(Path(temp), "[guide](references/guide.md).")
            write(
                root / "references" / "guide.md",
                "# Guide\n\nRead this reference only when detailed checks are needed.\n",
            )
            self.assertIn("reference_load_predicate", self.codes(scan_skill.scan(root)))

    def test_explicit_textual_route_reaches_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(
                Path(temp),
                "Use \x60references/guide.md\x60 for deterministic checks.",
            )
            write(root / "references" / "guide.md", "# Guide\n\nDo the checks.\n")
            codes = self.codes(scan_skill.scan(root))
            self.assertNotIn("unreachable_reference", codes)
            self.assertNotIn("broken_textual_route", codes)

    def test_broken_textual_route_is_distinct_from_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(Path(temp), "Read \x60references/missing.md\x60 now.")
            self.assertIn("broken_textual_route", self.codes(scan_skill.scan(root)))

    def test_secret_and_unsafe_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(Path(temp))
            token = "sk-" + ("A" * 24)
            command = "r" + "m " + "-rf /tmp/skill-forge-example"
            write(root / "scripts" / "risky.py", f'TOKEN = "{token}"\nCOMMAND = "{command}"\n')
            codes = self.codes(scan_skill.scan(root))
            self.assertIn("secret_openai_key", codes)
            self.assertIn("shell_risk_recursive_delete", codes)
            self.assertIn("side_effect_delete_command", codes)

    def test_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(Path(temp), "Read [bad](references/bad.md).")
            bad = root / "references" / "bad.md"
            bad.parent.mkdir(parents=True, exist_ok=True)
            bad.write_bytes(b"\xff\xfe")
            report = scan_skill.scan(root)
            self.assertIn("utf8", self.codes(report))

    def test_manual_policy_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(Path(temp))
            write(
                root / "agents" / "openai.yaml",
                'interface:\n'
                '  short_description: "Create and audit a portable skill"\n'
                '  default_prompt: "Use $demo-skill to audit this target."\n'
                'policy:\n'
                '  allow_implicit_invocation: true\n',
            )
            self.assertIn("manual_policy_mismatch", self.codes(scan_skill.scan(root)))

    def test_context_buckets_do_not_claim_observed_usage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(
                Path(temp), "Read [guide](references/guide.md) only for advanced work."
            )
            write(root / "references" / "guide.md", "# Guide\n\n" + ("detail " * 200))
            report = scan_skill.scan(root)
            budget = report["context_budget"]
            self.assertGreater(budget["deferred_estimated_tokens"], 0)
            self.assertIn("not loaded-context penalties", budget["policy"])
            self.assertIn("not observed", report["provenance"]["estimate_note"])

    def test_python_risk_checks_use_ast_and_local_package_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(Path(temp))
            write(root / "scripts" / "__init__.py", "")
            write(root / "scripts" / "helpers.py", "VALUE = 1\n")
            write(
                root / "scripts" / "runner.py",
                "import helpers\nfrom scripts.helpers import VALUE\n"
                "# This evaluation note is prose, not a dynamic call.\n"
                "def evaluate() -> int:\n    return VALUE\n",
            )
            codes = self.codes(scan_skill.scan(root))
            self.assertNotIn("undeclared_dependency", codes)
            self.assertNotIn("shell_risk_dynamic_eval", codes)
            write(root / "scripts" / "dynamic.py", "result = eval('1 + 1')\n")
            self.assertIn("shell_risk_dynamic_eval", self.codes(scan_skill.scan(root)))


class EvalPlanTests(unittest.TestCase):
    def plan(self) -> dict:
        return {
            "candidate_version": "candidate-hash",
            "baseline_version": "without-skill",
            "eval_set_version": "cases-hash",
            "worker": {"model": "gpt-5.6-luna", "reasoning_effort": "high"},
            "judge_mode": "blind_pairwise",
            "judge": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
            "judge_stronger_confirmed": True,
            "judge_strength_basis": "Sol is the stronger independent reasoning judge.",
            "conditions": ["baseline", "with_skill"],
            "cases": [
                {"case_id": "one", "holdout": False},
                {"case_id": "two", "holdout": False},
                {"case_id": "three", "holdout": True},
            ],
            "runs_per_case": 1,
            "concurrency": 2,
            "timeout_seconds": 300,
            "token_budget": 100000,
            "time_budget_seconds": 3600,
            "stop_condition": "Stop after one repeated infrastructure failure.",
            "clean_context_per_run": True,
            "isolated_workspace_per_run": True,
            "conditions_equivalent": True,
        }

    def test_explicit_models_and_call_count(self) -> None:
        result = eval_plan.validate(self.plan())
        self.assertEqual(result["estimated_calls"], {"worker": 6, "judge": 3, "total": 9})
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["model_calls"], 0)

    def test_missing_judge_is_rejected(self) -> None:
        plan = self.plan()
        del plan["judge"]
        with self.assertRaises(eval_plan.PlanError):
            eval_plan.validate(plan)

    def test_same_worker_and_judge_is_disclosed(self) -> None:
        plan = self.plan()
        plan["judge"] = dict(plan["worker"])
        result = eval_plan.validate(plan)
        self.assertTrue(any("identical" in item for item in result["warnings"]))

    def test_unconfirmed_judge_strength_is_rejected(self) -> None:
        plan = self.plan()
        plan["judge_stronger_confirmed"] = False
        with self.assertRaises(eval_plan.PlanError):
            eval_plan.validate(plan)


class TrainPlanTests(unittest.TestCase):
    def plan(self) -> dict:
        return {
            "target_version": "candidate-skill-hash",
            "baseline_version": "baseline-skill-hash",
            "eval_set_version": "cases-hash",
            "worker": {"model": "gpt-5.6-luna", "reasoning_effort": "high"},
            "judge_mode": "blind_pairwise",
            "judge": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
            "judge_stronger_confirmed": True,
            "judge_strength_basis": "Independent stronger reasoning model.",
            "developer_cases": ["routing", "links"],
            "final_holdout_cases": ["hostile-context"],
            "candidate_batch_size": 2,
            "max_rounds": 25,
            "minimum_candidate_evaluations": 50,
            "max_no_improvement_rounds": 2,
            "developer_runs_per_case": 1,
            "final_runs_per_case": 1,
            "concurrency": 2,
            "token_budget": 100000,
            "time_budget_seconds": 3600,
            "protected_metrics": ["correctness", "tokens"],
            "hard_gates": ["static_errors_zero", "no_secret"],
            "stop_condition": "Stop after two rounds without an eligible improvement.",
            "conditions_equivalent": True,
            "active_skill_immutable": True,
            "promotion_requires_explicit_approval": True,
            "final_holdout_access": "blocked_during_authoring",
            "early_stop": {
                "allowed": True,
                "requires_pareto_eligibility": True,
                "requires_full_developer_panel": True,
                "requires_blind_judgment": True,
                "requires_final_holdout": True,
                "minimum_confirmation_repeats": 3,
                "required_metric_improvements": ["correctness non-inferior"],
            },
        }

    def test_train_plan_reports_bounded_maximum(self) -> None:
        result = train_plan.validate(self.plan())
        self.assertEqual(result["max_candidates"], 50)
        self.assertEqual(result["minimum_candidate_evaluations"], 50)
        self.assertEqual(result["estimated_calls"]["total_max"], 123)
        self.assertEqual(result["model_calls"], 0)

    def test_overlapping_holdout_is_rejected(self) -> None:
        plan = self.plan()
        plan["final_holdout_cases"] = ["links"]
        with self.assertRaises(train_plan.PlanError):
            train_plan.validate(plan)

    def test_train_plan_rejects_a_short_candidate_floor(self) -> None:
        plan = self.plan()
        plan["minimum_candidate_evaluations"] = 49
        with self.assertRaises(train_plan.PlanError):
            train_plan.validate(plan)

    def test_train_plan_rejects_an_unproven_early_stop(self) -> None:
        plan = self.plan()
        plan["early_stop"]["minimum_confirmation_repeats"] = 2
        with self.assertRaises(train_plan.PlanError):
            train_plan.validate(plan)


class CatalogTests(unittest.TestCase):
    def test_catalog_reports_same_name_and_policy_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "catalog"
            for directory, policy in (("first", "false"), ("second", "true")):
                root = base / directory
                write(
                    root / "SKILL.md",
                    "---\nname: shared-skill\n"
                    "description: Inspect structured target paths and checks.\n"
                    "---\n# Shared\n",
                )
                write(
                    root / "agents" / "openai.yaml",
                    f"policy:\n  allow_implicit_invocation: {policy}\n",
                )
            report = scan_catalog.scan([base])
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("catalog_duplicate_name", codes)
            self.assertIn("catalog_manual_policy_conflict", codes)
            self.assertEqual(report["provenance"]["network_calls"], 0)


class TrainingLedgerTests(unittest.TestCase):
    def test_snapshot_excludes_internal_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "demo-skill"
            write(root / "SKILL.md", "# Demo\n")
            write(root / ".skill-forge" / "report.json", "{}\n")
            write(root / ".DS_Store", "host metadata\n")
            snapshot = training_ledger.snapshot(root)
            self.assertEqual(snapshot["file_count"], 1)
            self.assertEqual(snapshot["files"][0]["path"], "SKILL.md")

    def test_frontier_respects_gates_and_tradeoffs(self) -> None:
        result = training_ledger.frontier(
            {
                "directions": {"diversity": "max", "tokens": "min"},
                "candidates": [
                    {
                        "candidate_id": "balanced",
                        "mutation": {
                            "summary": "Add an explicit diversity check.",
                            "requirement_ids": ["R-001"],
                        },
                        "gates": {"static": True},
                        "metrics": {"diversity": 0.8, "tokens": 100},
                    },
                    {
                        "candidate_id": "dominated",
                        "mutation": {
                            "summary": "Add redundant wording.",
                            "requirement_ids": ["R-001"],
                        },
                        "gates": {"static": True},
                        "metrics": {"diversity": 0.7, "tokens": 110},
                    },
                    {
                        "candidate_id": "tradeoff",
                        "mutation": {
                            "summary": "Add a separate evidence route.",
                            "requirement_ids": ["R-002"],
                        },
                        "gates": {"static": True},
                        "metrics": {"diversity": 0.9, "tokens": 150},
                    },
                    {
                        "candidate_id": "blocked",
                        "mutation": {
                            "summary": "Use an unsafe command.",
                            "requirement_ids": ["R-003"],
                        },
                        "gates": {"static": False},
                        "metrics": {"diversity": 1.0, "tokens": 10},
                    },
                ],
            }
        )
        self.assertEqual(
            {item["candidate_id"] for item in result["pareto_frontier"]},
            {"balanced", "tradeoff"},
        )
        self.assertEqual(
            result["candidates_rejected_by_gate"][0]["candidate_id"], "blocked"
        )


class ReportTests(unittest.TestCase):
    def eval_report(self, paired: int = 3) -> dict:
        cases = []
        for index in range(paired):
            case_id = f"case-{index}"
            cases.extend(
                [
                    {
                        "case_id": case_id,
                        "condition": "baseline",
                        "status": "pass",
                        "wall_time_seconds": 10 + index,
                        "tokens": 1000 + index,
                        "quality_score": 6 + index,
                        "evidence": "baseline artifact",
                    },
                    {
                        "case_id": case_id,
                        "condition": "with_skill",
                        "status": "pass",
                        "wall_time_seconds": 9 + index,
                        "tokens": 1100 + index,
                        "quality_score": 7 + index,
                        "evidence": "candidate artifact",
                    },
                ]
            )
        return {
            "report_type": "eval",
            "verdict": "Candidate is directionally better.",
            "metadata": {
                "candidate_version": "candidate-hash",
                "eval_set_version": "cases-hash",
                "conditions_equivalent": True,
                "worker_model": "gpt-5.6-luna high",
                "judge_model": "gpt-5.6-sol high",
            },
            "findings": [],
            "cases": cases,
        }

    def test_comparable_is_derived_from_three_pairs(self) -> None:
        report = render_report.normalize(self.eval_report(3))
        derived = render_report.summarize(report)
        self.assertEqual(derived["evidence_level"], "comparable")
        self.assertEqual(derived["paired_cases"], 3)
        self.assertNotEqual(
            derived["conditions"]["baseline"]["p90_latency_seconds"],
            "insufficient",
        )

    def test_caller_cannot_force_sufficiency(self) -> None:
        payload = self.eval_report(1)
        payload["data_sufficient"] = True
        derived = render_report.summarize(render_report.normalize(payload))
        self.assertEqual(derived["evidence_level"], "directional")

    def test_invalid_status_is_rejected(self) -> None:
        payload = self.eval_report(1)
        payload["cases"][0]["status"] = "crash"
        with self.assertRaises(render_report.ReportError):
            render_report.normalize(payload)

    def test_static_scan_can_render_as_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = create_skill(Path(temp))
            report = render_report.normalize(scan_skill.scan(root))
            document = render_report.render(report)
            self.assertIn("Static evidence only", document)
            self.assertIn("Skill Forge report", document)

    def test_assertion_diagnostics_label_non_discrimination_and_instability(self) -> None:
        payload = self.eval_report(1)
        payload["cases"][0]["assertions"] = [
            {"assertion_id": "route", "outcome": "pass"}
        ]
        payload["cases"][1]["assertions"] = [
            {"assertion_id": "route", "outcome": "pass"}
        ]
        derived = render_report.summarize(render_report.normalize(payload))
        self.assertEqual(
            derived["assertion_diagnostic_counts"]["non_discriminating"], 1
        )

        payload = self.eval_report(1)
        payload["cases"].append(
            {
                "case_id": "case-0",
                "condition": "baseline",
                "status": "pass",
                "assertions": [{"assertion_id": "route", "outcome": "fail"}],
            }
        )
        payload["cases"][0]["assertions"] = [
            {"assertion_id": "route", "outcome": "pass"}
        ]
        payload["cases"][1]["assertions"] = [
            {"assertion_id": "route", "outcome": "pass"}
        ]
        derived = render_report.summarize(render_report.normalize(payload))
        self.assertEqual(derived["assertion_diagnostic_counts"]["unstable"], 1)

    def test_renderer_escapes_hostile_recorded_evidence(self) -> None:
        payload = self.eval_report(1)
        payload["findings"] = [
            {
                "severity": "warning",
                "code": "hostile_evidence",
                "message": "<img src=x onerror=alert(1)>",
                "evidence": "<script>alert(1)</script>",
            }
        ]
        document = render_report.render(render_report.normalize(payload))
        self.assertNotIn("<img src=x", document)
        self.assertNotIn("<script>alert(1)</script>", document)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", document)


class DependencyTests(unittest.TestCase):
    def test_static_helpers_have_no_network_or_model_clients(self) -> None:
        banned = {"requests", "httpx", "socket", "openai", "anthropic"}
        for path in SCRIPTS.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".", 1)[0])
            self.assertFalse(imported & banned, f"{path.name}: {imported & banned}")


if __name__ == "__main__":
    unittest.main()
