# Profiling Loop

Use this reference for the concrete mechanics of profiling Lean executables.

## Contents

- Backend Preflight
- Lake Samply
- Measurement Loop
- Order-Balanced Comparison
- Phase Mapping
- Attribution Quality
- Attribution Escalation
- Controlled Windows
- Post-change Verification
- Reporting
- Harness Behavior

## Backend Preflight

Prefer a repository's established profiling harness. Otherwise, select a native
sampling backend before changing build flags.

The command examples in this reference use POSIX shell syntax. Translate command
discovery, variables, and redirection when working on Windows even though
`samply` itself supports Windows targets.

1. On Linux, read the kernel's sampling policy first, because it decides which
   backends can work at all:

   ```bash
   cat /proc/sys/kernel/perf_event_paranoid
   ```

   | Level | `samply`, `lake samply` | `perf stat` | `perf record` |
   | --- | --- | --- | --- |
   | 1 or lower | usually permitted | usually permitted | usually permitted |
   | 2 (a common default) | refuses to run | commonly per-process user events | commonly user-space only; see below |

   This is the typical result, not a guarantee: capabilities, distribution patches,
   seccomp and event availability also decide, so test rather than infer. Lowering
   the level needs root and is the user's decision. Do not change it, and do not stop
   at it either: at level 2, `perf` often still gives attribution.

2. Probe `perf record` as well as `perf stat`. At level 2, `perf stat` can succeed
   while a plain `perf record --call-graph` fails with
   `No fallback found for 'cycles:u' for error 13`, because a call graph asks for
   kernel frames too. Restrict both the event and the call chains to user space, which
   is enough for Lean executable work. This only probes permission to open the event;
   a nonempty capture of the real target must still show usable samples before any
   attribution:

   ```bash
   perf record -e cycles:u -F 997 --user-callchains --call-graph dwarf \
     -o /dev/null -- true
   ```

   Preserve the exact diagnostic if this fails. Do not silently replace attribution
   with elapsed timings.

3. For a Lake executable target, feature-detect Lake's integrated `samply`
   command. It first appears in Lean 4.36:

   ```bash
   lake --help | grep -E '^[[:space:]]+samply[[:space:]]'
   lake help samply
   ```

   Prefer it when available and the kernel permits it, because it builds the
   selected target in the Lake environment, symbolicates addresses and demangles
   Lean-generated names into the saved file.

4. On Linux, macOS, or Windows, standalone `samply` remains the fallback for older
   Lake versions, arbitrary binaries and wrappers that are not Lake executable
   targets. Its saved file holds unresolved addresses, so it needs the Firefox
   Profiler viewer; for reading results from a terminal, prefer `perf report`:

   ```bash
   command -v samply
   ```

5. If no applicable backend works, report the blocker and the attempted commands.
   Continue with workload definition and identity capture, but do not make a
   hotspot claim from timing alone.

## Lake Samply

For a supported pinned toolchain and a `lean_exe` target, use a fresh output
path and `--no-serve` for unattended capture:

```bash
profile_run_dir="_out/performance/<campaign>/baseline-001"
test ! -e "$profile_run_dir"
mkdir -p "$profile_run_dir"

lake samply --no-serve \
  -o "$profile_run_dir/profile-demangled.json.gz" \
  <exe-target> -- --rate 997 -- <exe-args>
```

The first `--` begins arguments forwarded to `samply record`; the second begins
the executable's arguments. Omit `--rate 997` or replace it with other supported
`samply record` flags when appropriate. `--no-serve` still performs symbolication
and Lean-name demangling, writes the profile and exits. `--raw` instead preserves
the raw profile without those post-processing steps. Use interactive serving
only when the user wants to inspect the profile immediately.

The result is compressed JSON meant for a viewer. To read it from a terminal:

```bash
python3 "$skill_dir/scripts/summarize_profile.py" \
  "$profile_run_dir/profile-demangled.json.gz" --top 20
```

It prints stack-depth p50/p95/max, each thread's weight, entry-reaching share and
unknown-frame share, then self, inclusive and leaf-first stack tables. `--tid`
selects one thread, `--thread` matches names and `--json` keeps a record. Judge stack
quality per thread: well-rooted helpers can mask broken stacks on the thread doing the
work, so the aggregate is only an overview. The automatic missing-caller warning
applies only when a selected thread carries at least 10% of selected weight and at
least 20 weight units; smaller threads remain visible in the table.

Low entry-reaching share is not by itself proof of broken unwinding. A high p95 with
many stacks ending at a similar deep level and repeated recursive frames can mean that
legitimate recursion reached the profiler's stack cap. Inspect those frames in the raw
profile. Shallow stacks that stop at implausible application frames across unrelated
paths remain suspect. In either case self time is usable, while inclusive and caller
shares describe only the captured prefixes.

The summarizer also reads Lean's `trace.profiler.output` files, where weights are scope
milliseconds, not samples, and a parent's "self" is the residual of everything its
children and the trace threshold left unattributed rather than a hotspot.

