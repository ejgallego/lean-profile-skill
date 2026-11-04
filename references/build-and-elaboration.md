# Build latency and Lean elaboration

Use this mode for edit-to-output, no-change, clean-build, Lake, or Lean frontend
work. It shares evidence practices with native profiling, but native sampling
is a later tool choice, not the starting assumption. Treat each repository as
a fresh workload; another project's bottlenecks are hypotheses only.

For Verso projects, also read [verso-builds.md](verso-builds.md) for the
document/generator stages, deferred blocks, highlighting and project wrappers.
For a whole-library or compiler-build survey that selects modules and semantic
callers for deeper profiling, also read
[compiler-surveys.md](compiler-surveys.md).

## Establish the public boundary

Start with the project's documented public command and its real endpoint.
For a library, that may be `lake build LibraryTarget` through completion of its
requested artifacts. For an executable, distinguish building/linking the binary
from a command that also runs it. Record only endpoints actually observed.
`lake env`, `lake exe`, a direct binary, and `lean --run` have different setup
and build costs; diagnostic timings at those boundaries cannot replace a public
command comparison. Site-generation boundaries are covered in the Verso reference.

Before measurement, identify the edited source modules, requested Lake targets,
dependency graph, expected artifacts, and executable entry points or external
tools where applicable. Check Lean module-system status, `precompileModules`,
and, when the pinned toolchain supports them, `precompileImports` and
`precompileLibrary`. Check declared dependencies for non-Lean inputs (for
example, `include_str` files and their Lake `needs`). Record repository/worktree
identities and patches, toolchain and dependency revisions, manifest hash,
platform/CPU/core count, and artifact/OS-cache policy. Keep experiments isolated
from the author's checkout.

Choose a representative edit that invalidates the same source on each run.
Keep the scope of invalidation comparable, whether editing a proof, definition
or another source input. Lake compares content hashes, so `touch` alone rebuilds
nothing, and the rebuild cone depends on the kind of edit. A trailing comment can
rebuild one module while a comment that shifts later lines rebuilds its importers, so
measure the kinds the user actually makes separately.

Declare whether the artifact cache is part of the workload, because the two claims
need opposite controls:

- A public edit-to-output claim with the cache on includes its hits. They are what
  the user experiences, so preseed or freeze the declared cache state and retain the
  hits rather than engineering them away.
- A compile-cost claim that excludes the cache needs a reproducibly fresh build state
  and a fresh empty cache for every sample, or a pinned-toolchain method that disables
  artifact-cache reads. Neither half is enough alone: a fresh worktree still reads the
  toolchain or system cache unless `LAKE_CACHE_DIR` is isolated, an empty cache leaves
  `.lake/build` outputs in place, and one cache for a whole campaign is no longer empty
  after its first sample. Lake's `--no-cache` does not help: it stops package
  build-cache downloads, while local artifact reuse follows `enableArtifactCache`.

Hits are silent. With a shared cache, a second identical line shift restores the
importers, and a new field whose name never reaches the C restores the C objects, even
though the source differs both times; this invalidated 11 of 51 samples in one
campaign. Varying the edit to dodge the cache also changes what is measured, so prefer
a frozen edit in fresh states, or justify the family of edits. When the rebuild cone is
part of the declared workload, gate each sample on the exact job identities: a count
can stay constant while different jobs run. Record source hashes and affected jobs, then verify the
expected artifacts or behavior with workload-specific checks outside the timed
interval. For example, check required declarations for a library or expected
results for an executable. Compare candidate/control semantics appropriate to
the change; do not normalize away the behavior being tested. No-change samples
must preserve source inputs. Account for generated-source timestamps or other
clock-dependent inputs when present. Verso prose and HTML checks belong to its
workload-specific protocol.

Warm dependencies and the caches enabled in the workload. Do not silently
enable a separate artifact-download cache for the experiment. For affordable
runs, seven to nine measured samples per configuration after a warmup are a
practical starting point. Choose the trial count according to run cost, observed
noise, expected effect size and the strength of the acceptance claim; no fixed
count establishes validity. Record the sampling plan and any stopping rule,
and state the limits of small or noisy captures. Follow a user's explicit
measurement protocol when one is given.

