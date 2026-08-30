# EVAL and reports

## Model roles

Never hide model choice behind a preset. Before calls, show concrete identifiers and reasoning efforts for:

- **worker**: executes both baseline and candidate under identical configuration;
- **judge**: independently grades only claims not settled by deterministic assertions.

If the user did not name models, recommend a configuration and wait for authorization. Usually choose the cheapest worker representative of intended use and a stronger judge. A low-cost worker is useful for finding skill lift cheaply, but its result applies to that worker model only. Repeat on the deployment model before making deployment-wide claims.

The judge must not receive condition labels, authoring history, the intended winner, or hidden chain-of-thought. Randomize pair order when the harness supports it. Prefer no judge when file state, JSON schema, command status, or another deterministic oracle answers the question.

## Preflight plan

Record:

- candidate and baseline versions or hashes;
- versioned public cases, isolated holdouts, fixtures, assertions, and assertion IDs;
- conditions, repeats, clean-context/workspace strategy, and concurrency;
- worker model/effort and judge model/effort or `judge_mode: none`;
- when a judge is used, an explicit basis for treating its configuration as stronger;
- per-run timeout, token/time budget, estimated calls, and stop condition;
- whether access, prompts, tools, and workspace state are equivalent.

Use `scripts/eval_plan.py` to reject missing role configuration and compute call counts. Infrastructure setup and model calls remain separate; plan validation performs neither.

## Case design

Start with a few realistic cases, each targeting one behavior. Add cases only for observed uncertainty or a reproduced defect. Include, when relevant:

- positive, negative, near-miss, and explicit manual invocation;
- ordinary success and incomplete input;
- permission, tool, timeout, malformed-output, and recovery failures;
- hostile referenced content paired with a benign control;
- a paraphrase or irrelevant-context metamorphic variant;
- at least one holdout untouched by authoring.

Keep the generator away from holdout answers, judge rubric internals, and prior candidate scores. Shrink a reproducible failure to the smallest prompt/context that retains it before adding a regression case.

Each assertion should be specific enough to distinguish a plausible baseline
from a candidate. Record its outcome per condition rather than only a
case-level score. If the two paired conditions always have the same assertion
outcomes, label the case non-discriminating. If repeated outcomes conflict,
label it unstable. Both are test-design signals, not proof of product failure.

## Execution and status

Run each condition in a fresh context and, for workspace tasks, an isolated temporary workspace. Baseline and candidate receive the same worker model, effort, tools, fixtures, prompt, limits, and initial state; only skill availability differs.

Use exactly:

- `pass`: product evidence met the assertion;
- `fail`: product evidence contradicted it;
- `infrastructure_error`: timeout, runner crash, unavailable tool/model, rate limit, parse failure, or invalid environment.

An infrastructure error is neither pass nor fail. Retry a plausible transient once, record the reason, and stop when the budget or repeated-failure condition is reached. Preserve outputs so grading changes can be applied without rerunning workers.

## Comparison

Use deterministic assertions first. For remaining quality questions, use blind pairwise judgment with a versioned rubric and report it as model judgment.

Do not claim causal lift when:

- model, effort, prompt, tools, fixtures, or state differ;
- baseline or paired cases are missing;
- infrastructure failures dominate;
- the sample is too small for the stated conclusion;
- the candidate was tuned on the claimed holdout.

Repeated runs may show consistency, but small samples do not justify precise significance claims. Report raw counts, paired cases, medians, P90 only when supported, variance/outliers, and unknown tokens/cost as unknown, never zero.

Do not repeatedly inspect a final holdout while changing the candidate. Use it
once for the selected finalist, then turn any exposed defect into a future
developer regression after the comparison is closed.

## Artifact and report contract

Store only explicit audit/EVAL data under `<target>/.skill-forge/`:

- `eval-plan.json`: authorized plan and model roles;
- `runs/`: raw prompts, outputs, status, timing, and token records;
- `report.json`: normalized findings and cases;
- `report.html`: one-page decision landing.

Record candidate hash/version, EVAL-set hash/version, worker/judge identifiers, host, timestamps, and condition equivalence. Exclude `.skill-forge/` from distributed packages.

The HTML renderer computes sufficiency instead of trusting a caller flag. Its first screen shows verdict, evidence level, paired cases, status counts, worker/judge models, tokens, and latency. Details expand by finding, case, and failure cluster; raw artifacts remain separate.

For an explicit iterative train request, use the same EVAL contract for the
baseline-versus-finalist comparison and preserve the train plan, candidate
snapshots, mutations, and stopping reason alongside these artifacts.
