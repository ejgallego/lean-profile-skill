---
name: lean-profile-skill
description: Investigate Lean performance with separate workflows for public build/edit-to-output latency, module elaboration, and compiled native runtime. Use for measured experiments, Lean or Lake phase attribution, perf/samply and generated-C analysis. Start build and elaboration investigations with Lake and Lean frontend evidence; use native sampling after locating a substantial native runtime cost.
---

# Lean Performance Profiling

Use this skill to turn a vague Lean speed problem into comparable measurements,
credible attribution, and an optimization case that can be safely landed.

## Choose the timing boundary

- For public build latency, edit-to-output, Lake planning or module elaboration,
  read [build-and-elaboration.md](references/build-and-elaboration.md). Start with
  the public command, affected jobs and Lean frontend evidence.
- For Verso documents, also read [verso-builds.md](references/verso-builds.md) for
  authored-module compilation, generator execution and project-specific checks.
- For compiled executable runtime and generated native code, use the native
  workflow below. Enter it from a build investigation when native execution is
  a substantial part of the public wall time.

Keep public commands, nested module diagnostics and direct executable timings
separate. Another project's hotspot is a hypothesis, not evidence for this one.

## Native runtime lessons

Do not use a counter-first strategy for native runtime optimization. Runtime
counters, helper timers, and aggregate hardware counters tend
to say that something is expensive without identifying the compiler/runtime
ownership path that made it expensive. Use sampled profiles and generated C/IR
for attribution. Use counters only after that, as coarse acceptance or
regression evidence from an established harness.

Do not infer a missing Lean ownership feature from one slow source shape.
Separate three questions: whether Lean can express the exclusive update,
whether control flow keeps the owned token visible at the mutation, and whether
inlining or specialization duplicates too much generated code. Test those
dimensions explicitly before proposing a compiler feature or native override.

## Native runtime workflow

1. Define the workload before profiling.
   - Prefer a representative command the user actually cares about.
   - Add focused or micro workloads only after the representative run identifies
     a cost class.
   - Record the command, hashes for inputs and binaries, commit and worktree
     state, toolchain, build mode, diagnostics, event list, repeat policy, and
     expected terminal state.

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

4. Collect attribution with native profilers.
   - Use `perf record`, flamegraphs, or `samply` to choose targets.
   - Start with self time, then inspect children and callers.
   - Validate that samples come from the intended process or descendants, not
     only a launcher or waiting parent. A nonempty profile file is not enough.
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
   - Check generated C for runtime calls and ownership shape, then confirm with
     sampled profiles and harness-level acceptance numbers.

7. Accept changes only with a complete performance story.
   - State the measured hotspot, the changed normal code path, the before/after
     evidence, and any correctness tests.
   - Track native code and key symbol sizes when factoring or inlining changes.
   - Collect a fresh post-change profile and verify that the original caller or
     cost bucket moved as predicted.
   - Document failed candidates so future work does not rediscover them.

## Native reference routing

- Read [profiling-loop.md](references/profiling-loop.md) for concrete `perf`,
  flamegraph, `samply`, frame-pointer, and measurement-loop commands, plus the
  order-balanced invocation of the bundled `scripts/compare_commands.py`.
- Read [generated-c-ownership.md](references/generated-c-ownership.md) when the
  profile points at Lean runtime allocation, reference counting, persistent data
  structure copies, or suspected linearity issues.
- Read [runtime-mechanics.md](references/runtime-mechanics.md) when interpreting
  boxing or object-layout costs, atomic reference counting, task scheduling,
  synchronization, or channel behavior before choosing an optimization.
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
- Label hashes, generated code, and code size as deterministic evidence. Label
  timing, counters, and sampled profiles as noisy evidence; do not merge their
  confidence claims.
