# Compiler-wide surveys and semantic triage

Use this reference when a whole Lean library or compiler build is being surveyed
to choose modules and callers for deeper profiling. The survey is target
selection, not a before/after benchmark and not evidence that every flagged cost
is redundant.

## Fix the survey boundary

Before capture, name the exact library targets, module groups, requested
artifacts and build endpoint. State whether the survey measures one parallel
build, serial module replays, or both. A module duration observed inside a
parallel build includes contention and is not an isolated module cost.

Pin the dated toolchain tag, compiler commit, matching sources and bootstrap or
stage used to compile them. When the survey depends on a recently merged fix,
record the fix commit and a successful ancestry check from that commit to the
selected compiler commit. A publication date or version string is not enough:
a nightly published earlier on the merge date may predate the fix.

Hash the executable launcher and the compiler shared libraries actually mapped
by the process. Record their resolved paths, build IDs when available and the
process mappings used to establish which image ran. Identical launcher stubs do
not imply identical compilers. Also retain source, import, build-configuration
and non-source input identities.

## Stage the survey

1. Collect a diagnostics-off whole-build census of wall, CPU, peak memory, job
   timing and dependency information with output checks. Use this plain capture
   for cost and critical-path views.
2. In a separately labeled diagnostic capture, collect module-keyed Lean
   `--profile` phase data and retain it before aggregation. An aggregate category
   without a module key cannot select files, and instrumented phase durations
   are not plain build timings.
3. Construct separate views for absolute compilation work, dependency
   critical-path contribution and unusual phase behavior. Do not add parallel
   module durations and call the sum wall time.
4. If a whole-build native sample could reveal callers spread across many short
   modules, pilot it separately. Verify descendant coverage, overhead, output
   size, sample loss, symbols and unwind quality before choosing the rate. Keep
   this diagnostic capture out of headline timing samples.
5. Replay selected modules in isolation with the exact command and output gate.
   Parallel-build observations motivate the replay; they do not replace it.
6. Use detailed caller profiles to form hypotheses, then reconnect any focused
   experiment to a representative build or module workload.

Retain failed and lossy pilot captures with their rejection reason. Sampling
rates are workload-dependent: a rate accepted for one module or environment is
not a default for a whole build.

## Select modules reproducibly

Write the selection rule before detailed profiling. A useful small set covers
distinct reasons rather than simply taking the longest files:

- high absolute CPU or elapsed work;
- high critical-path contribution;
- an unusual phase mix or repeated semantic caller;
- a category not yet represented;
- an ordinary, reproducibly sampled comparison module.

Set the number or quota for each reason, deterministic tie-breaking and a
fall-through rule when one module qualifies more than once. Keep any
preselected regression or motivating module as a labeled sentinel outside the
discovery ranking. For every eligible and selected module, record the measured
metrics, ranks, selection reason, exclusions, observed sample coverage and exact
replay command. Do not infer corpus-wide savings by extrapolating unprofiled
files or summing overlapping inclusive percentages.

## Follow semantic callers

Treat the following as multi-label triage prompts, not automatic findings or a
ranking score. A helper symbol can be shared by several source callers, and a
generated specialization label may obscure the semantic caller. Inspect full
stacks and source or generated C before assigning ownership.

| Prompt | Stronger evidence | Next check |
| --- | --- | --- |
| Excessive name or environment resolution | Resolution nested inside local or speculative searches, with negative or unused results | Trace the semantic caller and the exact condition under which the global answer matters. |
| Name construction or hashing | Repeated qualification, private-name construction or temporary candidates dominate a modest semantic operation | Inspect constructed names, caller frequency and allocation/cleanup before considering caching or representation changes. |
| Repeated context or expression traversal | The same input is scanned repeatedly during one normal operation | Identify what changes between scans and whether a prior result remains valid. |
| Allocation, reference counting or copying | Temporary structures or persistent copies dominate a concrete caller | Follow ownership through the full call chain and inspect generated C. |
| Expensive unsuccessful search | Instance, unification or fallback candidates consume substantial work before rejection | Find a cheap sound rejection condition and test successful alternatives. |
| Repeated normalization or inference | Repeated normalization, type inference, instantiation or equality appears on equivalent inputs | Check context and metavariable changes, existing caches and invalidation. High proof-work share alone is not a defect. |
| Import, serialization or metadata | Surrounding work dominates a representative small edit or module build | Separate phases and identify which requested artifacts or observations require the work. |
| Synchronization or coordination | Repeated lock or wait callers have corroborating thread, CPU and wall evidence | Identify the dependency and distinguish CPU work from off-CPU waits and normally idle workers. |

Look especially for an expensive result computed before the caller knows that it
is needed: negative lookups, candidate lists consumed only as a Boolean and
repeated fallbacks are useful hypotheses. Establish the semantic condition and
correct precedence before deferring the work. Preserve focused correctness
tests because an upstream successor may intentionally change semantics while
solving the same performance problem.

## Capture fields

Add these fields to the project-local survey manifest or adapter:

- survey schema/version, UTC start, host, CPU/core count, governor or power mode,
  affinity, resource limits and relevant environment variables;
- repository commit and dirty-state identities, exact target/module inventory,
  source/import/non-source input hashes, harness/adapter hashes and
  cache/artifact policy;
- toolchain tag, compiler commit, bootstrap/stage and build flags, plus the
  motivating fix commit and ancestry command/result;
- launcher hash; resolved loaded-library paths, hashes and build IDs; captured
  process mappings and compiler/source provenance;
- exact argv, working directory, concurrency, process/descendant policy,
  module-to-process mapping, monotonic job/module start and end times, exit
  status and output gate;
- diagnostics-off per-module wall/user/system time, peak RSS, requested-artifact
  status, dependency predecessors and critical-path contribution;
- separately labeled, module-keyed Lean `--profile` records, exact profiler
  options and raw phase entries before aggregation; do not treat their
  instrumented durations as diagnostics-off costs;
- profiler/backend version, command, event, requested and observed frequency,
  call-graph mode, target PIDs/TIDs, sample counts, losses, unknown/known-frame
  share, symbol/unwind checks and measured pilot overhead;
- hashes for raw captures, symbol or mapping sidecars and any portable derivative,
  with the exact transformation and fidelity checks. Preserve the raw capture;
- an eligibility and selection table containing all views, ranks, coverage,
  reasons, tie-breaks, exclusions and isolated replay commands;
- explicit labels for measured observations, rejected captures, hypotheses and
  proposed next experiments.

CPU samples, inclusive scope durations, worker overlap, waits and wall latency
answer different questions. Keep them separate. A helper becoming a larger
percentage after a fix does not show that its absolute cost increased, and
waiter frames alone do not establish synchronization as a wall-time regression.
