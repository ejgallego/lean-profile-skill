# Build latency and Lean elaboration

Use this mode for edit-to-output, no-change, clean-build, Lake, or Lean frontend
work. It shares evidence practices with native profiling, but native sampling
is a later tool choice, not the starting assumption. Treat each repository as
a fresh workload; another Verso project's bottlenecks are hypotheses only.

For Verso projects, also read [verso-builds.md](verso-builds.md) for the
document/generator stages, deferred blocks, highlighting and project wrappers.

## Establish the public boundary

Start with the project's documented public command and its real endpoint.
For a site, distinguish first usable output, all HTML published, public command
exit (which may include generated-project verification), and browser paint.
Record only endpoints actually observed. `lake env`, `lake exe`, a direct
binary, and `lean --run` have different setup/build costs; diagnostic timings
at those boundaries cannot replace a public-command comparison.

Before measurement, identify authoring modules, document root, generator entry
point, output location, Lean module-system status, `precompileModules`, embedded
`include_str` inputs and Lake `needs`, and external tools/processes. Record
repository/worktree identities and patches, toolchain, Verso and other dependency
revisions, manifest hash, platform/CPU/core count, and artifact/OS-cache policy.
Keep experiments isolated from the author's checkout.

Choose a representative edit that invalidates the same source on each run.
For document prose, alternating two same-length visible values is useful. Record
the source hash and verify the expected text in finished HTML outside the timed
interval. Check semantic output equivalence,
including warning hovers, CSS order and extracted code when relevant. Do not
normalize away exactly the behavior a candidate changes. No-change samples
must preserve source inputs; control real timestamp boundaries if clocks can
invalidate generated Lean files.

Warm dependencies and the caches enabled in the workload. Do not silently
enable a separate artifact-download cache for the experiment. Unless the user
specifies another protocol, use at least one warmup and seven measured samples
per configuration; nine is a useful default for accepted comparisons. Rotate
candidate/control order, render into fresh numbered outputs, and retain actual
execution order. Record wall/user/system time, peak RSS,
exit status, validation, and affected jobs. Report median, IQR with its chosen
quantile convention, range, paired deltas and exclusions. Apply exclusions to
matched pairs with a recorded reason; do not keep only the favorable member.

Project-clean with dependencies warm, dependency-clean, first bootstrap with
network acquisition, and OS-cold are distinct workloads. Do not clear shared
caches to manufacture cold runs; use isolated caches/artifact directories when
needed and describe the achievable boundary.

## Attribute without conflating phases

1. Record exactly which Lake jobs rebuild and their durations; construct the
   dependency critical path. Parallel job CPU/durations are not serial wall time.
2. Locate the generator child and separate Lake setup/planning/build work from
   startup/imports, materialization, traversal, rendering, writes and shutdown.
3. Profile affected Lean modules with the toolchain's supported `--profile`,
   `profiler` options or `trace.profiler`. Inspect imports, initialization,
   elaboration, interpretation, compiler transformations, linters and tactics.
   Read toolchain help/local code for exact flags instead of assuming versions.
4. Add coarse monotonic markers around identified phases. Preserve a common
   clock origin and event scope. Attribute expensive enclosing elaborators with
   finer markers only where useful; a final document command may execute many
   deferred blocks before constructing its last public definition.
5. Inspect subprocess creation when external helpers could account for the cost.
   Use native sampling only once native runtime is a material part of the public
   wall time. Then follow the native workflow in SKILL.md.

`interpretation` does not mean avoidable VM overhead: it can include execution
of native callees. Precompilation can move work between profiler categories.
Compare total/public costs and finer source scopes before claiming a win.

A public invocation-to-olean interval includes orchestration, imports, compiler
work and serialization; do not label it pure elaboration. Parent scopes include
children; workers and build jobs overlap. Separately summarized interval medians
need not sum to median wall time. Label sums from separate diagnostic runs
approximate, and keep instrumented evidence separate from accepted wall samples.

## Test one mechanism at a time

Use the established command, edit and output gate for candidate/control pairs.
Track source changes and exact dependencies through a commit tree. Sibling
branch improvements are not additive until the combined configuration is tested.

Workload-dependent lessons worth checking, not assuming:

- Precompilation may improve warm generation while increasing clean-build cost.
  Native initialization may also activate unrelated linters and change output.
- Moving generated timestamps out of dependency-bearing source removes unwanted
  invalidation, rather than making elaboration itself faster.
- Manifest reuse needs a validity contract; a retained Lake workspace additionally
  needs real source/artifact invalidation. They are different mechanisms.
- Serialized data can reduce constructor elaboration but move work to runtime
  reconstruction. Externalized data can avoid native recompilation but requires
  explicit Lake dependencies, refresh rules and missing/corrupt-data checks.
- Before replacing a representation, inspect the concrete caller and existing
  serialization. A large final command does not prove its final constant is large.
- Development modes that omit highlighting are feature tradeoffs. Distinguish
  them from normal-output improvements even when Lean checking remains enabled.

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

Keep project-specific edits, instrumentation and invalidation in local adapters
rather than hard-coding a textbook or Blueprint workload into the shared skill.

For reusable report generation and trace-quality conventions, read
[profile-review.md](profile-review.md). Keep baseline, diagnostics, each paired
experiment and historical observations distinct in the resulting report.
