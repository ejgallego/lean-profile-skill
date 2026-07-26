# ml-lab Case Study

Read this only for ml-lab work or for analogous Lean interpreters where the
goal is faithful execution of an external runtime.

## Contents

- Operating Principle
- Main Commands
- Workload Interpretation
- Lessons To Preserve
- Attribution Rules
- Landing Bar

## Operating Principle

Optimize the normal faithful linked-bytecode path. Extracted hotspots and
focused fixtures are diagnostic tools, not alternative semantics.

For ml-lab, prefer linked `.byte` execution over `.cmo` execution. Keep
compatibility claims versioned and backed by upstream source references.

## Main Commands

Build the profiling target:

```bash
./scripts/profile-workload.sh build
```

Run the standard diagnostics-off comparison:

```bash
./scripts/profile-workload.sh compare_diagnostics_off
```

For landing-quality evidence, use order-balanced passes and validate the
captured identities:

```bash
./scripts/profile-workload.sh compare_diagnostics_off --compare-passes 2 \
  --out-dir _build/profile-workload-compare/candidate
python3 scripts/perf-comparison.py validate \
  _build/profile-workload-compare/candidate/comparison.json --strict
```

Rank benchmark reports:

```bash
python3 scripts/bench-harness.py validate --strict
lake exe ml-lab-bench --group faithful-full-startup --group faithful-byte \
  --repeat 3 --warmup 1 --ocaml-baseline \
  --json _build/bench-current.json
python3 scripts/select-next-perf-target.py _build/bench-current.json
```

Summarize an acceptance comparison:

```bash
python3 scripts/perf-acceptance-summary.py \
  _build/profile-workload-compare/candidate
```

Package ownership/runtime evidence:

```bash
python3 scripts/profile-ownership-triage.py \
  path/to/perf.data \
  --baseline-bin path/to/baseline/run \
  --symbol stepRawDecoded \
  --output _build/profile-ownership-triage/triage.md
```

Inspect current performance history:

```bash
python3 scripts/perf-history-report.py --smoke
```

Use `scripts/profile-workload.sh` modes such as `fib`, `array_set_bump`,
`bytes_set_bump`, `offsetref_bump`, `unicode_table_fill`, `rocqworker`,
`rocqworker_parent`, `rocq_coqtop_check_prop`,
`rocq_coqtop_check_prop_parent`, `rocq_compile_simple`, and
`rocq_compile_simple_parent` according to the target surface.

## Workload Interpretation

- Rocq/coqtop workloads are representative target selectors.
- Focused mutation fixtures validate mechanisms after a real Rocq or corpus
  profile points at array, bytes, block, weak, or heap materialization costs.
- `fib` is a guardrail for interpreter hot-loop work, not proof that a change
  improves realistic runtime behavior.
- Expected fuel exhaustion at the same PC is a valid bounded profiling cutoff,
  not automatically a failure.

## Lessons To Preserve

Durable wins came from:

- compact bytecode metadata for ordinary execution;
- lazy host Dynlink section loading;
- cached metadata helper setup;
- direct heap-entry consumption and specialized mutation paths;
- marshal/local-heap materialization improvements;
- careful generated-C ownership inspection followed by representative
  diagnostics-off acceptance runs.

Strong anti-patterns:

- counter-first investigations for Lean target selection;
- flat heap array replacement and heap pre-sizing without faithful runtime
  justification;
- narrow helper factoring that looks cleaner but regresses generated code;
- zero-length byte-slice skips that do not move real workloads;
- byte payload side stores, heap chunking, page tables, or sharding as faithful
  fixes when they split the modeled heap object away from upstream semantics;
- benchmark-specific mini-interpreters, bytecode-pattern recognizers, or
  fixture-specific hot paths.

## Attribution Rules

Use sampled profiles first for target selection. Treat helper timers, runtime
counters, and linearity/sharedness summaries as diagnostics after native
profiling identifies the cost class. Do not add counters to discover Lean
hotspots; that strategy has repeatedly produced noisy symptoms rather than
actionable ownership/compiler evidence.

Use `select-next-perf-target.py` on a fresh current-head report before choosing
a target from older perf-history artifacts. In the 2026-07-08 usability test,
the stale history artifact pointed at `dynlink_private_test`, while the fresh
current report ranked the same startup/dynlink family but put
`dynlink_initializers_test10` and packed-module Dynlink rows first. Preserve the
lesson, not the exact row: refresh before optimizing.

For ownership work:

- inspect generated C for the relevant helper;
- check sampled callers of `lean_copy_expand_array_nonlinear`,
  `lean_copy_expand_array`, and `lean_dec_ref_cold`; treat inline operations
  such as `lean_array_set` as generated-C/IR markers;
- keep the acceptance run diagnostics-off;
- only add `:::ownership-audit "short-id"` comments as structured notes, not
  proofs.

## Landing Bar

Before landing an ml-lab performance change:

- identify the measured hotspot and representative workload;
- explain the corresponding OCaml runtime surface or why no upstream analogue
  is needed;
- show same-machine before/after evidence on the representative workload;
- use focused fixtures only as mechanism validation;
- run the relevant correctness tests;
- archive rejected ideas in the profile worktree or a short design note.
- retain the comparison identity metadata and raw AB/BA rows;
- collect a post-change profile and verify that the attributed caller moved;
- include executable/symbol-size deltas when generated code placement changed.
