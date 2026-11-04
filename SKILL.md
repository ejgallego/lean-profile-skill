---
name: lean-profile-skill
description: Investigate Lean performance across public build/edit-to-output latency, module elaboration, native runtime, and browser/Wasm widgets. Use for measured experiments, Lean or Lake phase attribution, perf/samply and generated-C analysis, browser sampled attribution, or reusable evidence reports. Start build investigations with Lake and Lean frontend evidence; choose runtime profiling for the actual execution backend.
---

# Lean Performance Profiling

Use this skill to turn a vague Lean speed problem into comparable measurements,
credible attribution, and an optimization case that can be safely landed.

Paths to `scripts/`, `references/` and `assets/` are relative to this file's
directory. Resolve it once; the references call it `$skill_dir`.

## Choose the timing boundary

- For public build latency, edit-to-output, Lake planning or module elaboration,
  read [build-and-elaboration.md](references/build-and-elaboration.md). Start with
  the public command, affected jobs and Lean frontend evidence.
- For a whole-library or compiler survey that selects modules to profile, also
  read [compiler-surveys.md](references/compiler-surveys.md).
- For Verso documents, also read [verso-builds.md](references/verso-builds.md) for
  authored-module compilation, generator execution and project-specific checks.
- For compiled executable runtime and generated native code, use the native
  workflow below. Enter it from a build investigation when native execution is
  a substantial part of the public wall time.
- For Lean-backed browser widgets, Wasm or VIR/FIR comparisons, read
  [browser-wasm.md](references/browser-wasm.md). Reuse the project's browser
  harness; distinguish decode, component work, DOM observation and paint.
- For a technical report, timelines or a profile gallery, read
  [profile-review.md](references/profile-review.md). The bundled builder consumes
  explicitly included raw observations and linked captures; it runs no benchmarks.
  For a pull request, the evidence bundle in
  [benchmark-design.md](references/benchmark-design.md#evidence-bundle) is usually
  enough. Evidence directories are often gitignored, so quote the numbers, commands
  and hashes in the description instead of linking local paths.

Keep public commands, nested module diagnostics and direct executable timings
separate. Another project's hotspot is a hypothesis, not evidence for this one.

If the public number does not match the complaint, say so first. Bound the worst
case you can reach, list what you did not measure, and ask which command and hardware
the user means, rather than explaining a slowness you could not reproduce.

## Running unattended

Profiling work outlives tool calls and shells, and a blocked call looks like a
hang. These habits keep a capture alive and its evidence trustworthy:

- Estimate a capture before starting it. Prefer the host's managed long-running
  execution and bounded polling where it has them, and a background job otherwise.
  Either way retain the log in the evidence directory, and keep the workload's
  hard deadline separate from the host's polling interval.
- Assume any run that edits source can be killed. Work in a disposable copy where
  you can; otherwise keep a crash-safe restoration and verify source hashes after.
- Never start an interactive viewer. `lake samply` needs `--no-serve`,
  `samply record` needs `--save-only`, and `samply load` and
  `trace.profiler.serve=true` both serve until stopped. Run a report's HTTP
  server in the background, and stop whatever you started before finishing.
- Keep evidence in `_out/performance/<campaign>/` or the project's established
  equivalent, not in temporary storage. A restart can empty temporary directories
  and end a long investigation with nothing retained. If that path is not ignored,
  add it to `.git/info/exclude` instead of changing the project's `.gitignore` just
  for the investigation.
- Run timing samples sequentially, with no parallel builds, agents or test suites
  on the machine. If the host is shared, record its load and limit the claim.
- Report environment blockers rather than changing them. Kernel profiling
  settings belong to the user.
- Native runtime work needs a sampling profiler. If none is permitted, stop and say
  so: do not substitute timings, counters or a debugger census for attribution, and
  do not change code on a guess.
- Scale evidence to the decision. An effect of orders of magnitude does not need
  the sampling a 3% claim does, while landing evidence still needs output checks,
  an after-profile and the limits of what was measured.

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

Before anything else, run `python3 "$skill_dir/scripts/check_sampling.py"`. It
probes each sampling backend and names the one to use. On exit 3 no backend is
permitted: relay its message, which says what the machine's owner can change, and
stop until they have.

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
   - Copy the built executable into the evidence directory before editing source,
     because `lake build` replaces it and the baseline is otherwise gone.
   - Preserve raw runs. Use AB/BA or another order-balanced pair when elapsed
     time is sensitive to temperature or background load.
   - Prefer repo-local harnesses when they already exist.
   - Prefer repo-local target-selection, acceptance-summary, or ownership-triage
     scripts over reconstructing those reports by hand.
   - If no comparison harness exists, use the bundled
     `scripts/compare_commands.py` to preserve order-balanced raw runs and
     command identities.
   - Check that the outputs agree on more inputs than the benchmark uses, without
     timing them, with `scripts/compare_outputs.py`.
   - To report retained harness captures, read
     [command-import.md](references/command-import.md). Importing does not validate
     outputs; explicit checks determine statistical inclusion, independently of
     the optimization decision.

4. Collect attribution with native profilers.
   - Use the backend that `check_sampling.py` selected; the
     [backend preflight](references/profiling-loop.md#backend-preflight) explains
     its probes. `perf stat` succeeding does not show that sampling works.
   - For a Lake executable target, prefer `lake samply` when the pinned
     toolchain provides it (Lean 4.36 onward) and the kernel permits it; it builds
     the target and demangles Lean names. Otherwise use `perf record` or the
     project's profiler. `scripts/summarize_profile.py` reads `lake samply` and
     `perf script` output from a terminal and flags truncated stacks.
   - Start with self time, then inspect children and callers. Classify the hot
     leaves before choosing a hypothesis: copying, allocation, cheap work repeated
     far more often than the input predicts, waiting and startup each lead to a
     different check ([classes](references/profiling-loop.md#classifying-the-hot-leaf)).
   - Validate that samples come from the intended process or descendants, not
     only a launcher or waiting parent. A nonempty profile file is not enough.
   - Validate symbol and call-chain quality before trusting caller stacks. Named
     frames are not enough: confirm that stacks reach a thread entry.
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
     evidence, and any correctness tests; the
     [evidence bundle](references/benchmark-design.md#evidence-bundle) lists the rest.
   - Track native code and key symbol sizes when factoring or inlining changes.
   - Collect a fresh post-change profile and verify that the original caller or
     cost bucket moved as predicted.
   - Document failed candidates so future work does not rediscover them.

## Native reference routing

- Read [profiling-loop.md](references/profiling-loop.md) for concrete `perf`,
  flamegraph, `samply`, frame-pointer, and measurement-loop commands, plus the
  order-balanced invocation of the bundled `scripts/compare_commands.py`.
  Skip it only when the project's own harness already covers these.
- Read [generated-c-ownership.md](references/generated-c-ownership.md) when the
  profile points at Lean runtime allocation, reference counting, persistent data
  structure copies, or suspected linearity issues, or when a report attributes a
  cost to ownership.
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
  return addresses, impossible callers, or clean-looking stacks that stop after a
  few frames.
- Do not add benchmark-pattern recognizers, one-off mini-interpreters, or
  workload-specific fast paths unless the user explicitly wants an experiment.
- Keep diagnostics, logging, tracing, and ownership probes out of headline
  benchmark mode unless the run is measuring their overhead.
- Label hashes, generated code, and code size as deterministic evidence. Label
  timing, counters, and sampled profiles as noisy evidence; do not merge their
  confidence claims.
