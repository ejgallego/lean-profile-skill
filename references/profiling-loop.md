# Profiling Loop

Use this reference for the concrete mechanics of profiling Lean executables.

## Contents

- Measurement Loop
- Phase Mapping
- Attribution Quality
- Attribution Escalation
- Counter Trap
- Controlled Windows
- Post-change Verification
- Reporting

## Measurement Loop

1. Capture context:

```bash
git status --short
git rev-parse --short HEAD
cat lean-toolchain 2>/dev/null || true
lake --version
```

2. Build once before measuring:

```bash
lake build <target>
file .lake/build/bin/<exe>
```

Lake normally places executables under `.lake/build/bin` and generated
intermediate artifacts, primarily C code, under `.lake/build/ir`. Keep the
build type explicit when it matters:

- `release` is the normal headline benchmark shape;
- `debug` uses `-O0 -g` and is for debugging/attribution, not headline speed;
- `relWithDebInfo` keeps optimization with debug info and can be useful for
  attribution if the project supports it;
- extra `leanc` flags in `moreLeancArgs` affect build traces, while
  `weakLeancArgs` can be changed without forcing the same rebuild semantics.

3. Record sampled profiles:

For Lean performance work, start with attribution. Counter-first profiling has
failed in practice because it tends to identify symptoms rather than the
compiler/runtime ownership path that caused them.

```bash
perf record -F 997 --call-graph dwarf -o perf.data -- \
  .lake/build/bin/<exe> <args>

perf report --stdio --no-children -i perf.data \
  --sort overhead,symbol --percent-limit 0.5
```

Use `--no-children` to see self-time target candidates. Use children-inclusive
views after the self-time view tells you which region matters.

4. Use counters only after attribution:

```bash
perf stat -r 5 \
  -e cycles:u,instructions:u,branches:u,branch-misses:u,cache-references:u \
  -- .lake/build/bin/<exe> <args>
```

Use user-space events (`:u`) for Lean executable work unless kernel time is the
subject. Increase repeats when the command is short or noisy. Keep warmups
separate from measured samples. Treat these totals as acceptance or regression
evidence after a target is known, not as the way to find the target.

5. Render flamegraphs when visual call paths help:

```bash
perf script -i perf.data > perf.script
stackcollapse-perf.pl perf.script > perf.folded
flamegraph.pl --title "Lean profile" perf.folded > profile.svg
```

If FlameGraph scripts are not installed, use `samply`:

```bash
XDG_CACHE_HOME=/tmp/samply-cache \
  samply record --no-open -- .lake/build/bin/<exe> <args>
```

## Phase Mapping

Before changing source, map where time is spent across the user-visible
command. Distinguish phases such as process startup, artifact loading, parsing,
initialization, steady execution, and output/shutdown. Use the least intrusive
available anchor:

1. temporal flamegraph/sample bands;
2. existing phase markers or trace events;
3. stable program counters or input boundaries;
4. a controlled slice/window when setup otherwise hides the region.

Record the full command's phase boundaries and reconnect every slice result to
that command. A snapshot can retain state and change Lean ownership, so use
snapshot replay for boundary discovery or throughput only unless generated
C/runtime evidence shows that ownership is unchanged.

## Attribution Quality

Before acting on a sampled profile:

- check `file .lake/build/bin/<exe>` reports symbols/debug info when expected;
- check `nm -n .lake/build/bin/<exe> | rg 'lean_|<project symbol>'`;
- reject call chains with large `[unknown]` sections, small integer return
  addresses, impossible callers, or stacks that end in nonsense addresses;
- compare `perf report --no-children` with call-graph views so bad unwinding
  does not hide a strong self-time target.

When call chains are poor, build a profiling binary with frame-pointer-friendly
C flags if the project supports it:

```text
-fno-omit-frame-pointer
-mno-omit-leaf-frame-pointer
-fasynchronous-unwind-tables
```

Use that binary to repair attribution. Do not mix frame-pointer build timings
with normal build timings unless the project accepts that build mode as the
benchmark target.

## Attribution Escalation

Escalate in this order:

1. Confirm binary symbols and inspect self-time targets.
2. Inspect children-inclusive and folded caller views.
3. Inspect generated C/IR for retains, releases, copies, allocation, closure
   construction, and code duplication.
4. Inspect annotated assembly, disassembly, and native symbol size when the
   compiler's code placement or inlining is implicated.
5. Use an anchored debugger breakpoint/return-address census only when profiler
   stacks remain truncated or several callers are indistinguishable.

Do not jump directly to debugger instrumentation when samples and generated
code already explain the caller. Record why each escalation was necessary.

## Counter Trap

Do not add Lean/runtime counters as the default way to discover hotspots. This
strategy has failed on Lean systems because counters and helper timers often:

- perturb the code shape being measured;
- miss ownership changes introduced by the compiler and runtime;
- flatten several caller paths into one aggregate number;
- encourage optimizing a diagnostic fixture instead of the representative path.

Use counters only when they are already part of a stable harness or when a user
explicitly requests a counter experiment. Even then, pair them with samples and
generated C/IR before deciding what to change.

## Controlled Windows

If startup, parsing, loading, or snapshot setup dominates the profile, isolate
the useful window before changing code. Prefer project-supported slice or
snapshot modes. If none exist, use a smaller representative input rather than a
hand-written hot loop.

For long-running commands:

- bound the Lean command itself with a real fuel, input size, or timeout;
- do not rely only on profiler duration flags, because profilers may wait for
  the command to exit;
- keep full-run evidence around after any slice points to a candidate fix.

## Post-change Verification

After measuring a candidate, collect a fresh sampled profile through the same
representative path. Confirm at least one of:

- the original hot caller disappeared or shrank;
- the predicted runtime bucket moved by the expected amount;
- a new dominant cost replaced it and explains the remaining time.

Treat a timing win without the predicted profile movement as an unresolved
result. Track executable and hot-symbol sizes before and after any factoring,
inlining, specialization, or generated-code-shape change.

## Reporting

Every profiling note should include:

- exact command and input;
- binary/input hashes, path, commit, and worktree state;
- profiler and event list;
- repeat/warmup policy;
- execution order and raw samples;
- expected and observed terminal state;
- headline elapsed time or harness-provided aggregate counters;
- sampled-profile target and confidence notes;
- generated-code and native-size evidence when relevant;
- post-change profile readout;
- accepted next action or rejected hypothesis.
