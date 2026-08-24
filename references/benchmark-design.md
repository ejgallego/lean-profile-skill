# Benchmark Design

Use this reference when adding, choosing, or interpreting Lean performance
workloads.

## Contents

- Workload Classes
- Comparable Runs
- Ranking Targets
- Slices And Snapshots
- Diagnostics
- Historical Reports
- Evidence Bundle

## Workload Classes

Use explicit classes:

- Representative: real user-visible command or corpus. Let these choose the
  next optimization target.
- Focused: reduced workload that isolates a mechanism seen in a representative
  profile. Use these to validate a fix.
- Micro: tiny guardrail or regression detector. Do not let these dominate
  target choice without representative evidence.
- Historical: fixed reports across commits. Use only when workload definitions,
  schema, toolchain, and corpus drift are documented.

## Comparable Runs

Before comparing numbers, hold constant:

- machine and CPU governor where possible;
- Lean toolchain and dependencies;
- executable target and build flags;
- input corpus and command arguments;
- diagnostics/tracing mode;
- profiler event list;
- repeat and warmup policy;
- baseline and candidate labels.

If any of these changed, record the change and narrow the claim.

Treat benchmark identity as a schema, not prose. Capture:

- command and argument vector;
- executable, input, bytecode/corpus, and harness hashes;
- repository commit and dirty state, plus the tracked-diff hash and hashes of
  task-relevant untracked files when dirty;
- toolchain, build mode, diagnostics, environment-relevant configuration;
- fuel/input size, expected status, terminal PC or equivalent endpoint;
- event list, inheritance policy, warmups, repetitions, and run order;
- raw per-run results plus the aggregation rule.

Use AB/BA or another order-balanced schedule when comparing noisy elapsed
times. Preserve pass and sequence columns so aggregation cannot silently keep
only the final run. Report the paired deltas and raw distribution, and mark the
result inconclusive when the claimed effect is not distinguishable from
run-order or observed noise. A repository-specific harness may retain one-pass
runs for quick screening; the bundled helper requires a complete AB/BA cycle and
therefore starts at two passes.

If the repository has no comparison harness, resolve this skill directory and
use `scripts/compare_commands.py`. It refuses to overwrite an existing output
directory and records command arrays, executable and input hashes, Git identity,
stdout/stderr, elapsed time, optional per-run `perf stat` output, and the AB/BA
sequence.

## Ranking Targets

Prefer ranking by weighted overhead against a real baseline:

```text
weighted_overhead = (candidate_metric - baseline_metric) * representativeness_weight
```

Use elapsed time for user-visible workflow ranking. Use cycles or instructions
only as secondary acceptance/regression evidence from a stable harness. Do not
use counter totals to discover Lean optimization targets.

If the repository has a packaged selector, use it before reading raw reports.
Selectors should validate benchmark metadata, warn about stale report commits,
rank representative workloads ahead of guardrails, and emit the rerun command
for the top row.

A good optimization story connects:

- a representative slowdown or hotspot;
- the normal Lean/project code path being changed;
- a focused mechanism check if needed;
- a correctness test or semantic invariant;
- an explicit reason rejected alternatives are not being used.

## Slices And Snapshots

Slices are attribution tools. They are useful when a full run has too few
samples or when setup dominates the profile. Do not land on slice evidence
alone. After changing code, rerun the slice plus the representative command.

Snapshot or replay systems must include enough identity to avoid stale reuse:

- executable hash or commit;
- input hash;
- relevant environment/configuration;
- project-specific runtime state version.

## Diagnostics

Keep normal headline runs diagnostics-off. Enable diagnostics only when
measuring diagnostic overhead or collecting targeted evidence.

Examples of diagnostics:

- runtime traces;
- ownership/sharedness summaries;
- extra JSON reports;
- helper timing output;
- debug metadata modes.

If diagnostics change code shape, do not use their timing as the acceptance
number.

Counter instrumentation belongs in this diagnostic category unless it is part
of an already trusted benchmark harness. Treat ad-hoc counters as a failed
target-selection strategy for Lean.

## Historical Reports

For history sweeps:

- choose a fixed milestone set or explicit revision range;
- record unsupported or ignored fixtures;
- use timeouts rather than blocking the whole sweep;
- keep build-cache reuse separate from measured samples;
- avoid comparing aggregate totals across corpus growth without a common-label
  subset.
- refresh a current-head report before choosing a target from old artifacts.

## Evidence Bundle

A landing-quality bundle should contain:

1. identity metadata and raw runs;
2. endpoint/status validation;
3. diagnostics-off, order-balanced representative before/after results;
4. secondary counters with their event and inheritance policy;
5. pre- and post-change sampled profile summaries;
6. generated C/IR evidence for ownership or allocation claims;
7. executable and hot-symbol size deltas for code-shape changes;
8. correctness commands/results;
9. an accepted/rejected decision and remaining hotspot.

Classify hashes, generated sources, exact endpoints, and code size as
deterministic evidence. Classify elapsed time, counters, and sampled overheads
as noisy evidence. Keep both; do not imply that one has the confidence
properties of the other.
