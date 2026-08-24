# Profiling Loop

Use this reference for the concrete mechanics of profiling Lean executables.

## Contents

- Backend Preflight
- Measurement Loop
- Order-Balanced Comparison
- Phase Mapping
- Attribution Quality
- Attribution Escalation
- Controlled Windows
- Post-change Verification
- Reporting

## Backend Preflight

Prefer a repository's established profiling harness. Otherwise select a native
sampling backend before changing build flags:

The command examples in this reference use POSIX shell syntax. Translate command
discovery, variables, and redirection when working on Windows even though
`samply` itself supports Windows targets.

1. On Linux, use `perf` only after verifying that it is installed and permitted:

   ```bash
   command -v perf
   perf stat -e cycles:u -- true
   ```

   If the probe reports a permission or unsupported-event error, preserve the
   exact diagnostic. Do not silently replace attribution with elapsed timings.

2. On Linux, macOS, or Windows, use `samply` when it is installed and can record
   the target:

   ```bash
   command -v samply
   ```

3. If neither backend works, report the blocker and the attempted commands.
   Continue with workload definition and identity capture, but do not make a
   hotspot claim from timing alone.

## Measurement Loop

1. Capture context:

```bash
git status --short
git rev-parse --short HEAD
cat lean-toolchain 2>/dev/null || true
lake --version
python3 -c 'import platform; print(platform.platform())'
```

Capture this state before creating repo-local profile outputs. Prefer committed
baseline and candidate revisions. For a dirty candidate, save
`git diff --binary --full-index HEAD`, hash that patch, and separately hash every
task-relevant untracked source or input; `git diff` does not contain untracked
files.

2. Build once before measuring:

```bash
lake build <target>
file .lake/build/bin/<exe>
```

Lake normally places executables under `.lake/build/bin` and generated
intermediate artifacts, primarily C code, under `.lake/build/ir`. Keep the
build type explicit when it matters:

Hash the executable and every relevant input after the build. The bundled
comparison script records SHA-256 identities for both executables and every
file passed through `--artifact`; when working manually, use the platform's
available SHA-256 tool.

- `release` is the normal headline benchmark shape;
- `debug` uses `-O0 -g` and is for debugging/attribution, not headline speed;
- `relWithDebInfo` keeps optimization with debug info and can be useful for
  attribution if the project supports it;
- put profiling-critical `leanc` flags in `moreLeancArgs` so Lake invalidates
  the affected build trace;
- do not use `weakLeancArgs` for frame-pointer or debug-info changes unless the
  affected artifacts are explicitly invalidated and the rebuilt binary hash is
  verified. Those arguments can change without triggering a rebuild.

3. Record sampled profiles:

For Lean performance work, start with attribution. Counter-first profiling has
failed in practice because it tends to identify symptoms rather than the
compiler/runtime ownership path that caused them.

```bash
profile_run_dir="_profiles/baseline-001"
test ! -e "$profile_run_dir"
mkdir -p "$profile_run_dir"

perf record -F 997 --call-graph dwarf -o "$profile_run_dir/perf.data" -- \
  .lake/build/bin/<exe> <args>

perf report --stdio --no-children -i "$profile_run_dir/perf.data" \
  --sort overhead,symbol --percent-limit 0.5
```

Use `--no-children` to see self-time target candidates. Use children-inclusive
views after the self-time view tells you which region matters.

If the command launches the real workload through `env`, a shell script, a
daemon client, or another wrapper, verify the profiler follows the intended
descendant. Choose the harness's inherited/child-recording mode or record the
target executable directly. Immediately sanity-check the capture:

```bash
perf script -i "$profile_run_dir/perf.data" | head
perf script -i "$profile_run_dir/perf.data" | \
  rg -m 20 '<target-binary>|<project-symbol>|lean_'
```

Reject a capture whose samples are only loader, wrapper, shell-wait, or launcher
frames. File size and sample count alone do not validate attribution. Likewise,
an empty `perf report` is a failed preflight even if `perf record` exited zero;
check event compatibility and inspect `perf script` before continuing.

4. Use counters only after attribution:

```bash
perf stat \
  -e cycles:u,instructions:u,branches:u,branch-misses:u,cache-references:u \
  -o "$profile_run_dir/perf-stat.txt" \
  -- .lake/build/bin/<exe> <args>
```

Use user-space events (`:u`) for Lean executable work unless kernel time is the
subject. For baseline/candidate repeats, use the order-balanced comparison
below. Keep warmups separate from measured samples. Treat counters as acceptance
or regression evidence after a target is known, not as the way to find the
target.

5. Render flamegraphs when visual call paths help:

```bash
perf script -i "$profile_run_dir/perf.data" > "$profile_run_dir/perf.script"
stackcollapse-perf.pl "$profile_run_dir/perf.script" \
  > "$profile_run_dir/perf.folded"
flamegraph.pl --title "Lean profile" "$profile_run_dir/perf.folded" \
  > "$profile_run_dir/profile.svg"
```

If FlameGraph scripts are not installed, use `samply`:

```bash
samply record --save-only -o "$profile_run_dir/profile.json.gz" -- \
  .lake/build/bin/<exe> <args>
```

Use `samply load "$profile_run_dir/profile.json.gz"` later when interactive
browsing is wanted. `--no-open` alone still starts a local server and can block
an unattended agent.

## Order-Balanced Comparison

If the repository has no comparison harness, resolve this skill directory as
`skill_dir`, then run:

```bash
python3 "$skill_dir/scripts/compare_commands.py" \
  --baseline '["./baseline/run", "arg"]' \
  --candidate '["./candidate/run", "arg"]' \
  --artifact path/to/input \
  --artifact lean-toolchain \
  --metadata build=release \
  --metadata diagnostics=off \
  --passes 2 --warmups 1 \
  --out-dir _profiles/compare-001
```

Two passes provide one AB/BA cycle for screening. Increase to a larger even
count for acceptance work, and repeat `--artifact` for every relevant input.
Use each `--metadata` key once. The script refuses to overwrite an existing
output directory and stores raw JSONL rows, command and artifact identities,
dirty tracked patches, stdout/stderr, paired deltas, and warnings about short or
minimally repeated runs. It hashes the selected `perf` executable and rechecks
command, profiler, artifact, Git revision, and tracked-diff identities after
execution. Each completed profiler run must produce a nonempty counter file;
the run row records its SHA-256. Missing evidence or identity drift makes the
comparison fail while preserving `identity-check.json` and the partial run
ledger. Run rows distinguish ordinary exit, timeout, launch failure, evidence
failure, and interruption. An interrupted run exits 130 after recording its row
and final identity check. On POSIX systems, timeout and interruption terminate
the command's process group so descendant work does not contaminate later runs.

Pass `--perf-events` with
`cycles:u,instructions:u,branches:u,branch-misses:u,cache-references:u` only
after sampled attribution identifies a target. The script then stores one
counter file per measured run instead of collapsing repetitions into an
aggregate.

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

- confirm the sampled process names and mapped binaries include the intended
  executable or descendants;
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
