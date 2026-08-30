# Release benchmark — 2026-08-30

This release check compares Codex's bundled `$skill-creator` with
`$skill-forge` on the same three creation requests. It is evidence about the
tested configuration, not a blanket claim that one creator always makes a
better skill.

## Setup

- Worker: Codex `gpt-5.6-terra`, `xhigh` reasoning.
- Three portable-skill tasks: ticket triage with conditional reference routing,
  local log redaction with a deterministic helper, and an explicitly invoked
  incident-update skill.
- Three isolated repetitions per case and condition: 18 runs in total.
- Each run began in an empty workspace with the same request, tools, and time
  limit. Only the creator skill changed.
- No model judge was used. All published checks are deterministic.

## Measured result

| Measure | Bundled Skill Creator | Skill Forge |
| --- | ---: | ---: |
| Generated skills completing the harness | 9 / 9 | 9 / 9 |
| `SKILL.md` entrypoint exists | 9 / 9 | 9 / 9 |
| Zero errors from the Skill Forge static scanner | 9 / 9 | 9 / 9 |
| Description fits the host limit | 9 / 9 | 9 / 9 |
| Local links/routes resolve | 9 / 9 | 9 / 9 |
| No undeclared Python dependency or secret-like value | 9 / 9 | 9 / 9 |
| Median output tokens | 4,605 | 5,389 (+17.0%) |
| Median wall time | 70.0 s | 82.0 s (+17.1%) |

Those static rows are non-discriminating: both creators passed them in this
small sample. Skill Forge cost more tokens and time in return for more
scaffolding, so there is no speed or token-saving claim here.

One black-box check did distinguish the conditions. Every generated
`log-redactor` received the same local file containing an email address, a
bearer token, a phone number, and an ordinary line. The source had to remain
unchanged; the output had to exist, remove all three sensitive values, and
preserve the ordinary line.

| Functional check | Bundled Skill Creator | Skill Forge |
| --- | ---: | ---: |
| Source unchanged | 3 / 3 | 3 / 3 |
| Output created and ordinary content preserved | 3 / 3 | 3 / 3 |
| All three fixture values redacted | 2 / 3 | 3 / 3 |
| Generated helper includes its own executable test file | 0 / 3 | 2 / 3 |
| Those generated test suites pass | — | 2 / 2 |

The redactor sample is too small to establish a general defect rate. It does
show one concrete difference under the stated fixture: one baseline helper
left the formatted phone number intact, while all three Skill Forge helpers
removed it.

## Inspect or rerun

- [evaluation-plan.json](evaluation-plan.json) records the conditions,
  assertions, and limits.
- [creator-cases.json](creator-cases.json) contains the three public requests.
- [results.json](results.json) preserves sanitized per-run status, assertions,
  timing, tokens, and response hashes.
- [log-redactor-smoke.json](log-redactor-smoke.json) preserves the functional
  fixture checks without a machine-specific path or log content.

The benchmark uses only synthetic prompts and a synthetic local log fixture;
the committed evidence contains no user logs, credentials, or personal paths.
