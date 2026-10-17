# Lean-backed browser and Wasm performance

Use for browser widgets, retained previews and VIR/FIR comparisons, not ordinary
Lean elaboration or native executables. Reuse the project's browser acceptance,
replay and profile tools; this reference adds no harness. Apply
[benchmark-design.md](benchmark-design.md) for raw runs, order balance and
diagnostics separation. The guidance below draws on the VIR/FIR widget campaign;
its results and project-specific probes are not portable backend conclusions.

## Name the observed boundary

A checked browser decoder and renderer may cross these boundaries:

```text
JSON text → JavaScript parse → native JS graph checking/conversion
  → Lean.Json → FromJson typed value → identity/key preparation
  → VDOM / React element construction → React reconciliation and commit
  → browser layout / paint
```

This is a source-inspection checklist, not a prescribed serial implementation.
The plain Lean parser takes a different decode path; a checked native JSON path
still reconstructing `Lean.Json` and calling `FromJson` is not a JS replacement
for the typed decoder. Identity work can precede or occur inside rendering.
Bracket actual callers rather than assigning phases from function names.

Label replay exclusions: RPC/LSP, server encoding, transport, package download,
Wasm compilation/instantiation, initial mount and passive effects. Measure those
separately when they belong to the requested end-to-end latency. A retained
update is not a cold start. A content callback excludes downstream work unless
the observed call path proves otherwise.

A DOM predicate, mutation observer or timestamp named `committedAt` establishes
only its actual observation point. It is neither an isolated VDOM timer nor
proof of completed paint. React commit and browser paint are distinct stages;
use suitable browser trace events for layout/paint claims, not a CPU stack named
`commitRoot`. See React's [render and commit model](https://react.dev/learn/render-and-commit).
Do not add independently computed phase medians into a supposed total median.

## Freeze comparison identity

Record the authoritative source/package snapshot, including relevant dirty and
dependency sources, resolved entry/factory, Wasm and JS/adapter hashes, renderer,
codec, options, input bytes/hash, and host providers/extern mappings. Also retain
browser/version/flags, React production or diagnostic mode, viewport, warmup,
run order and session-age policy (mounts, prior updates, retained runtime/DOM).
Keep these fixed except for the declared experimental axis; list unavoidable
differences and narrow the claim. Do not silently regenerate frozen inputs from
a mutable checkout or substitute an older producer package.

Separate codec screening, factory parity, adapter changes and backend comparison.
For VIR, inspect interpreter dispatch/evaluation, symbol/name lookup, allocation
and host calls. For FIR, inspect compiled Wasm and the typed JS adapter, including
conversion and callbacks. Neither backend removes all boundary work by definition.
Qualify packages in the actual consumer; producer checks or SSR alone do not
establish browser equivalence. Outside timing, check relevant DOM/text semantics,
retained controls/nodes, callbacks, error recovery and disposal. Do not normalize
away the behavior under test.

## Sampled attribution and clocks

- Keep uninstrumented timings separate from CDP sampling, React profiling,
  identity probes and heap diagnostics. Record the selected sampling interval
  and target/thread coverage; main-thread sampling is not whole-browser work.
- Preserve the raw profile, phase markers and summarizer identity. CDP profile
  timestamps and sample deltas use microseconds; do not equate their origin with
  page `performance.now()` or a Node clock. See the
  [CDP Profiler contract](https://chromedevtools.github.io/devtools-protocol/1-3/Profiler/).
- Calibrate clocks explicitly. One project approach brackets a page timestamp
  with protocol timestamps, retaining the offset estimate, uncertainty and all
  trials. Verify the protocol clock matches the profile domain. Choose a
  rejection threshold appropriate to phase length and the claim; do not weaken
  it after a failed capture. Recheck drift for long captures where relevant.
- Reconstruct sample times from recorded deltas, not the requested interval.
  State the interval-weighting and boundary-clipping convention; a sampled
  stack does not establish continuous execution throughout that interval.
  Preserve warmup/measured membership and uncertain boundary attribution.
- Make self-time categories mutually exclusive, with explicit unknown, idle
  and GC handling and a stated denominator. Inclusive host-boundary time already
  includes descendant samples: never add it to self buckets or sum overlapping
  inclusive callers. Caller groups are not chronological phases. A builtin
  called `encode` or `decode` needs caller/source evidence before being labeled
  document serialization. Sample shares do not establish end-to-end savings.

## Match symbols to executable artifacts

Resolve frames per Wasm module, not by function index alone. When borrowing names
from a debug/unstripped artifact, verify its correspondence to the captured
release module. A strong project check compares all non-custom sections, not
just code bodies: imports, types, tables and data matter too. Retain both full
hashes and the comparison method. Equality supports symbol reuse; it does not
make diagnostic browser execution a release timing. If sections differ, obtain
matching symbols or report unresolved frames rather than guessing.

Hash matching JS bundles/source maps and Wasm name/DWARF artifacts; record
resolution coverage. Shared JS↔Wasm trampolines are not proof of module-body
ownership. Stripped FIR frames may support a Wasm bucket without supporting an
internal-function claim. Keep source-level attribution distinct from optimized
instruction costs. See Chrome's [Wasm debugging guidance](https://developer.chrome.com/blog/wasm-debugging-2020/).

## Retention, memory growth and teardown

Follow ownership across Lean objects, JS handles, callback registries, React
roots and host resources. A retained session may intentionally keep resources;
record that policy and update count before calling growth a leak or comparing
session ages. Reverse/reset age cohorts when investigating retention separately
from ordinary timing. Check cleanup after failed creation, replacement, unmount
and disposal, including rejection of stale callbacks. JS heap, Wasm capacity
and live owned objects are different quantities; delayed GC or retained linear
memory capacity alone is not proof of a leak.

Audit cached `DataView`/typed-array views around calls that can grow memory,
including reentrant callbacks. For fixed-length, non-shared Wasm buffers, growth
can detach the old buffer even when growing by zero; byte length alone is not a
safe cache key. Reacquire `memory.buffer` and refresh views when its identity
changes. Shared memory and resizable-buffer modes have different behavior:
check the deployed API and accessible range rather than assuming detachment.
Keep scalar/object caches distinct from buffer-view caching; stable buffer
identity does not make mutable contents constant. See the
[WebAssembly JS memory contract](https://www.w3.org/TR/wasm-js-api-2/#memories).

Keep version-specific classifiers, clock probes and browser adapters in the
project. Reports should link raw profiles and calibration/symbol evidence using
[profile-review.md](profile-review.md), with uninstrumented acceptance results
and attribution captures clearly separated.

`lake samply` profiles a native Lake executable target. It does not replace CDP
sampling, browser performance traces or clock calibration for Wasm running in a
browser, even when the Wasm was produced from the same Lean source.
