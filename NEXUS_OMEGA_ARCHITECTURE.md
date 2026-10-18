# NEXUS Omega Architecture and Implementation Plan

NEXUS Omega is a controlled, experiment-driven self-evolution layer for NEXUS Enterprise. It does not rewrite production code or bypass existing permissions. It observes real executions, evaluates them with reproducible metrics, creates immutable candidate configurations, runs candidates in bounded experiments, and changes the active version only through governance.

## Control boundary

- **Observe mode:** read-only analysis and recommendations.
- **Sandbox mode:** candidate generation and benchmark execution with no production mutation.
- **Controlled mode:** promotion is allowed only when configured policy thresholds pass; high-risk changes require approval.

The operational NEXUS workflow remains the only path for customer tasks. Omega consumes its traces and invokes it through explicit experiment interfaces.

## Lifecycle

```text
OBSERVE -> EVALUATE -> ANALYZE -> GAP -> HYPOTHESIS -> CANDIDATE
  -> SANDBOX -> BENCHMARK -> COMPARE -> GOVERN
  -> PROMOTE -> VERIFY -> (ROLLBACK if regression) -> REMEMBER
```

Each transition receives a correlation/evolution-cycle ID, writes a durable record, and emits a redacted audit event. No result is presented as an improvement until a real benchmark produces it.

## Phased implementation

1. **Audit and contracts:** document current boundaries, add Omega configuration and typed domain contracts.
2. **Execution tracing:** capture version/config/provider metadata and bounded, redacted execution events around existing workflow traces.
3. **Evaluation engine:** version metrics and datasets; persist sample size, measurement method, timestamps, and execution lineage.
4. **Failure analysis:** aggregate real validation/correction/tool/retrieval outcomes and classify recurring patterns.
5. **Capability gaps:** require frequency, evidence references, affected task slices, severity, and confidence before creating a gap.
6. **Hypotheses:** generate structured interventions from gaps while consulting evolution memory to avoid duplicate attempts.
7. **Candidates and versions:** create immutable candidate configurations with parent lineage and explicit target components.
8. **Sandbox:** execute only allowlisted configuration changes through existing restricted execution facilities; enforce budgets and no production writes.
9. **Benchmarks:** run held-out, versioned benchmark cases through the real workflow and store item-level outcomes.
10. **Comparison:** calculate baseline/candidate deltas across quality, reliability, efficiency, and safety.
11. **Governance:** apply configurable minimum sample, improvement, latency, cost, and safety policies.
12. **Promotion:** register and activate only approved candidates, preserving the previous stable version.
13. **Verification and rollback:** monitor post-promotion executions, detect configured regressions, and restore the previous known-good version.
14. **Memory:** expose searchable history of gaps, hypotheses, candidates, experiments, decisions, promotions, and rollbacks.
15. **Frontend and demonstration:** add `/evolution`, lineage views, experiment reports, and a reproducible real-data workflow.
16. **Hardening:** add unit, integration, API, security, sandbox, governance, promotion, rollback, and regression tests.

## Initial data model direction

Additive tables will represent `evolution_cycles`, `execution_events`, `failure_events`, `capability_gaps`, `hypotheses`, `candidates`, `agent_versions`, `workflow_versions`, `experiments`, `benchmark_runs`, `promotions`, `rollbacks`, and `evolution_memory`. Foreign keys should reference existing tasks/evaluation runs where applicable. JSON is acceptable for immutable configuration snapshots, while lifecycle status, version IDs, timestamps, and policy decisions remain queryable columns.

## Decision policy

The default policy is observe-only. A controlled decision must evaluate all configured dimensions, not only one quality score:

- minimum sample size;
- minimum quality/reliability improvement;
- maximum latency and cost increase;
- zero critical safety regression;
- acceptable failure/retry rate;
- explicit human approval for high-risk targets.

Every rejection is useful memory and remains visible. Known-bad candidates cannot be silently retried as new successes.

## Reproducibility

Experiments record dataset version, held-out case IDs, baseline and candidate version IDs, provider/model identifiers, prompt/config snapshots, policy version, seed where applicable, timestamps, and item-level results. Generated code is never executed with unrestricted host privileges.

## Delivery checkpoints

Each phase ends with focused tests, the existing NEXUS suite, documentation updates, and a clean review of migration/security impact. Large changes are intentionally split so operational behavior stays stable while Omega gains capability.