Record `lake --version`, `samply --version`, the exact target and arguments, the
profile hash, and the final executable hash. `lake samply` builds the target, so
confirm which binary it produced and whether the build changed it before using
the profile to explain separately measured timings. The capture is diagnostic:
do not use its elapsed duration as the headline acceptance measurement.

`lake samply` targets native executables. It does not replace Lean frontend
`trace.profiler`, browser/Wasm CDP capture, `perf stat`, or profiling an enclosing
public wrapper. For an arbitrary already-built command, retain the standalone
`samply record --save-only` workflow below.

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
intermediate artifacts, primarily C code, under `.lake/build/ir`.

Hash the executable and every relevant input after the build. The bundled
comparison script records SHA-256 identities for both executables and every
file passed through `--artifact`; when working manually, use the platform's
available SHA-256 tool.

For a compiler or launcher that loads the implementation from shared libraries,
also record the resolved process mappings and hash the libraries actually loaded.
An unchanged executable stub does not establish compiler identity. Record native
build IDs when available so profiles, symbols and mapped images can be joined.

Keep the build type explicit when it matters:

- `release` is the standard build for headline benchmarks;
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
profile_run_dir="_out/performance/<campaign>/baseline-001"
test ! -e "$profile_run_dir"
mkdir -p "$profile_run_dir"

perf record -e cycles:u -F 997 --user-callchains --call-graph dwarf \
  -o "$profile_run_dir/perf.data" -- .lake/build/bin/<exe> <args>

perf report --stdio --no-children -i "$profile_run_dir/perf.data" \
  --sort overhead,symbol --percent-limit 0.5
```

Use `--no-children` to see self-time target candidates. Use children-inclusive
views after the self-time view tells you which region matters. The warnings about
`kptr_restrict` and kernel samples are expected for a user-space recording.

Lean runs `main` on a spawned thread, so the recording must inherit threads. Options
such as `--per-thread` and `--no-inherit` silently lose the workload: a run that
collected 480 samples by default collected 7 with either one.

If the command launches the real workload through `env`, a shell script, a
daemon client, or another wrapper, verify the profiler follows the intended
descendant. Choose the harness's inherited/child-recording mode or record the
target executable directly. Immediately sanity-check the capture:

```bash
perf script -i "$profile_run_dir/perf.data" | head
perf script -i "$profile_run_dir/perf.data" | \
  rg -m 20 '<target-binary>|<project-symbol>|lean_'
```

For a terminal summary of a `perf` capture, including the stack-depth check below:

```bash
perf script -i "$profile_run_dir/perf.data" -F comm,tid,ip,sym | \
  python3 "$skill_dir/scripts/summarize_profile.py" - --top 20
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

5. Render flamegraphs when visual call paths would help. `stackcollapse-perf.pl`
and `flamegraph.pl` come from the separate FlameGraph repository and are often not
installed; `perf report` and `summarize_profile.py` do not need them:

```bash
perf script -i "$profile_run_dir/perf.data" > "$profile_run_dir/perf.script"
stackcollapse-perf.pl "$profile_run_dir/perf.script" \
  > "$profile_run_dir/perf.folded"
flamegraph.pl --title "Lean profile" "$profile_run_dir/perf.folded" \
  > "$profile_run_dir/profile.svg"
```

If `lake samply` is unavailable or the target is not a Lake executable, use
standalone `samply`:

```bash
samply record --save-only -o "$profile_run_dir/profile.json.gz" -- \
  .lake/build/bin/<exe> <args>
```

This needs `perf_event_paranoid` at 1 or lower. Use
`samply load "$profile_run_dir/profile.json.gz"` later when interactive browsing is
useful. `--no-open` alone still starts a local server and can block an unattended
agent.

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
  --out-dir _out/performance/<campaign>/compare-001
