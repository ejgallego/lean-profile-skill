# Generated C And Ownership

Use this reference when a Lean profile points at allocation, reference counting,
persistent array copies, or suspected missed in-place updates.

## Contents

- Rule
- Upstream Lean Diagnostics
- Locate Generated C
- Runtime Symbols To Track
- Inspection Pattern
- Lean Optimization Heuristics
- Acceptance Evidence

## Rule

Lean source code does not prove runtime ownership behavior. Compiler
optimization can remove, reorder, or hide source-level uniqueness probes. Treat
source diagnostics as hints; validate ownership claims with generated C,
runtime symbols, and sampled profiles. Use counters only as later aggregate
acceptance evidence.

## Upstream Lean Diagnostics

Lean's reference-counting runtime can reuse memory and update arrays or strings
in place when a value is uniquely referenced. When the value is shared, primitive
updates may copy instead.

Use the documented Lean-native diagnostics before dropping to generated C:

- `dbgTraceIfShared "label" value` reports when `value` is shared, but run it in
  code that is explicitly compiled and executed; `#eval` can be misleading for
  this purpose.
- `set_option trace.compiler.ir.result true` prints compiler IR where
  allocation, reference counting, `isShared`, constructor field projection, and
  `set x[n]` mutations are explicit.

Treat these as diagnosis surfaces, not acceptance evidence by themselves. For
ml-lab-style runtime work, require agreement between IR/source diagnostics,
generated C or runtime symbols, sampled profiles, and representative
diagnostics-off results.

## Locate Generated C

Lake normally writes generated intermediate artifacts, primarily C code, under
`.lake/build/ir`. Paths vary by Lean and Lake version, so search the build tree:

```bash
rg --files .lake/build | rg '\.c$'
rg -n 'lean_copy_expand_array(_nonlinear)?|lean_array_set|lean_array_fset|lean_inc|lean_dec' \
  .lake/build
```

If the function name is mangled, search for the Lean definition suffix, nearby
module name fragments, or runtime calls visible in the profile.

## Runtime Symbols To Track

Prefer these sample-visible runtime symbols:

- `lean_copy_expand_array_nonlinear`: an explicit profiling marker for an array
  copy caused by non-exclusive ownership;
- `lean_copy_expand_array`: array copy or capacity expansion;
- `lean_array_push`: array growth or builder pressure;
- `lean_dec_ref_cold`: object-release/reference-count pressure;
- `lean_alloc_ctor`: constructor allocation;
- allocator symbols such as `mi_malloc_small` and `mi_free`: allocation volume.

Also grep generated C/IR for `lean_array_set`, `lean_array_fset`, `lean_inc`,
`lean_inc_ref`, `lean_dec`, `lean_is_exclusive`, and `lean_ctor_release`. These
are often inline operations and may not survive as standalone optimized native
symbols. Do not infer that one marker is always bad. Explain it through the
caller and the data structure being updated.

## Inspection Pattern

1. Find the generated function for the suspected Lean helper.
2. Draw the live ownership graph from the representative caller to the
   mutation. Include old state, projected fields, result constructors,
   `Option`/error fallbacks, callbacks, closures, and captured environments.
3. Count runtime calls in the function before and after the candidate change.
4. Check whether large state values are retained while a nested field mutates.
5. Confirm the caller still appears or disappears in `perf report` or a
   flamegraph.
6. Validate a representative workload through the normal harness, not a tiny
   counter probe.

Use this grep-friendly ownership checklist in notes:

- owned token entering the call;
- every alias or retained parent;
- mutation point and expected `lean_is_exclusive` result;
- success, failure, and exception/error return owners;
- callback and closure captures;
- generated C/IR evidence for each live edge;
- post-change profile evidence.

If the repository has a triage script, use it to package binary symbol quality,
sampled caller summaries, generated-C shape, and the acceptance readout in one
report. Keep that report separate from diagnostics-off headline timing.

Useful shell shapes:

```bash
rg -n 'MyModule.*myHelper|myHelper' .lake/build
rg -n 'lean_copy_expand_array(_nonlinear)?|lean_array_set|lean_array_fset|lean_inc|lean_dec' \
  .lake/build/path/to/generated.c
perf report --stdio --no-children -i path/to/perf.data --percent-limit 0.0 | \
  rg 'lean_copy_expand_array(_nonlinear)?|lean_dec_ref_cold|myHelper'
```

## Lean Optimization Heuristics

Prefer changes that consume and rebuild state narrowly:

- destructure a large state before calling the mutating helper if that avoids
  retaining the whole old state;
- push mutation behind a small helper that receives only the field it needs;
- avoid generic normalized views before mutating a concrete representation;
- keep debug strings, tracing state, and diagnostic summaries out of the hot
  path unless diagnostics are enabled;
- replace old-state fallbacks with explicit result variants carrying the
  current state when that removes a real retained owner;
- eliminate callback/closure captures that keep the old state live across a
  successful mutation;
- verify in generated C that a nicer source shape did not produce larger or
  slower code.

Be skeptical of:

- source-only ownership assertions;
- changes that improve instructions but inflate cycles through code size or
  branch behavior;
- data-structure sharding that masks copying but no longer models the intended
  semantics;
- tiny fast paths that recognize one benchmark rather than improving the normal
  runtime operation.

## Acceptance Evidence

For ownership-sensitive optimizations, require all of:

- sampled profile identifies the runtime caller or allocation class;
- generated C explains why the candidate should help;
- same-machine baseline/candidate harness results improve or remain acceptable
  on a representative workload;
- focused probe validates the mechanism only after representative evidence
  points at that mechanism;
- correctness tests still cover the changed path.
