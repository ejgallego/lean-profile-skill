# Performance Experiment Record

Use this reference to record accepted, rejected, and inconclusive candidates.
Keep the record compact enough to scan as a JSONL ledger or short Markdown
note, while linking large raw artifacts rather than embedding them.

## Required Fields

- `id`: stable short name
- `status`: queued, measuring, accepted, rejected, or inconclusive
- `hypothesis`: predicted caller/runtime-bucket movement
- `representative_workload`: exact user-visible workload
- `focused_workload`: optional mechanism validator
- `baseline` and `candidate`: commit plus binary hash
- `inputs`: input/bytecode/corpus hashes and arguments
- `measurement`: host, toolchain, build, events, warmups, repetitions, order
- `endpoint`: expected and observed status/terminal boundary
- `attribution`: pre-change sampled hotspot and caller
- `mechanism`: upstream/runtime surface and generated C/IR explanation
- `results`: raw artifact link plus aggregate deltas
- `post_profile`: whether the predicted hotspot movement occurred
- `correctness`: commands and outcomes
- `decision`: one-sentence reason
- `remaining_hotspot`: next measured target, if known

## Decision Rules

- Mark `accepted` only when the representative path, correctness checks, and
  post-change attribution agree.
- Mark `rejected` when the mechanism is disproved, representative performance
  regresses, fidelity is weakened, or generated code moves contrary to the
  hypothesis.
- Mark `inconclusive` when noise, identity drift, endpoint mismatch, or broken
  call chains prevent a claim.
- Preserve rejected records and patches so the idea is not rediscovered as
  untried work.

## Evidence Labels

Label each claim as:

- deterministic: hashes, exact endpoint, generated C/IR, native code size;
- noisy: elapsed time, hardware counters, sampled-profile percentages;
- semantic: tests, upstream runtime references, representation invariants.

State disagreements explicitly. For example, fewer instructions with noisier
elapsed time can still support a mechanism, but it is not an elapsed-time win.
