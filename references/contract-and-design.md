# Contract and design

## Contract card

| Field | Required answer |
|---|---|
| Outcome | What recurring task becomes measurably easier or safer? |
| Audience | Which users, agents, and hosts rely on it? |
| Trigger | Which requests should load it? |
| Boundary | Which nearest similar requests must not load it? |
| Authority | Reads, writes, tools, network, dependencies, and approvals |
| Completion | Which observable artifact or decision ends the work? |
| Risk | Low read-only, medium workspace mutation, or high external/destructive effect |

Ask only when an unknown answer changes a row. Recommend no skill when the task is one-off, ordinary model ability is sufficient, or a project-local instruction is narrower.

## Requirement ownership

Assign stable IDs such as `R-001` before writing. Map each requirement to exactly one owner and at least one verification method:

- `SKILL.md`: discovery boundary, shared decisions, permissions, and routing;
- direct reference: conditional knowledge that changes a decision only in some requests;
- script: deterministic parsing, validation, or transformation that should not be regenerated;
- asset: material copied into output, never hidden instruction text;
- EVAL case: an observable behavior that prose or static validation cannot establish.

Flag both directions of traceability:

- requirement without verification: behavior can regress silently;
- test without requirement: an orphan assertion may preserve accidental behavior.

A link is not a second owner. Core should state when to read a reference, while
the reference owns the conditional detail. Keep the load predicate exclusively
in the caller: do not repeat “read/use this reference when …” or the route
description as introductory prose inside the referenced file. The reference
should begin with behavior that applies after loading it.

## Description and routing test

The description says what the skill does and when it applies. Add exclusions only for plausible false routes. Test at least:

1. clear positive invocation;
2. nearest negative or near miss;
3. vague request that should ask for missing context;
4. manual invocation policy when explicit-only behavior is required.

Do not promise a model, tool, host, side effect, publication path, or network access the skill cannot guarantee. Do not treat the user's current stack as a permanent constraint unless they confirmed it.

## Minimality and progressive disclosure

For every proposed file ask: which concrete decision or deterministic behavior becomes better because this exists? If no answer exists, omit it.

Estimate context in three separate buckets:

- discovery metadata: always available for routing;
- core: loaded when invoked;
- deferred resources: loaded only when routed to them.

Do not subtract quality points merely because deferred scripts, tests, or references exist. Investigate whether they are reachable, owned, and useful instead.

## Pre-mortem

For medium/high-risk work, assume release failed. Record the three likeliest ordinary failures, earliest signal, prevention, and rollback. Prefer wrong routing, stale paths, missing authority, evaluator contamination, and lost behavior over speculative disasters.

Keep generation and evaluation separate: authoring flows may see public cases, but not holdout answers, judge prompts, or hidden acceptance details.

## Script-first, model-last

Use a standard-library script for a deterministic operation only when it
replaces repeated model work or establishes a testable invariant. Good owners
include parsing, link checking, hashing, fixture isolation, deduplication,
aggregation, schema validation, and rendering recorded data.

For each proposed script, name its input, output, failure behavior, side
effects, and one local test. Keep the script read-only unless the contract
explicitly permits a narrow output path. Do not turn semantic judgment,
unreviewed skill rewrites, or hidden model calls into a script merely to make a
workflow look automated.

For improve or train work, first inventory the existing behavior, structure,
and content fingerprint. Preserve a useful behavior unless a contract row,
reproduced defect, or measured regression supports its removal.
