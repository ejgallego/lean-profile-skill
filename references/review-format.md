# Review input format

The `lean-profile-review-alpha` manifest is UTF-8 JSON. Required top-level strings
are `schema`, `title` and `summary`. Strings are plain text, escaped for HTML;
no Markdown interpreter or remote assets are needed for the report itself.
Duplicate JSON keys and nonfinite numbers are rejected. This alpha format has
no compatibility layer for earlier manifests.

`datasets`, `baselines`, `comparisons`, `profiles`, `attribution` and `links`
are optional arrays; `progress` is an optional object. See
`examples/review/report.json` for a complete synthetic example. For retained
`compare_commands.py` output, use [command-import.md](command-import.md).

## Datasets and explicit contrasts

A dataset is one capture with a shared workload, timing boundary and cohort.
Split public-command, nested diagnostic, edit/no-change/clean and instrumented
measurements into separate datasets, even when their configuration names match.

| Dataset field | Meaning |
| --- | --- |
| `id` | Required stable identifier. |
| `title` | Short description of the capture. |
| `configurations` | Nonempty array of unique configuration names. |
| `samples` | CSV or JSONL path, relative to the input manifest or absolute. |
| `format` | Optional `csv` or `jsonl`; otherwise inferred from the file extension. |
| `boundary` | Actual start and stop of the measured interval, including any harness overhead. |
| `cohort` | Workload, cache policy and relevant conditions. |
| `identity` | Commits, toolchains, host and capture identity, or concise text with a linked full identity record. |
| `command` | Exact command(s), displayed in an expandable section. |
| `expected_exit_status` | Integer, default `0`; matching it is necessary but not sufficient for inclusion. |

A baseline requires `title`, `note`, `dataset` and `configuration`.
A comparison requires `title`, `note`, `dataset`, distinct `control` and
`candidate` configurations, and an investigator-written `decision` explanation.
Its optional `decision_status` is `accepted`, `rejected` or `inconclusive`;
absence means unclassified. This status concerns the optimization, not whether
the underlying observations belong in statistics.

Optional comparison `group` is a plain-text experiment heading. Comparisons with
the same group are displayed together, at the group's first position in the
manifest. Use a short workload label for each member's `title`. Group members
must have identical `note`, `decision` and `decision_status`: the renderer shows
that shared explanation once. Distinct decisions should remain separate groups
or ungrouped comparisons.

Grouping changes presentation only. Each member retains its dataset, configuration
names, timing boundary, inclusion decisions, statistics and anchor. No observations
are pooled and no group estimate is calculated. With plots enabled, the first
member's distribution is shown with the group; every other distribution remains
under that workload's expandable evidence. Put the representative workload first.
Missing estimates, censoring and measured exclusions remain visible in the table.

Baselines and comparisons reference a dataset; they cannot override its metadata.
Each dataset is parsed, hashed and copied once, regardless of the number of
references. Three or more configurations get an expandable overview table in
the evidence section. Only requested
contrasts are computed; the builder does not infer an N-way experimental design.

```json
{
  "schema": "lean-profile-review-alpha",
  "title": "Retained experiment",
  "summary": "Explicitly validated observations; see linked correctness records.",
  "datasets": [{
    "id": "capture",
    "title": "Public invocation",
    "configurations": ["control", "candidate"],
    "samples": "observations.jsonl",
    "boundary": "process invocation through exit, including harness bookkeeping",
    "cohort": "same workload and warm-cache policy",
    "identity": "record actual commits, toolchains and host here",
    "command": "record exact control and candidate commands here"
  }],
  "baselines": [{
    "id": "original", "title": "Original cost", "note": "Retained control observations.",
    "dataset": "capture", "configuration": "control"
  }],
  "comparisons": [{
    "id": "trial", "title": "Candidate", "note": "Describe checks and limitations.",
    "dataset": "capture", "control": "control", "candidate": "candidate",
    "decision_status": "rejected", "decision": "Valid measurements, but not worth landing."
  }]
}
```

