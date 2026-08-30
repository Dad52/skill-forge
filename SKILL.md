---
name: skill-forge
description: Use only when explicitly invoked as $skill-forge to create, improve, audit, train, or explicitly evaluate portable Agent Skills for Codex while avoiding common Skill Creator pitfalls. Do not use for ordinary coding, publishing, or automatic changes.
---

# Skill Forge

Build small, testable decision aids rather than collections of generic prompt advice. Work only after the user invokes `$skill-forge`.

## Boundaries

- Start from the target and a compact contract; do not draft before understanding the recurring task.
- Treat create, improve, audit, evaluate, catalog, and train as internal routes, not user-facing modes.
- Do not change skill contents until the user explicitly authorizes `apply` or an equivalent exact mutation.
- An explicit audit may write only audit artifacts under `<target>/.skill-forge/`. Without that authorization, scan to stdout or a temporary directory.
- Run no model, network, package-install, publication, or external-action step unless separately authorized.
- Run behavioral EVALs only when the user explicitly asks to test, measure, benchmark, or compare.
- Run training only when the user explicitly asks to train or iteratively improve a named skill.
- Report individual findings with evidence and uncertainty. Never manufacture a composite quality percentage.
- Do not claim that a static check proves behavioral quality, security, portability, or token savings.

## Workflow

### 1. Contract and risk

Identify the route and establish only facts that change the result:

- recurring outcome, target users, trigger, and nearest non-trigger;
- allowed reads, writes, external actions, runtimes, and dependencies;
- observable completion criteria and exact target directory;
- risk tier: low for read-only guidance, medium for workspace mutation, high for external or destructive effects.

Say when a skill is unnecessary and recommend the smaller alternative. For creation, material redesign, or mixed responsibilities, read [contract and design](references/contract-and-design.md).

For an explicit catalog audit, consolidation, or host-compatibility question,
read [catalog and hosts](references/catalog-and-hosts.md). For an explicit
iterative improvement request, read [train workflow](references/training.md)
before proposing candidates or model calls.

### 2. Ownership before prose

Create a map before drafting:

| Requirement ID | Owner | Location | Verification |
|---|---|---|---|
| `R-001` shared routing/workflow | core | `SKILL.md` | positive and near-miss trigger cases |
| `R-002` conditional decision detail | one reference | `references/*.md` | reachable link and load condition |
| `R-003` deterministic operation | one script | `scripts/*.py` | local test with observable result |

One rule has one owner. A reference-load predicate belongs only to its caller
(normally `SKILL.md`): do not repeat “read/use this reference when …” or the
route description inside the reference itself. A reference starts with the
instructions that apply after it is open. Do not add a reference, script,
template, example, or agent merely to make the package look complete. Preserve
useful existing behavior unless a contract row or observed failure justifies
its removal.

Use a script only for a deterministic operation that replaces repeated model
work or establishes a testable invariant. Name its input, output, failure
behavior, side effect, and local test. Keep semantic decisions, unreviewed
rewrites, and model calls visible in the workflow.

### 3. Static health

For create, improve, and audit, run the dependency-free checks against the target. Default to stdout so a nominally read-only review creates nothing:

```bash
python3 <skill-forge-dir>/scripts/scan_skill.py <target-skill>
python3 <skill-forge-dir>/scripts/validate_structure.py <target-skill>
```

For an explicitly requested audit, a reproducible artifact is allowed:

```bash
python3 <skill-forge-dir>/scripts/scan_skill.py <target-skill> \
  --output <target-skill>/.skill-forge/static-scan.json
```

Read [static health](references/static-health.md) before interpreting audit findings or changing a risky skill. An error blocks release. A heuristic warning requires contextual review; record accepted false positives rather than rewriting blindly. Context-budget estimates distinguish discovery, core, and deferred resources and never penalize an unread file as if it were loaded.

For an explicitly requested catalog review, inspect only the supplied roots:

~~~
python3 <skill-forge-dir>/scripts/scan_catalog.py <explicit-catalog-root>
~~~

Do not use catalog overlap as authority to delete, merge, or retire a skill.

### 4. Proposal and apply

For creation, show the proposed tree, contract, ownership map, and essential contents. For improvement, show a minimal diff and connect each edit to a requirement, finding, or reproduced failure. For audit, show findings without modifying the target.

Stop before mutation unless the user authorized apply. After apply, rerun structural checks and the smallest relevant deterministic tests. Do not perform unrelated cleanup.

After an authorized apply, record a content fingerprint before reporting
success:

~~~
python3 <skill-forge-dir>/scripts/training_ledger.py snapshot \
  --target <target-skill> \
  --output <target-skill>/.skill-forge/provenance.json
~~~

The fingerprint records files and hashes, not a behavioral-quality score.

### 5. Explicit EVAL

Only after an explicit measurement request, read [EVAL and reports](references/eval-and-reports.md).

For an explicit train request, validate the bounded train plan first and keep
the active skill immutable:

~~~
python3 <skill-forge-dir>/scripts/train_plan.py \
  --input <target-skill>/.skill-forge/train-plan.json
~~~

A train plan must evaluate at least 50 candidates. A no-improvement limit may
not end the run before that floor. An earlier stop is allowed only for a
predeclared meaningful result: an eligible Pareto candidate, full developer
panel confirmation with at least three repeats, blind independent judgment,
the locked final holdout, and every declared protected-metric improvement.
The plan validator rejects a lower candidate floor or an incomplete early-stop
contract.

Run only isolated candidate copies, use one attributable hypothesis per
candidate, and do not inspect a locked final holdout until a finalist is
selected. The train plan, not a planned iteration count, determines when to
stop. A Pareto-frontier result is evidence for a proposal, never automatic
promotion.

Before any model call, show and confirm:

- cases, conditions, assertions, repeats, concurrency, budget, and stop condition;
- one worker model and reasoning effort used identically for baseline and candidate;
- a separate judge model and effort, or why deterministic assertions make a judge unnecessary;
- expected worker calls, judge calls, tokens, and wall time.

Use a cheaper representative model for worker runs when the goal is to expose skill lift economically. Use a stronger independent model for unresolved qualitative judgment. A weak-model benchmark measures assistance to that model; it does not prove the same lift on a stronger deployment model. Never switch models silently.

Validate a planned run without calling a model:

```bash
python3 <skill-forge-dir>/scripts/eval_plan.py \
  --input <target-skill>/.skill-forge/eval-plan.json
```

Use isolated contexts and workspaces. Preserve holdout cases from the authoring flow. Record pass, fail, or infrastructure_error; never turn a crash, timeout, unavailable tool, or parse failure into product evidence.

Record per-condition assertion outcomes. Mark identical paired assertion results
as non-discriminating and contradictory repeats as unstable; use them to refine
developer cases, not to manufacture a quality conclusion.

### 6. Decision report

Generate HTML only for an explicit audit or EVAL from recorded JSON:

```bash
python3 <skill-forge-dir>/scripts/render_report.py \
  --input <target-skill>/.skill-forge/report.json \
  --output <target-skill>/.skill-forge/report.html
```

The renderer validates statuses and comparison metadata, derives sufficiency from the runs, and keeps raw evidence outside the landing. For high-impact work or unfamiliar hosts, read [problem map](references/problem-map.md) before proposing release.

## Result

Answer in the user's language with:

1. verdict and exact scope;
2. contract assumptions or blockers;
3. ownership map plus proposal or severity-ranked findings;
4. verification, provenance, accepted uncertainty, and remaining risk;
5. for EVAL only: worker/judge configuration, equivalence, comparable metrics, sufficiency, and artifact paths.

Do not publish, package, create GitHub files, install tools, or mutate external systems unless separately requested.