Rotate candidate/control order and retain actual execution order. Use fresh
numbered log directories and separate generated outputs where applicable, while
retaining incremental build artifacts according to the declared cache policy.
Record wall/user/system time, peak RSS, exit status, validation, and affected jobs.
Report median, IQR with its chosen
quantile convention, range, paired deltas and exclusions. Apply exclusions to
matched pairs with a recorded reason; do not keep only the favorable member.

Project-clean with dependencies warm, dependency-clean, first bootstrap with
network acquisition, and OS-cold are distinct workloads. Do not clear shared
caches to manufacture cold runs; use isolated caches/artifact directories when
needed and describe the achievable boundary. A project with
`enableArtifactCache` can otherwise answer a repeated edit from the shared cache, so
keep `LAKE_CACHE_DIR` inside the campaign, where samples neither read nor fill the
user's cache, and use a new one per sample when the cache is excluded. It grows with
every build, reaching several gigabytes in one short campaign. It is not evidence, so
delete it when the campaign ends.

## Attribute without conflating phases

1. Record exactly which Lake jobs rebuild and their durations; construct the
   dependency critical path. Parallel job CPU/durations are not serial wall time.
   In a multi-module survey, retain module keys and phase data before aggregation;
   confirm selected modules in isolation because their build durations include
   parallel contention. `lake build -v` logs each job's exact `lean` command. To
   replay a module without contention, reuse that command with temporary outputs,
   so that Lake's artifacts stay untouched and the imports stay the build's own:

   ```bash
   lake env lean Pkg/Module.lean --setup .lake/build/ir/Pkg/Module.setup.json \
     -o "$tmp/m.olean" -i "$tmp/m.ilean" -c "$tmp/m.c" --json
   ```

   A file holding only the module's imports gives its import-loading floor, which
   is often a large share of a short module's time. Older toolchains may lack
   `--setup`; check `lean --help`. `lake env` itself costs time (0.3 s on one project,
   more than half of a measured import floor), so for floors resolve `LEAN_PATH` once
   with `lake env printenv LEAN_PATH` and call `lean` directly.
2. Separate Lake setup/planning from module jobs, C compilation, linking and
   other subprocesses actually present. If the public command also executes a
   built program, distinguish its startup, work and shutdown from the build.
   On toolchains that expose LeanIR generation as its own Lake job (Lean 4.36
   onward), distinguish `elabArts` from `irArts`. The deprecated `leanArts` facet delegates to
   `irArts`, so it is too coarse for attributing that boundary.
3. Profile affected Lean modules with the toolchain's supported `--profile`,
   `profiler` options or `trace.profiler`. Inspect imports, initialization,
   elaboration, interpretation, compiler transformations, linters and tactics.
   Read toolchain help/local code for exact flags instead of assuming versions.
   `--profile` reports each declaration or step above `profiler.threshold`, then
   cumulative category totals, so a quiet run does not mean a cheap module: read the
   totals and lower the threshold before concluding that nothing stands out.
   A current noninteractive trace capture has this shape:

   ```bash
   lake env lean \
     -Dtrace.profiler=true \
     -Dtrace.profiler.output=_out/performance/<campaign>/profile.json \
     Module.lean
   ```

   The output is Firefox Profiler JSON; `$skill_dir/scripts/summarize_profile.py`
   reads it from a terminal, though `--profile` is usually the better first view. Add `--setup` as above for a module whose imports need
   Lake's setup. Verify the flags against the pinned Lean version. `trace.profiler.serve=true`
   is an interactive convenience and can keep the process serving the trace;
   do not use it in an unattended timing loop. These traces describe Lean
   frontend scopes, not native CPU samples or the full public wall-time boundary.
4. Add coarse monotonic markers around identified phases. Preserve a common
   clock origin and event scope. Attribute expensive enclosing elaborators with
   finer markers only where useful; an enclosing elaborator may aggregate work
   from several declarations, tactics or deferred actions.
