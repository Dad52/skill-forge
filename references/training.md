# Train workflow

Training is a bounded experimental route for an explicitly requested skill
improvement. It is not a background loop, an automatic promotion mechanism, or
a promise that each iteration improves a skill.

## Protected setup

Before any worker call, freeze:

- active-skill fingerprint and baseline version;
- developer cases, assertion IDs, fixtures, worker configuration, and budgets;
- a separate final holdout whose prompts, hidden acceptance details, and
  previous scores are unavailable to the authoring loop;
- protected metrics and hard gates, including correctness and any user-set
  token or latency ceiling;
- at least 50 candidate evaluations, maximum rounds, maximum candidates per
  round, no-improvement limit, timeout, token budget, and a repeated-
  infrastructure-failure stop condition;
- an early-stop contract. It may end the run before 50 candidates only after a
  predeclared meaningful result: eligible Pareto status, a full developer-panel
  confirmation with at least three repeats, blind independent judgment, the
  locked final holdout, and every declared metric improvement.

Validate this contract first:

~~~
python3 <skill-forge-dir>/scripts/train_plan.py \
  --input <target-skill>/.skill-forge/train-plan.json
~~~

The active skill remains immutable. Work only in isolated candidate copies
under the target skill's .skill-forge/training directory. Promotion is a
separate explicit user decision, even when a candidate is strong.

## Candidate loop

Start by measuring the unchanged baseline with the fixed developer harness.
For each round:

1. diagnose one observed failure cluster, weak mechanism, or non-discriminating
   assertion;
2. propose a small attributable mutation tied to requirement IDs and a
   prediction;
3. run static gates, then the smallest developer cases that can falsify that
   prediction;
4. run the full developer panel only for candidates that pass the cheap gates;
5. record outcome, costs, infrastructure state, and the next hypothesis.

Do not stack unrelated edits into a candidate. Parallel proposals are allowed
only when they alter independent hypotheses and use isolated copies. Never let
one candidate's output become another candidate's hidden prompt.

Use deterministic scripts for parsing, deduplication, validation, aggregation,
snapshotting, and report rendering when they replace repeated model work or
create a testable invariant. Do not use a script to make semantic product
decisions, rewrite a skill without review, or hide model calls.

## Selection and stop

Hard gates reject a candidate before quality trade-offs. For eligible
candidates, use a Pareto frontier across declared metrics rather than a
synthetic score. Record the selection evidence:

~~~
python3 <skill-forge-dir>/scripts/training_ledger.py frontier \
  --input <target-skill>/.skill-forge/training/<run-id>/candidate-results.json
~~~

Do not let a no-improvement limit end the run before 50 candidate evaluations.
Before that floor, use failure clusters to propose another attributable
hypothesis; stop only for an exhausted budget, timeout, or repeated
infrastructure failure. After the floor, stop when the plan's budget, round,
no-improvement, or infrastructure limit is reached. An early stop before the
floor is valid only when every predeclared meaningful-result gate has passed.
Report a diagnosis if no candidate improves the protected objective:
the bottleneck may be the test, model, missing evidence, or an already adequate
baseline. Do not keep changing prose merely to fill planned iterations.

Test only a selected finalist against the locked final holdout. If the
holdout exposes a defect, log it as a new future developer regression only
after the current comparison is complete; do not tune and re-measure that same
holdout as evidence of final lift.

## Provenance and report

Create a content fingerprint after an approved apply and at each candidate
boundary:

~~~
python3 <skill-forge-dir>/scripts/training_ledger.py snapshot \
  --target <target-skill> \
  --output <target-skill>/.skill-forge/provenance.json
~~~

Keep the approved plan, snapshots, candidate mutation record, raw outputs,
tri-state run status, and final report under .skill-forge. Render the final
baseline-versus-finalist EVAL as the normal HTML report; it must name the
worker and judge, conditions, comparable paired cases, budgets, and
infrastructure errors. A training report must explain rejected candidates and
stopping reason, not present a percentage when the evidence is insufficient.

## Metrics that must stay honest

An assertion is non-discriminating when paired baseline and candidate outcomes
are identical; it is not proof that the skill failed. An assertion is unstable
when repeated runs disagree; it is a test-design or model-variance signal.
Refine developer cases with these signals, but preserve the locked holdout.

Do not implement an automatic-trigger metric until the actual host can provide
reliable discovery telemetry. Explicit invocation, positive and near-miss
fixtures, and host-loader checks are the valid proxy until then.