An optional `id` gives a stable anchor for each baseline, comparison or profile.
Dataset IDs are mandatory. IDs must start with an ASCII letter and contain
only letters, digits, `_` or `-`. They must be globally unique. The UI reserves
`baselines`, `datasets`, `progress`, `attribution`, `measurements`, `evidence`,
`filter`, `decision-filter`, `count`, `toast`, and the `frame-` prefix.
Default baseline/comparison/profile IDs are `base-00`, `cmp-00` or `profile-00`
in array order; use explicit IDs for cross-references.

## Observation contract

CSV and JSONL require `id`, `configuration`, `block`, `exit_status`, `phase`,
`outcome`, `validated`, `included` and `exclude_reason`. Completed outcomes also
require one duration: **either `wall_s` or `elapsed_ns`, not both**. This CSV
example uses seconds:

```csv
id,configuration,block,wall_s,exit_status,phase,outcome,validated,included,exclude_reason
control-1,control,1,0.0045,0,measured,completed,true,true,
candidate-1,candidate,1,0.0041,0,measured,completed,true,true,
```

The same flat observations can be expressed as JSONL, retaining integer clocks
and any extra nested fields:

```jsonl
{"id":"control-1","configuration":"control","block":"1","elapsed_ns":4500000,"exit_status":0,"phase":"measured","outcome":"completed","validated":true,"included":true,"exclude_reason":"","argv":["tool","arg with spaces"]}
{"id":"candidate-1","configuration":"candidate","block":"1","elapsed_ns":4100000,"exit_status":0,"phase":"measured","outcome":"completed","validated":true,"included":true,"exclude_reason":"","argv":["tool-candidate","arg with spaces"]}
```

- `id` is nonblank text, unique within the dataset.
- `configuration` names a declared configuration.
- `block` is nonblank text identifying a matched execution block, not row order.
  Each configuration has at most one observation per phase/block.
- Optional integer `slot` records execution order within a phase/block; it must
  be positive and unique there. File order and nested fields are preserved.
- `phase` is `measured` or `warmup`.
- `outcome` is `completed`, `timeout`, `interrupted` or `error`.
- `exit_status` is an integer or absent value (CSV empty, JSON null).
  Completed outcomes require an integer.
- Provide exactly one duration for a completed outcome: finite nonnegative
  `wall_s`, or nonnegative integer `elapsed_ns`. Other outcomes may omit duration.
  The model preserves the integer clock and derives seconds for statistics;
  display rounding does not rewrite the source.
- Timeouts require a finite positive `timeout_s`: the configured limit, not
  observed elapsed time after termination handling.
- `validated` and `included` are literal `true`/`false` in CSV and booleans in
  JSONL. `validated` records an explicit correctness check, not exit status.
- `included=true` requires a measured, completed, validated observation with
  expected exit status, positive duration and an empty `exclude_reason`.
  A rejected optimization can still have included observations.
- `included=false` retains the outcome. Excluded measured observations require
  a nonblank `exclude_reason`; warmups never enter statistics.
- Optional row `boundary` and `cohort` must agree with the dataset when present.
- Optional resources `user_s`, `system_s`, `peak_rss_kib` must be finite and
  nonnegative. Each reported resource must cover all included observations in
  that configuration, not a smaller subset.

CSV headers must be unique and rows must have the correct field count. Quoted
fields can contain commas, escaped quotes and newlines; malformed quoted fields
are rejected. Empty physical lines between records are skipped. Extra fields
are retained. The obsolete observation field `accepted` is rejected;
use `included`. JSONL is not converted through CSV: typed/nested fields and
integer clock readings survive in the archive and model.
JSONL parsing errors identify the source file and physical line, including blank
lines; syntax errors also report the column.
CSV field-validation errors identify the record's starting physical line;
quoting errors identify the line where the parser detected them. Both formats
report the source file for invalid UTF-8.

The general reader validates structure and consistency, not the truth of
investigator records. Link correctness evidence and explain exclusions. The
command importer additionally requires hash-bound validation records before
marking outcomes output-validated.

### Missing outcomes, timeouts and pairing

Datasets must contain at least one observation, but a declared configuration
can have none (for example, a fail-fast capture stopped before running it).
Warmups and unsuccessful/unvalidated outcomes are visible without supplying
a timing median. Missing statistics are null in the model and shown as dashes.

