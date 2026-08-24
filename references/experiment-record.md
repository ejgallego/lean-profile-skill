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
- `baseline` and `candidate`: commit plus binary hash; for dirty revisions,
  tracked-diff hash plus hashes of task-relevant untracked source files
- `inputs`: input/bytecode/corpus hashes and exact argument arrays
- `measurement`: host, toolchain, build, events, warmups, repetitions, order
- `endpoint`: expected and observed status/terminal boundary
- `attribution`: pre-change sampled hotspot and caller
- `mechanism`: upstream/runtime surface and generated C/IR explanation
- `results`: raw artifact link, pass/sequence rows, paired deltas, and aggregate
  summaries
- `post_profile`: whether the predicted hotspot movement occurred
- `correctness`: commands and outcomes
- `decision`: one-sentence reason
- `remaining_hotspot`: next measured target, if known

## Compact JSONL Example

Keep one logical record per line when maintaining a ledger. This formatted
example is the same object written compactly in JSONL:

```json
{
  "id": "array-update-01",
  "status": "rejected",
  "hypothesis": "Remove a nonlinear array copy from the sampled caller.",
  "representative_workload": {"argv": ["./run", "input.bin"]},
  "focused_workload": null,
  "baseline": {"commit": "abc123", "binary_sha256": "sha256:baseline"},
  "candidate": {"commit": "def456", "binary_sha256": "sha256:candidate"},
  "inputs": [{"path": "input.bin", "sha256": "sha256:input"}],
  "measurement": {
    "host": "host-id",
    "toolchain": "lean-version",
    "build": "release",
    "events": [],
    "warmups": 1,
    "repetitions": 10,
    "order": "AB/BA"
  },
  "endpoint": {"expected": "exit 0", "observed": "exit 0"},
  "attribution": "lean_copy_expand_array_nonlinear in updateState",
  "mechanism": "The candidate retained the old state through the result value.",
  "results": {
    "raw": "_profiles/compare-001",
    "runs_jsonl": "_profiles/compare-001/runs.jsonl",
    "paired_deltas_ns": [1200000, -300000, 800000, 1100000],
    "summary": {"candidate_minus_baseline_median_percent": 1.2}
  },
  "post_profile": "The original caller remained.",
  "correctness": [{"command": "lake test", "outcome": "passed"}],
  "decision": "Reject: ownership and representative runtime did not improve.",
  "remaining_hotspot": "updateState caller retention"
}
```

## Decision Rules

- Mark `accepted` only when the representative path, correctness checks, and
  post-change attribution agree.
- Mark `rejected` when the mechanism is disproved, representative performance
  regresses, fidelity is weakened, or generated code moves contrary to the
  hypothesis.
- Mark `inconclusive` when identity drift, endpoint mismatch, broken call
  chains, noise, run-order effects, or paired-run variation prevent a claim.
- Preserve rejected records and patches so the idea is not rediscovered as
  untried work.

## Evidence Labels

Label each claim as:

- deterministic: hashes, exact endpoint, generated C/IR, native code size;
- noisy: elapsed time, hardware counters, sampled-profile percentages;
- semantic: tests, upstream runtime references, representation invariants.

State disagreements explicitly. For example, fewer instructions with noisier
elapsed time can still support a mechanism, but it is not an elapsed-time win.