5. Inspect subprocess creation when external helpers could account for the cost,
   and to separate Lean, C compilation and linking on the real parallel timeline.
   This is a separately labeled diagnostic, not a timing sample:

   ```bash
   strace -f --seccomp-bpf -ttt -q -e trace=execve,exit_group \
     -o "$campaign/strace.trace" lake build
   ```

   `-q` keeps the `+++ exited` lines that close each interval; `-qq` removes them.
   Use native sampling only once native runtime is a material part of the public
   wall time. Then follow the native workflow in SKILL.md.

`interpretation` does not mean avoidable VM overhead: it can include execution
of native callees. Precompilation can move work between profiler categories.
Compare total/public costs and finer source scopes before claiming a win.

A public invocation-to-olean interval includes orchestration, imports, compiler
work and serialization; do not label it pure elaboration. Parent scopes include
children; workers and build jobs overlap. Separately summarized interval medians
need not sum to median wall time. Label sums from separate diagnostic runs
approximate, and keep instrumented evidence separate from included wall samples.

## Test one mechanism at a time

Use the established command, edit and output gate for candidate/control pairs.
Track source changes and exact dependencies through a commit tree. Sibling
branch improvements are not additive until the combined configuration is tested.

Workload-dependent lessons worth checking, not assuming:

- Precompilation may improve warm generation while increasing clean-build cost.
  Native initialization may also activate unrelated linters and change output.
- Where supported (Lean 4.35 onward), test `precompileImports` and `precompileLibrary` as distinct
  configurations rather than aliases for `precompileModules`: they move
  different compilation work across the module/library boundary. Measure their
  no-change, representative-edit and clean-build costs separately.
- Moving generated timestamps out of dependency-bearing source removes unwanted
  invalidation, rather than making elaboration itself faster.
- Manifest reuse needs a validity contract; a retained Lake workspace additionally
  needs real source/artifact invalidation. They are different mechanisms.
- Serialized data can reduce constructor elaboration but move work to runtime
  reconstruction. Externalized data can avoid native recompilation but requires
  explicit Lake dependencies, refresh rules and missing/corrupt-data checks.
- Before replacing a representation, inspect the concrete caller and existing
  serialization. A large final command does not prove its final constant is large.
- Development modes that omit normal work are feature tradeoffs. State which
  behavior or checks they retain when comparing them with the normal workflow.

For a cached or externalized artifact, validate source edits, imported-dependency
edits, exporter edits, deletion, corruption and failed compilation as applicable.
Check that the public command never publishes stale output. A direct executable
may bypass the refresh protocol; document the supported command boundary.

## Reusable outputs

Keep raw samples, identities, command logs, affected-job lists, traces, patches,
validation and decisions under a local `_out/performance/<campaign>/` (or the
project's established equivalent). Reuse the repo's build-aware harness. The
bundled `compare_commands.py` is for stable command/binary comparisons: its
identity checks are not an edit-invalidation protocol, and it does not itself
supply all build resource/job metrics or fresh-output/validation hooks.

Without such a harness, write a small campaign script instead of timing edits by
hand: apply the declared edit, time `lake build -v` under `/usr/bin/time -v` with the log
retained, parse the built jobs, restore the source in a `finally`, and append a JSONL
row. Job lines look like `ℹ [47/114] Built Pkg.Module (2.1s)`, in `ms` or `s`, and
`Built Pkg.Module:c.o (with exports)` for C objects. Prefer observed job timing and
actual dependency edges where the project exposes them. Stock Lake logs carry no
scheduler graph, and that limit belongs in the report: `import` lines give only an
approximate module-elaboration view, which omits IR, C, linking, custom jobs and
non-source inputs, so do not call it the public build's critical path. Run the
campaign under the host's long-running execution, and check that the binaries return
to their original hashes after the restoring rebuild. If the project does not ignore `_out/`, add it to `.git/info/exclude` so that
tracked files stay untouched and gigabytes of evidence cannot be committed by accident.

Keep project-specific edits, instrumentation and invalidation in local adapters
rather than hard-coding a textbook or Blueprint workload into the shared skill.

For reusable report generation and trace-quality conventions, read
[profile-review.md](profile-review.md). Keep baseline, diagnostics, each paired
experiment and historical observations distinct in the resulting report.