For an explicit contrast, included block sets must match on both sides. Unequal
sets produce an unavailable estimate with unmatched block IDs in the model;
the builder never silently selects only complete pairs. If excluding unmatched
members is justified, record that decision and the exclusions explicitly.

A measured timeout on either selected configuration suppresses paired and
overall speedup estimates, even if that timeout is marked excluded. Included
completion distributions remain available but are conditional on completion.
A warmup timeout is not a measured timeout or baseline. A timeout in an unrelated
third configuration does not invalidate a fully matched contrast. No timeout is
inserted into a distribution at its configured limit, and the builder does not
perform survival analysis or infer speedup bounds.

Statistics include `n`, median, `q1`, `q3`, IQR and range. Quartiles use linear
interpolation at `(n - 1) × p`; a singleton has IQR zero but cannot characterize
run-to-run variability. Choose trial counts for cost, noise, effect and claim;
there is no universal minimum.

Paired saving is `control - candidate` for each included matching block, with
its own median, IQR and range. Its median may differ from the difference of
group medians. Percent reduction is `100 × (1 - candidate_median / control_median)`;
negative means slower. These descriptive statistics do not establish significance.
Tables and axes choose common s/ms/µs/ns units and significant digits.

## Summary of improvements

`progress` requires a `note`; optional `selected` and `totals` arrays reference
comparison IDs without duplicates within each array. A total must be a directly
measured comparison of original and combined configurations; the investigator
is responsible for that identity. The builder never composes incremental savings.

Optional `historical` entries require `title`, `note`, `from` and `to`.
Each endpoint is either `{"baseline": "id"}` or
`{"comparison": "id", "side": "control"}` (also allowing `candidate`).
Endpoints must name the same command and timing boundary. They remain separately
labeled unpaired, with identities and cohorts, not synthesized pairs or confidence
claims. Missing completions or measured censoring suppress their ratio.

## Attribution and evidence

`attribution` entries require `title` and `text`. Use investigator-written
phase explanations and label approximate sums from separate runs.

`profiles` require `title`, `kind`, `path`, `boundary`, `identity` and `note`.
Supported kinds remain `perfetto`, `viewer` (trusted interactive HTML), `image`
and `raw`. Optional `comparison` references a comparison ID; otherwise the
profile appears with phase attribution. Record instrumentation, clock origin,
units and provenance. A native self profile is not a trustworthy caller tree;
no conversion or new viewer semantics are inferred from an attachment.

`links` require `title` and `path`. Artifact paths must be existing local files.
Relative paths resolve from the input manifest directory and preserve symlink
mount paths for HTTP serving. Profiles and links are hashed but not copied;
serve their common ancestor and keep them stable. Perfetto opens its online UI
and receives the trace locally in the browser on user click, without uploading
or creating a share link.

Each artifact path is hashed once per build, even when used by both profiles and
links. Exact duplicate links (same path and title) are omitted; distinct titles
remain. Hashes are recomputed on subsequent builds, not cached across invocations.

## Generated output and reproducibility

A fresh output directory contains `index.html`, local CSS/JS,
`source-manifest.json`, `dataset-NN.csv` or `dataset-NN.jsonl`, and
`review-data.json`. Dataset snapshots are the exact bytes used for parsing,
statistics and SHA-256 hashing, shared by every referring baseline/contrast.
The manifest preserves its original bytes and original path semantics.
`review-data.json` is a derived model, not a replacement input manifest.

The model retains metadata, source hashes, copied dataset names, included IDs,
block IDs, all outcome records and resources. Contrasts retain matched block IDs,
differences and unavailability reasons. Linked profiles/evidence retain their
paths and build-time hashes but can change later.

With `--plots`, Matplotlib produces `figures/*.svg` and `*.png`; the model
records their hashes and source IDs. Figure bytes depend on library versions,
metadata and fonts; numerical reproducibility comes from snapshots and the model.
No benchmarks or trace conversions run during reporting. Validation precedes
output creation, but a later disk or plotting failure can leave a partial fresh
directory. This is not a portable capture bundler.
