# Import retained command comparisons

Use `scripts/import_comparison.py` for a capture produced by the bundled
`compare_commands.py`. It reads retained evidence; it does not run commands,
recheck binaries against the current checkout, or perform correctness tests.
The output feeds [the report builder](profile-review.md).

`check_outputs.py` is standalone: use it without the importer or report builder when
all you need is a byte-exact check of retained run output. It never runs the compared
commands. Given `--out checks/validation.json`, it writes that validation document and
the sibling evidence file `checks/validation-results.json`; pass the former to the
importer only when building a report.

```bash
python3 "$skill_dir/scripts/check_outputs.py" _out/performance/capture \
  --expected _out/performance/expected-stdout.txt \
  --scope 'stdout equals the output of an independent reimplementation' \
  --out _out/performance/checks/validation.json
python3 "$skill_dir/scripts/import_comparison.py" \
  _out/performance/capture --out _out/performance/import-01 \
  --boundary 'child invocation through exit, including harness bookkeeping' \
  --cohort 'representative workload; same warm-cache policy' \
  --validation _out/performance/checks/validation.json
python3 "$skill_dir/scripts/build_review.py" \
  _out/performance/import-01/report.json --out _out/performance/review-01
```

Curate `report.json` before building a report anyone else will read. The importer
writes factual boilerplate, not findings. Copy it to `review-input.json` beside
`observations.jsonl` so that relative paths still resolve, then replace `title`,
`summary`, each `note` and `decision`; the importer lists both configurations under
`baselines` so that partial captures stay visible, so drop the `candidate` entry when
the comparison already shows it. Add `attribution` for any cause you can support,
and set `decision_status` only if the decision is yours to make.

The importer does not recheck binaries against the current checkout. When source
trees are retained, rebuilding each in a scratch copy and comparing the result with the
manifest's `executable_sha256` is cheap and is the strongest evidence that the report's
diff describes what was measured.

