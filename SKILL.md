---
name: lean-profile-skill
description: Profile and optimize the runtime of compiled Lean executables and their generated native code. Use when Codex needs to diagnose executable runtime regressions, compare baseline and candidate binaries, collect perf or samply evidence, inspect generated C for ownership/allocation behavior, design native-runtime benchmarks, or document accepted and rejected runtime optimizations. Do not use as the first-line workflow for theorem or tactic elaboration, module compilation, or general Lake build-time profiling.
---

# Lean Native Runtime Profiling

Use this skill to turn a vague Lean speed problem into comparable measurements,
credible attribution, and a landable optimization story.

## Scope Gate

Confirm that the slow region occurs while running compiled Lean code. If the
request concerns theorem or tactic elaboration, module compilation, dependency
builds, or general `lake build` latency, stop this workflow and begin with
`lean --profile`, the `profiler` options, or `trace.profiler`. Return to this
skill only if that investigation identifies native executable runtime as the
cost surface.

## Prominent Lesson

Do not use a counter-first strategy for Lean performance work. It has failed in
practice: runtime counters, helper timers, and aggregate hardware counters tend
to say that something is expensive without identifying the compiler/runtime
ownership path that made it expensive. Use sampled profiles and generated C/IR
for attribution. Use counters only after that, as coarse acceptance or
regression evidence from an established harness.

Do not infer a missing Lean ownership feature from one slow source shape.
Separate three questions: whether Lean can express the exclusive update,
whether control flow keeps the owned token visible at the mutation, and whether
inlining or specialization duplicates too much generated code. Test those
dimensions explicitly before proposing a compiler feature or native override.

## Workflow

1. Define the workload before profiling.
   - Prefer a representative command the user actually cares about.
   - Add focused or micro workloads only after the representative run identifies
     a cost class.
   - Record the command, input and binary hashes, commit/worktree state,
     toolchain, build mode, diagnostics, event list, repeat policy, and expected
     terminal state.

2. Map the workload phases before changing code.
   - Separate startup, loading, parsing, steady execution, and shutdown when the
     command crosses materially different runtime regions.
   - Use temporal samples, stable program counters, or project-native phase
     markers. Treat slices as attribution aids, not acceptance workloads.

3. Establish a baseline and a candidate.
   - Keep builds comparable: same machine, same input, same executable target,
     same diagnostics mode, same repeat/warmup policy.
   - Preserve raw runs. Use AB/BA or another order-balanced pair when elapsed
     time is sensitive to temperature or background load.
   - Prefer repo-local harnesses when they already exist.
   - Prefer repo-local target-selection, acceptance-summary, or ownership-triage
     scripts over reconstructing those reports by hand.
   - If no comparison harness exists, use the bundled
     `scripts/compare_commands.py` to preserve order-balanced raw runs and
     command identities.
   - If no harness exists, record a sampled profile first; do not build a local
     counter instrumentation plan as the first move.

4. Collect attribution with native profilers.
   - Use `perf record`, flamegraphs, or `samply` to choose targets.
   - Start with self time, then inspect children and callers.
   - Validate that samples come from the intended process or descendants, not
     only a launcher or waiting parent. A non-empty profile file is not enough.
   - Validate symbol and call-chain quality before trusting caller stacks.
   - Use frame-pointer builds only as an attribution aid unless the project
     already treats them as its normal benchmark build.

5. Escalate attribution only as needed.
   - Use this order: symbols and self time; children/folded callers; generated
     C/IR; annotated assembly and native symbol size; anchored debugger caller
     census.
   - Stop at the first level that credibly explains the normal source path.

6. Inspect generated C when ownership or allocation is involved.
   - Source-level uniqueness probes are not enough for Lean performance claims.
   - Draw the ownership graph through the entire call chain, including result
     variants, error paths, callbacks, and closure captures.
   - Before concluding that Lean lacks an ownership operation, compare a small
     faithful source-shape matrix: direct versus nested update, branch-local
     versus post-join update, and inline versus noinline helper placement.
   - Check generated C for runtime calls and ownership shape, then confirm with
     sampled profiles and harness-level acceptance numbers.

7. Accept changes only with a complete performance story.
   - State the measured hotspot, the changed normal code path, the before/after
     evidence, and any correctness tests.
   - Track native code and key symbol sizes when factoring or inlining changes.
   - Collect a fresh post-change profile and verify that the original caller or
     cost bucket moved as predicted.
   - Document failed candidates so future work does not rediscover them.

## Reference Routing

- Read [profiling-loop.md](references/profiling-loop.md) for concrete `perf`,
  flamegraph, `samply`, frame-pointer, and measurement-loop commands, plus the
  order-balanced invocation of the bundled `scripts/compare_commands.py`.
- Read [generated-c-ownership.md](references/generated-c-ownership.md) when the
  profile points at Lean runtime allocation, reference counting, persistent data
  structure copies, or suspected linearity issues.
- Read [benchmark-design.md](references/benchmark-design.md) before adding or
  interpreting benchmark suites, focused fixtures, historical reports, or
  baseline/candidate comparisons.
- Read [experiment-record.md](references/experiment-record.md) when creating an
  acceptance bundle, experiment ledger, or accepted/rejected candidate note.
- Read [ml-lab-case-study.md](references/ml-lab-case-study.md) only for ml-lab
  work or for analogous Lean interpreters/runtimes where faithful execution,
  linked bytecode, and runtime-state locality matter.

## Guardrails

- Do not optimize a focused extraction without reconnecting it to the
  representative workload.
- Do not trust broken call chains with large `[unknown]` sections, small integer
  return addresses, or impossible callers.
- Do not add benchmark-pattern recognizers, one-off mini-interpreters, or
  workload-specific fast paths unless the user explicitly wants an experiment.
- Keep diagnostics, logging, tracing, and ownership probes out of headline
  benchmark mode unless the run is measuring their overhead.
- Do not add local runtime counters to discover Lean hotspots unless the user
  explicitly requests an experiment; prefer native samples and generated C/IR.
- Label hashes, generated code, and code size as deterministic evidence. Label
  timing, counters, and sampled profiles as noisy evidence; do not merge their
  confidence claims.