```

Two passes provide one AB/BA cycle for screening. Increase to a larger even
count for acceptance work, and repeat `--artifact` for every relevant input.

Before claiming a small effect, measure the noise: run the same binary as both
baseline and candidate under the identical schedule. The harness warns when the two
launchers are byte-identical, and that warning matters: an accidental A/A run of a
214 ms program over four passes reported a 7.6% median reduction, so check the hashes
of any two builds before interpreting them. Matching launchers alone are not an A/A
control, because they can load different libraries, resolve adjacent data differently
or branch on `argv[0]`. Control the loaded images, cwd, environment and inputs too.

Use each `--metadata` key once. Retained binaries carry no Git identity of their own and
the manifest records only the current commit, so name the two revisions, for example
`--metadata baseline_rev=<sha> --metadata candidate_rev=<sha>`.

Set a finite `--timeout-seconds` on any run that could stall. A short median, an output
difference between the two sides, or identical launchers each add a warning to
`summary.json`, so read that file before quoting a result. Matching stdout is not a
correctness check; it only flags an unintended change. See
[Harness Behavior](#harness-behavior) for what the script records and how it fails, and
[command-import.md](command-import.md#summary-conventions) for summary field names and the
shared positive-means-faster convention.

Pass `--perf-events` with
`cycles:u,instructions:u,branches:u,branch-misses:u,cache-references:u` only
after sampled attribution identifies a target. Collect headline elapsed times
in a comparison without `--perf-events`, then use a separate output directory
for the counter run. The script stores one counter file per measured run instead
of collapsing repetitions into an aggregate. Because `perf stat` can perturb
runtime, treat elapsed values from the counter run as diagnostics rather than
headline timings. `perf stat` inherits by default, so Lean's spawned main thread is
counted. Each `perf_stat` path in `runs.jsonl` is relative to the output directory.

To turn a retained capture into an evidence report, follow
[command-import.md](command-import.md). The importer preserves failed outcomes
and requires explicit correctness records before including timings in statistics.

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
- check how deep stacks go and whether they reach a thread entry such as `_start`
  or `start_thread` (`summarize_profile.py` reports both). Truncation can look clean:
  on Lean 4.36, `perf` DWARF stacks stopped two frames down at `lean_copy_expand_array`,
  named a real function as the caller and skipped the true one, with no `[unknown]`
  frame anywhere. A larger stack dump did not help, while `lake samply` reached thread
  entries on that workload, though not on every capture. Self time was still sound;
- compare `perf report --no-children` with call-graph views so bad unwinding
  does not hide a strong self-time target.
- record requested and observed sampling rate, sample/event losses, target
  thread coverage and known-versus-unknown frame share. Preserve rejected or
  lossy captures instead of silently lowering the rate and replacing them.

When call chains are poor, build a profiling binary with frame-pointer-friendly
C flags if the project supports it. These reach only the C that the project compiles,
so they do not repair stacks that break inside the prebuilt Lean runtime; use a census
for those:

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

A census counts who actually reaches a runtime function. This x86-64 gdb script reads
the return address at function entry:

```gdb
set pagination off
set confirm off
break lean_copy_expand_array_nonlinear
commands
silent
info symbol *(void**)$sp
cont
end
run
```

```bash
for args in '2000 50000' '0 1'; do
  gdb -q -batch -x census.gdb --args .lake/build/bin/<exe> $args 2>/dev/null | \
    rg ' in section' | sed -E 's/ \+ [0-9]+ in section.*//' | sort | uniq -c | sort -rn
done
```

Every hit stops the process, so shrink the workload. Pass arguments through `--args`
and leave `run` bare, because arguments or a redirect on `run` replace them. Always
pair it with a zero-work run: in a measured case, startup alone made 976 copies from
`lean_array_push`, unchanged by the workload, beside the 2000 from the real caller.

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

If the fix makes the run too short to sample, keep the same-path capture for the
comparison and add a scaled-up candidate-only capture for the remaining cost, labeled
diagnostic. Compare named buckets rather than percentages, since startup dominates a
millisecond run.

Treat a timing win without the predicted profile movement as an unresolved
result. Track executable and hot-symbol sizes before and after any factoring,
inlining, specialization, or generated-code-shape change.

## Reporting

Report what the [evidence bundle](benchmark-design.md#evidence-bundle) lists, scaled to
the decision. For an interim note, the exact command, identities and the next action or
rejected hypothesis are enough.

## Harness Behavior

You rarely need this unless a comparison fails or you are auditing a capture.

`compare_commands.py` refuses to overwrite an output directory. It stores raw JSONL rows,
command and artifact identities, dirty tracked patches, stdout and stderr with each run's
stdout hash, and paired savings. It hashes the selected `perf` executable and rechecks
command, profiler, artifact, Git revision and tracked-diff identities after execution. Each
completed profiler run must produce a nonempty counter file, whose SHA-256 the run row
records. Missing evidence or identity drift fails the comparison while preserving
`identity-check.json` and the partial run ledger.

Run rows distinguish ordinary exit, timeout, launch failure, evidence failure and
interruption. An interrupted run exits 130 after recording its row and final identity check.
Timeout and interrupt cleanup reach the process group on POSIX, not descendants that
deliberately start a new session, and only the direct process on Windows. Cleanup is bounded:
if it cannot be confirmed, for example because a sandbox refuses the group signal, the run
records why and the comparison fails instead of hanging.

Where the platform has `os.pidfd_open`, exit is observed without polling. Elsewhere, including
macOS, a deadline still polls, and the harness warns before running. The manifest records the
planned method as `elapsed_measurement.planned_exit_observation` and each run its actual
`exit_observation` (`pidfd`, `blocking-wait` or `timed-polling`). A run that used a different
method from the plan is invalid, because one polling arm could bias the comparison. Launch and
cleanup remain harness overhead. Older captures that set `--timeout-seconds` polled, which added
up to 50 ms depending on run length, so treat their short runs with care.