The commands assume the capture sits in `_out/performance/`; to share the result,
first copy it into the [bundle directory](profile-review.md#sharing-a-report). Replace
the boundary and cohort with the actual conditions. The capture's elapsed
clock includes harness work and process startup; timeout readings include
termination handling. Optional perf-stat captures include instrumentation
overhead and are labeled diagnostic evidence. Do not relabel these readings as
pure in-process runtime or mix them with an uninstrumented public baseline.

Both output directories must be fresh. The default tools require Python 3.10+
and only its standard library. The importer validates inputs before creating
output, though a later disk failure can leave a partial directory.

## Capture and inclusion

The importer reads `manifest.json` (`lean-profile-compare-alpha`) and
`runs.jsonl`, with optional `identity-check.json`. It checks run sequence IDs,
exact argv against the manifest, phase, block/pass, slot, expected exit status
and outcome fields. It preserves raw snapshots, original order, nested argv,
integer `elapsed_ns`, and the configured timeout separately.

Normalized observations record their original `capture_directory`; original
stdout/stderr/perf paths are relative to that directory, not the import directory.
Source snapshots and validation evidence appear as report links. Captures and
external evidence are not bundled or relocated; retain them at stable paths.

The importer applies the shared
[inclusion contract](review-format.md#observation-contract). In addition, it
requires a retained identity check reporting no drift and no recorded harness
evidence error. Only a passed, hash-bound check below sets `validated=true`.

Missing/failed checks leave the outcome visible with exclusion reasons. Omitting
`--validation` is useful for inventorying captures, but includes no runs in timing
statistics. A successful exit or an identity match is not an output check.
Missing identity evidence also prevents inclusion, even if output checks passed.

Partial fail-fast captures can still render, including a baseline warmup timeout
with no candidate observations. The shared
[timeout and pairing rules](review-format.md#missing-outcomes-timeouts-and-pairing)
apply; the importer never selects surviving pairs or promotes warmups.

The generated comparison has an explanatory decision but no `decision_status`.
An investigator may subsequently classify the optimization; the importer does
not accept or reject it from timing alone.

## Summary conventions

New harness summaries and reports both use **positive savings for a faster
candidate**, negative for a slower one:

- Harness `paired_savings_ns`: baseline elapsed minus candidate elapsed for
  each measured pass, in pass order; `paired_saving_median_ns` is their median.
- Harness `baseline_minus_candidate_median_ns`: difference of group medians,
  not the median of paired savings.
- Shared `median_reduction_pct`: `100 × (1 − candidate_median / control_median)`;
  the harness calls the control `baseline`.
- Report `paired_saving_s`: descriptive statistics of matched savings in seconds.

The importer reads raw `runs.jsonl`, not the harness's `summary.json`, and the
report recomputes statistics over explicitly included observations. Exclusions
can therefore change the results. Older retained captures remain usable through
their raw runs; no old summary-field aliases are emitted or interpreted.

## Explicit output-validation records

The validation document binds the exact captured manifest and JSONL bytes with
SHA-256, then identifies checks by the source run's positive integer `sequence`:

```json
{
  "schema": "lean-profile-command-validation-alpha",
  "manifest_sha256": "replace with SHA-256 of capture/manifest.json",
  "runs_sha256": "replace with SHA-256 of capture/runs.jsonl",
  "checks": [{
    "sequence": 1,
    "result": "passed",
    "scope": "Representative output compared with the trusted expected result",
    "artifacts": [{
      "path": "checks/results.json",
      "sha256": "replace with SHA-256 of checks/results.json",
      "record": "/runs/1/output-check"
    }]
  }]
}
```

Each supplied check requires `result` (`passed` or `failed`), a nonempty `scope`
and at least one evidence artifact. An artifact has `path`, `sha256` and a
nonempty `record` selector or description. Paths are relative to the validation
document or absolute. Unknown/duplicate run IDs, missing or changed artifacts,
and hash mismatches fail before output is created. Checks may cover a subset
of runs; all others remain explicitly unvalidated.

A shared evidence path is hashed and linked once per import; every check retains
its own selector. Each supplied expected hash is still checked, so conflicting
hashes fail. A later invocation rereads evidence rather than reusing old hashes.

Use actual project checks and state what they establish. The importer verifies
the document's binding and artifact bytes, but does not interpret arbitrary
selectors, rerun checks or prove the investigator's assertions. Do not manufacture
a `passed` record just to make timings appear. If evidence is unavailable, omit
the check and retain the resulting limitation.

When the project has no tests, a check written for this comparison is legitimate if
it could have failed. In order of strength: expected output from an independent
reimplementation or trusted reference; then the two configurations agreeing with each
other over more inputs than the benchmark uses. For a path the command line cannot reach,
a small script under `lake env lean --run` can compare the old and new definitions directly. A candidate compared only with its
own retained output establishes nothing. For the second kind, `scripts/compare_outputs.py`
runs both configurations over chosen argument sets without timing them; see
[profiling-loop.md](profiling-loop.md#order-balanced-comparison). The bundled
`scripts/check_outputs.py` covers the common case, comparing every completed run's retained stdout with trusted bytes
and recording mismatches as `failed`. It refuses to replace either output file; a later
I/O failure can leave only the newly created part. `--scope` must say what the match
establishes and what it omits. It handles byte-exact output only; write the validation document
directly for anything that needs normalizing. It reads the retained capture and does
not run commands, so generate the expected bytes separately.

## Provenance and limits

The importer creates `report.json`, normalized `observations.jsonl`, and byte
copies named `source-manifest.json`, `source-runs.jsonl`, plus optional
`source-identity.json` and `source-validation.json`. Parsing, validation binding
and copying use the same input snapshots. Per-run validation metadata retains
the copied validation document's hash/check location and original evidence hashes.

This is a first-party adapter for the bundled two-command harness, not a generic
campaign converter. For other harnesses, prepare the shared CSV/JSONL observation
contract directly, preserving block identity, order, units, outcome and validation
provenance. Do not synthesize missing trials or infer cross-capture pairing.
