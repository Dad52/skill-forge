# Problem map

| Risk cluster | Typical symptom | Forge control | What remains unproven |
|---|---|---|---|
| Discovery | missed, false, or shadowed trigger | description contract, manual policy, trigger matrix | host loader correctness |
| Context | slow or ignored guidance | ownership map and separate context buckets | observed runtime tokens |
| Structure | parser, name, link, or anchor failure | constrained parser and graph checks | every host YAML extension |
| Scripts | hidden dependency or unsafe mutation | import, command, authority, and regression checks | sandbox/runtime safety |
| Change | lost behavior or unexpected mutation | proposal-first, requirement traceability, explicit apply | correctness of user-approved design |
| EVAL | inflated, inverted, or contaminated result | isolation, holdouts, tri-state status, blind judge | ground-truth quality |
| Train | noisy iterations or accidental benchmark overfit | immutable baseline, tiny attributable mutations, dev/final split, hard gates, Pareto frontier | transferable lift |
| Models | cheap runs judged by same weak model | explicit worker/judge roles | transfer to untested models |
| Cost | quota loss, 429, or runaway loop | call estimate, budget, timeout, stop condition | future provider pricing |
| Reports | convincing output from weak evidence | schema validation and derived sufficiency | reader interpretation |
| Lifecycle | shadowed, stale, or lost version | provenance, retirement path, rollback record | future host compatibility |
| Catalog | apparent duplicates or host-specific shadowing | scoped inventory and host-precedence review | loader behavior without a host fixture |
| Security | credentials or injected instructions | static detection plus adversarial fixture | absence of unknown attacks |

## Short pre-mortem

Ask only what can alter the release:

1. If the skill is never used, which discovery assumption failed?
2. If it triggers wrongly, which near-miss or manual-policy case is absent?
3. If it harms a workspace, which authority, input boundary, or recovery path was unstated?
4. If the EVAL looks falsely better, which condition, holdout, judge, or infrastructure state leaked?
5. If the package becomes slower, which content bucket was actually loaded?
6. If retirement loses capability, which old requirement lacks a Forge owner or regression case?

For each plausible failure record earliest signal, mitigation, verification, and rollback. A static warning, provenance record, or passing benchmark narrows uncertainty; none proves universal safety or quality.
