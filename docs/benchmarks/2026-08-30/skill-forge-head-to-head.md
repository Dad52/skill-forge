# Skill Forge — head-to-head with Codex Skill Creator

Four portable skills were created from the same requests: ticket triage, an explicit-only incident update, a local log redactor, and a release-note drafter. Each condition was repeated three times.

- Creator: `gpt-5.6-terra`, `xhigh` reasoning.
- 12 generated skills per condition; every creation had a separate workspace.
- Runtime: 21 checks per condition, including six deterministic redaction fixtures.
- Blind judge: `gpt-5.6-sol`, `high`; 18 shuffled text-answer pairs.

| Measure | Codex Skill Creator | Skill Forge |
| --- | ---: | ---: |
| Created skills with entrypoint, portable paths, no secret-like values, and no undeclared Python dependency | 12 / 12 | 12 / 12 |
| Runtime checks passed | 21 / 21 | 21 / 21 |
| Blind task-fit passes | 16 / 18 | **17 / 18** |
| Critical boundary failures | 3 / 18 | 3 / 18 |
| Blind preference | 2 wins, 12 ties | 4 wins, 12 ties |
| Mean creation time | **111.3 s** | 113.3 s |
| Mean runtime time | 10.4 s | **10.1 s** |

The result is directional rather than a replacement claim. Skill Forge won two of three ambiguous ticket-triage comparisons by treating reported scope and severity as provisional. It also won one incident-update comparison. Codex Skill Creator won one release-note comparison; twelve other pairs were ties. Neither side improved the three customer-reply boundary failures, so that gap belongs in a later release.

The benchmark does not claim a token or creation-speed saving. It measures the failure modes that motivated the skill: discovery, explicit triggering, portability, local helper safety, and authority/fact boundaries.
