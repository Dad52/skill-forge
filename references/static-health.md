# Static health

## Finding contract

Each finding has a stable ID and these fields:

`category · severity · confidence · status · path/line · evidence · remediation`

- `error`: a reproducible structural, credential, or authority failure that blocks release;
- `warning`: a likely defect or risky ambiguity requiring contextual review;
- `info`: an observation or estimate, not a request to rewrite;
- `confidence`: scanner confidence in detection, not probability that the whole skill is bad.

Never combine findings into a quality grade. Record a false positive as accepted evidence so the rule can later be calibrated.

## Passes

The scanner performs independent passes so one heuristic cannot masquerade as an overall verdict:

1. target, encoding, file limits, and symlinks;
2. constrained frontmatter schema and folder/name match;
3. local Markdown links, explicit textual routes, anchors, reachability, and reference depth;
4. `agents/openai.yaml` consistency, including manual-only policy;
5. exact cross-file duplication and ownership signals;
6. credentials, prompt-injection-like instructions, unsafe commands, and side effects;
7. undeclared Python dependencies, local package imports, and portability hints;
8. estimated discovery/core/deferred context budget.

The dependency-free YAML fallback deliberately supports the frontmatter subset Forge needs. When syntax cannot be verified without a full YAML implementation, report `unverified_yaml`; never silently accept or silently install a package.

## Release blockers

Treat these as errors unless the documented target host provides a compatible exception:

- missing or unreadable UTF-8 `SKILL.md`;
- malformed, duplicated, missing, or mismatched `name`/`description`;
- local link escaping the target or pointing to a missing file;
- secret-like credential in a distributed file;
- manual-only description paired with implicit invocation;
- undisclosed destructive instruction with clear executable intent.

## Judgment-required warnings

Warnings are prompts to inspect context, not automatic changes:

- unreachable or deeply chained references;
- a reference that repeats its own “read/use this reference when …” predicate;
- exact duplicated instruction across owners;
- unverified YAML feature or host-specific field;
- prompt-injection-like wording in an example or imported reference;
- shell/network/write constructs whose authority is unclear;
- an actual Python eval or exec call; plain prose containing the word is not a finding;
- absolute local paths, undeclared imports, or portability assumptions.

Static checks cannot prove semantic duplication, freshness, safe runtime behavior, cross-host compatibility, behavioral quality, or actual token consumption.

An explicit textual route is accepted only when an imperative such as Read, Use,
See, or Follow points to a concrete local Markdown path. Casual prose and a
bare filename do not make a resource reachable. Dependency analysis recognizes
package-local imports by their path; it does not infer that an arbitrary
third-party import is available.

## Review procedure

1. Reproduce each error from its evidence and source span.
2. Review warnings in context; mark accepted false positives explicitly.
3. Map each proposed edit to a finding, requirement, or behavioral regression.
4. Re-run the smallest pass and nearby tests after apply.
5. Add a regression fixture for every confirmed scanner or production defect.

The scanner is side-effect free unless `--output` is passed. An audit artifact belongs only under `.skill-forge/` and must not ship with the skill package.
