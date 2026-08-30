# Skill Forge

[Русский](README.ru.md)

> Create agent skills with the real failure cases behind Codex and Claude Code Skill Creator in mind.

Skill Forge helps you create, inspect, improve, or measure a portable agent
skill without quietly turning the job into a rewrite, a model run, or a
publication. It makes the skill's trigger, authority, dependencies,
references, and checks explicit before you ship it.

We collected these problem reports and built their lessons into Skill Forge so
new skills do not repeat them.

## Why these checks exist

| Failure pattern | Where it surfaced | What Skill Forge checks |
| --- | --- | --- |
| A skill is not discovered because its entrypoint or description is wrong | [Codex #20637](https://github.com/openai/codex/issues/20637), [Codex #13941](https://github.com/openai/codex/issues/13941), [Anthropic #1169](https://github.com/anthropics/skills/issues/1169) | Exact `SKILL.md`, frontmatter, and description limits |
| The core instructions or reference route are unclear, so the model loads too much or misses the rule it needs | [Codex #16479](https://github.com/openai/codex/issues/16479), [Anthropic #1486](https://github.com/anthropics/skills/issues/1486) | One owner per rule, conditional references, reachable local routes, and a context-budget check |
| A helper needs capabilities it did not declare, or its safety boundary is only implied | [Anthropic #1468](https://github.com/anthropics/skills/issues/1468) | Declared dependencies, local verification, authority boundaries, secret and unsafe-instruction scans |

The links are the concrete reports we used, not marketing evidence. A static
check catches a class of mistakes; it does not prove that every generated skill
will be good.

## What the benchmark found

Skill Forge and Codex's bundled `$skill-creator` each created four portable
skills three times. Both conditions produced 12/12 valid, portable packages
and passed all 21 runtime checks. The difference showed up only in blind task
evaluation.

| Measure | Codex Skill Creator | Skill Forge |
| --- | ---: | ---: |
| Portable, statically healthy generated skills | 12 / 12 | 12 / 12 |
| Runtime checks passed | 21 / 21 | 21 / 21 |
| Blind task-fit passes | 16 / 18 | **17 / 18** |
| Critical boundary failures | 3 / 18 | 3 / 18 |
| Blind preference | 2 wins, 12 ties | 4 wins, 12 ties |
| Mean creation time | **111.3 s** | 113.3 s |

The observed edge is in ambiguous triage and explicit boundary handling, not
speed or a guarantee that every new skill will be better. Codex Skill Creator
also won one release-note comparison, and both approaches repeated the same
customer-reply boundary failure. [Read the full method and per-scenario result.](docs/benchmarks/2026-08-30/skill-forge-head-to-head.md)

## What it looks like in practice

**A support-ticket triage skill.** It should turn a pasted ticket into an
internal severity/owner/next-step note, not accidentally write a customer
reply or update a ticket. Skill Forge keeps the everyday decision flow in
`SKILL.md` and moves the detailed severity taxonomy to a reference that loads
only for borderline cases.

**A local log redactor.** The skill must make a copy at a path you name, never
touch the source, never upload a log, and say what its helper needs. A small
test is worth more here than a reassuring sentence in the prompt.

**An incident-update skill.** A normal writing request must not trigger it.
When you invoke it explicitly, it keeps uncertainty, removes private customer
details, and produces a draft rather than publishing one.

## Install

```bash
npx skills add Dad52/skill-forge --skill skill-forge --agent codex
```

## Use it

```text
$skill-forge I made a skill that edits local logs. Check whether its trigger, file-safety rules, references, and test path are ready for release. Do not change anything yet.
```

For a change, Skill Forge shows the smallest proposed diff first and waits for
an explicit instruction to apply it. For an evaluation, it records the model,
cases, conditions, and evidence before a run begins.

## License

[MIT](LICENSE).
