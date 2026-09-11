# Verso: from authored Lean to rendered output

Use this reference together with [build-and-elaboration.md](build-and-elaboration.md)
for Verso build performance. Verso has two useful logical stages: building the
authored document as Lean code, then executing a generator to produce output.
These are attribution boundaries, not necessarily two processes or two commands.
A project's wrapper may add extraction, verification, asset processing and
publication. Inspect the pinned implementation and the normal public command.

## Map both stages before profiling

```text
representative edit
  → public orchestration / Lake setup and planning
  → Stage 1: authored Lean document
      imports and initialization
      document directives, embedded Lean checking, highlighting
      deferred block finalization and document declarations
      Lean artifacts + compiler transformations
      native object compilation and linking, where the chosen path needs them
  → Stage 2: generator execution
      startup / environment import / initialization
      materialize document values, including decoding embedded data
      traversal / extension processing / reference resolution
      HTML and auxiliary output construction
      writes
  → project-specific hooks, verification and publication
  → public command exit
```

This is a checklist of possible boundaries, not a prescribed serial schedule.
Jobs can overlap, hooks can run before publication, and some operations occur
inside initialization or argument evaluation. Record first usable view, complete
HTML publication and command exit separately if they differ. Browser reload,
asset fetching and paint require separate observations.

Identify and record:

- Authoring module(s), document root/genre, generator entry and public command.
- Generator execution mode: native binary, `lake exe`, `lean --run`, or another
  wrapper. Include Lake setup, rebuild and relink work in edit-to-output time.
- Root and dependency manifests, Verso and SubVerso pins, Lean module-system
  status, library-specific `precompileModules`, native artifacts actually loaded.
- Output modes, volumes, variants, canonical publication paths and extra hooks.
- Embedded files (`include_str` and similar), their Lake `needs` or equivalent
  dependencies, plus runtime-read assets with their own refresh contract.
- Processes actually launched by directives, highlighters or render hooks:
  Node, KaTeX, Graphviz, TeX or others only where present. Some work can instead
  happen in the browser; do not attribute browser layout to generator wall time.

Do not infer Mathlib loading, Blueprint traversal, public-xref emission, large
terms or external-tool dominance from the use of Verso. Ordinary Verso manuals,
textbooks and Blueprint projects can have different import closures and costs.
Only use Blueprint-specific workflows for a project that actually uses them.

For prose edits, alternating two same-length visible values can keep source
invalidation comparable. Record the source hash and verify the expected value
in finished HTML outside the timing interval. Compare semantic outputs relevant
to the change, including warning hovers, CSS order and extracted code where
present. Do not normalize away the behavior being tested. Render complete sites
into fresh numbered output directories while retaining the incremental build
artifacts specified by the cache policy.

## Stage 1: document elaboration is real Lean work

A prose edit can rebuild a chapter's Lean artifact, aggregating document roots,
executable entry modules, native objects and links. Record the actual affected
jobs and critical dependency chain; a direct already-built generator omits this
cost. A fast native rendering microbenchmark therefore need not imply a fast
author feedback loop.

Embedded Lean examples can entail command/tactic checking, environment and info
collection, SubVerso semantic highlighting, and packing data for later rendering.
Locate each operation in the pinned caller before measuring it. Generic syntax
coloring, semantic Lean highlighting, hover payloads and Lean correctness checking
are distinct features; a preview-mode experiment must state which it retains.

Incremental `#doc` parsing can expose block commands to the editor. This does
not by itself provide block-level reuse in a fresh batch invocation. Measure
editor re-elaboration separately if it is the author's actual workflow.

For an expensive final block, inspect these source-level boundaries (names are
search anchors, not a stable instrumentation API):

| Boundary | What to distinguish |
| --- | --- |
| `runVersoBlock` / `partCommand` | Processing the current block, directives and embedded Lean |
| `addLastBlockCmd` / `finishDoc` | Current block plus completion of the document |
| `toVersoDoc` and deferred elaboration | Materializing syntax/terms for previously deferred blocks |
| Final `Command.elabCommand` of the public definition | Defining the final document constant |
| Lean compiler/artifact phases | Transformations, C emission, serialization; separate from later C-object jobs |

