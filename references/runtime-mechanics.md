# Lean Runtime Mechanics for Profiling

Use this reference when a native profile implicates representation, boxing,
atomic reference counting, tasks, synchronization, or channels. It is an
interpretation guide, not a replacement for sampled attribution or a benchmark.

## Contents

- Validated Toolchain
- Symptom Map
- Object Representation and Boxing
- Reference Counting and Reuse
- Tasks, Async I/O, and Synchronization
- Revalidation Checklist

## Validated Toolchain

The concrete interfaces and examples in this reference were validated on
2026-08-26 against Lean `4.34.0-rc1`, commit
`3447a668783dbce1a8fdb97101dd067687b2b418`, and Lake
`5.0.0-src+3447a66`.

Treat trace names, attributes, module paths, and generated identifiers as
toolchain-specific. The runtime principles are more durable, but still verify
them after changing toolchains. This stamp is not a compatibility promise.

## Symptom Map

| Profile or generated-code signal | Likely mechanism | Next deterministic check |
| --- | --- | --- |
| allocator or `lean_alloc_ctor` samples | boxing, constructor creation, closure creation, or failed reuse | Inspect `lean_alloc_ctor(tag, objectFields, scalarBytes)` and its caller. |
| `lean_copy_expand_array_nonlinear` | an array reached mutation without exclusive ownership | Trace retained parents and aliases through the mutation. |
| `lean_dec_ref_cold` or dense `lean_inc`/`lean_dec` | ownership transfers, aliases, closure captures, or multi-threaded RC | Inspect final IR binders and generated-C ownership across the full call chain. |
| `lean_is_exclusive` followed by allocation | reset/reuse has a shared fallback | Determine which live reference makes the object non-exclusive. |
| boxed wrappers around scalar-heavy code | a polymorphic or object-typed boundary needs boxing | Compare concrete and generic signatures and constructor scalar storage. |
| scheduler, wait, mutex, or syscall-heavy samples | blocking work, contention, oversubscription, or unsuitable channel capacity | Separate runnable CPU work, blocking I/O, waiting, and synchronization phases. |

Use the map to choose an inspection, not to diagnose from one symbol alone.

## Object Representation and Boxing

Every heap object begins with a header containing the reference-count state,
size or deletion-list storage, an object-specific byte, and a tag byte. On the
validated toolchain these fields occupy eight bytes before the object's own
payload.

The important representation distinctions are:

- small enums and small `Nat`/`Int` values can be tagged directly in a pointer;
- constructors store object fields followed by a scalar byte area;
- `Array` stores object pointers, while scalar arrays such as `ByteArray` and
  `FloatArray` store unboxed elements;
- monomorphic scalar parameters and fields such as `UInt64` can remain native C
  scalars;
- a scalar crossing a polymorphic or object-typed boundary may require a boxed
  wrapper or heap object.

In generated C, use the second and third arguments of
`lean_alloc_ctor(tag, numObjs, scalarSize)` to distinguish pointer fields from
unboxed scalar storage. For example, a generic pair instantiated with `UInt64`
can still have two object fields, while a monomorphic structure with two
`UInt64` fields can use zero object fields and sixteen scalar bytes.

Do not flatten structures or replace types merely because this model predicts
an indirection. First confirm allocation or memory traffic in a representative
profile, inspect the concrete generated layout, and include memory footprint and
code-size effects in acceptance evidence.

## Reference Counting and Reuse

For a heap object's reference-count field:

- a positive value is single-threaded;
- `1` is exclusive and eligible for in-place update;
- `0` is persistent and not reference-counted;
- a negative value is multi-threaded and uses atomic reference counting.

An object is reusable only when it is exclusive at the update. Arrays and
strings use this property in their update operations. The compiler may also
emit reset/reuse paths for constructor objects: the exclusive branch releases
replaced fields and mutates the old allocation, while the shared branch
allocates a replacement.

The calling convention also affects RC traffic:

- an owned object argument transfers responsibility for eventually releasing
  the reference to the callee;
- a borrowed `@&` argument leaves that responsibility with the caller;
- scalar or tagged arguments do not participate in object reference counting.

Values shared across tasks or synchronization boundaries may be marked
multi-threaded. This makes their RC operations atomic and prevents exclusive
reuse while they remain in that state. When atomic RC appears in a profile,
find the sharing boundary and lifetime before changing the data structure.

Read [generated-c-ownership.md](generated-c-ownership.md) for the ownership
graph, compiler traces, annotations, and acceptance checks.

## Tasks, Async I/O, and Synchronization

`Task` schedules computations on Lean's worker infrastructure, but a blocking
operation inside a task does not become asynchronous merely because it runs in
a task. Blocking enough workers can delay otherwise runnable work. When the
work is asynchronous I/O, use the public `Std.Async` APIs and their higher-level
combinators where they fit the program.

Current public imports include:

```lean
import Std.Async
import Std.Sync.Channel
import Std.Sync.Mutex
```

Choose synchronization from measured behavior and required semantics:

- `IO.Ref` uses atomic pointer operations and busy-waiting; it can suit short,
  low-contention updates but should not be assumed cheap under contention;
- `Std.Mutex` sleeps while waiting and is usually the clearer starting point
  for guarded shared state; shared/read-write and recursive variants also
  exist;
- `Std.Channel` supports unbuffered, bounded, and unbounded operation. Its
  default capacity is unbounded. A bounded channel provides backpressure, but
  the correct capacity depends on producer/consumer rates, memory limits, and
  latency requirements.

Do not turn these choices into universal rules. Profile queue growth, waiting,
contention, wakeups, and useful worker time on the representative workload.

## Revalidation Checklist

After changing Lean toolchains:

1. Record `lean --version`, `lake --version`, the `lean-toolchain` value, and the
   compiler commit when available.
2. Compile a probe using `trace.Compiler.saveBase`,
   `trace.Compiler.saveImpure`, and `trace.Compiler.result` with
   `pp.funBinderTypes` and `pp.letVarTypes`.
3. Compile probes for `@[inline]`, `@[always_inline]`, `@[macro_inline]`,
   `@[noinline]`, `inline (f x)`, specialization attributes, and an ordinary
   `@&` parameter.
4. Compile the public async and synchronization imports above.
5. Generate C for one generic versus monomorphic scalar structure and one
   record update. Confirm scalar storage, boxed wrappers, exclusive reuse, and
   fallback allocation against the active runtime header.
6. Update this stamp and any changed guidance. Do not add legacy compatibility
   instructions unless the skill explicitly gains a multi-toolchain scope.

These probes validate interfaces and deterministic code shape. They do not
replace a representative native-runtime profile or baseline/candidate run.