A finalization scope can include deferred blocks as well as the final public
definition. Measure these children before attributing the enclosing cost to
constant construction. Use nested monotonic markers to resolve the actual scope;
never sum inclusive parent and child times or mistake `interpretation` for pure
bytecode overhead.

Precompiling SubVerso or metaprogramming libraries can improve work executed
during elaboration. Check total module/public wall time, clean-build cost and
initializer side effects; profiler bucket changes alone do not prove savings.
Loading unrelated linter initializers can change warning and hover output.

## Stage 2: loading, materialization and rendering

Importing an environment or starting a process is not the same boundary as
materializing the document value. An expression supplying `%doc` or another
root value can be evaluated before entry to `manualMain` or a project wrapper.
A marker placed only inside the renderer may miss this cost. Bracket the caller,
root evaluation and renderer entry, or use a process timeline to locate the gap.

Separate document materialization from traversal, extension/reference work,
HTML construction, auxiliary data, writes and shutdown. Follow the pinned
implementation's passes rather than assuming a fixed number of traversals.
Sample an already-built native generator only once its public-wall contribution
justifies native attribution; cover its child and worker threads.

Inspect existing encodings before proposing another representation. Search
anchors include `hlToExport` and `hlFromExport!` in
`Verso/Code/Highlighted.lean`; inspect their implementations at the current pin
to determine which data is already serialized and when decoding happens. Moving
surrounding constructor trees into serialized data may lower elaboration while
increasing runtime reconstruction. Do not treat an internal highlighted-data
format as a stable external serialization API.

For externalized chapter data, model the extra exporter/materialization job and
its artifact explicitly. This is an experimental architecture, not a standard
Verso build stage. Include source/import/exporter invalidation, missing/corrupt
artifacts and failed-build behavior in the public-path validation. A stable
native binary only demonstrates avoided native rebuilds for the tested edit
scope; shared-import edits may still recompile other components.

## Project wrappers can add another build

Some generators extract standalone Lean projects and run Lake to check them
before publishing HTML at its canonical location. That generated-project build
is not a second elaboration of the Verso source in the root workspace. It has its own
sources, manifest, artifact cache and dependency graph. Not every Verso project
extracts code, verifies it, or uses this publication order.

When such a step exists:

- Record root and generated-project jobs separately, along with the enclosing
  public command. Native rendering may end before the requested endpoint.
- Check whether generated headers or timestamps invalidate otherwise unchanged
  Lean files. Retaining provenance outside dependency-bearing Lean can remove
  unnecessary nested builds; verify output/trace behavior across clock changes.
- Treat reuse of a valid generated dependency manifest separately from retaining
  a live Lake workspace. The latter needs a genuine invalidation protocol.
- Keep generated-code checks in acceptance timings if the public command normally
  performs them. Skipping them is a workflow change to label and evaluate.

Multiple volumes/variants can repeat startup, materialization and checks. If
profiling identifies this repetition, test batching at the public boundary and
preserve each variant's outputs and validation. Inspect mutable global variant
selectors before parallelizing rendering. Shared Make prerequisites can prevent
duplicate writers; concurrent generator instances must have isolated outputs.

## Reusable instrumentation contract

Keep Verso-version-specific marker patches and project edit/output adapters in
the campaign. Reuse the generic sample/identity/review formats instead of baking
a particular chapter, genre or wrapper into shared scripts.

For each marker retain run/configuration identity, phase name, process/thread,
monotonic timestamp and clock origin, plus begin/end or duration semantics.
For job traces retain artifact/module identity and dependency edges. Align child
clocks explicitly before drawing one timeline; otherwise display separate lanes
with stated origins. Keep scope chronology separate from aggregated flamegraphs.

The report should connect three views without merging their timing envelopes:

1. Public edit-to-finished-output A/B distributions and output validation.
2. An observed build/process timeline showing affected jobs, overlap, generator
   phases and the publication endpoint, with its own capture identity.
3. An affected-module Lean profile, with finer Verso markers where needed.

Keep raw captures and transformation provenance; instrumented
profiles explain included uninstrumented public measurements rather than replace
them. No-change and clean-build costs remain regression dimensions even when
edit-to-view is the current priority.

Use [profile-review.md](profile-review.md) for the shared report builder and
trace-quality checks. Version-specific instrumentation stays in the project.
