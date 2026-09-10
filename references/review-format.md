# Review input format

The `lean-profile-review-v1` manifest is UTF-8 JSON. Required top-level strings
are `schema`, `title` and `summary`. Strings are plain text, escaped for HTML;
no Markdown interpreter or remote assets are needed for the report itself.
Duplicate JSON keys and nonfinite constants are rejected.

`baselines`, `comparisons`, `profiles`, `attribution` and `links` are optional
arrays. `progress` is an optional object. A comparison-only manifest from the
original v1 format remains valid. See `examples/review/report.json` for a small
complete example; the numbers and trace in that directory are invented.

## Measurements

Each baseline or comparison requires these nonempty strings:

| Field | Meaning |
| --- | --- |
| `title` | Short description of the workload or experiment. |
| `boundary` | Start and stop of the measured interval. |
| `cohort` | Edit/no-change/clean, cache policy and relevant conditions. |
| `identity` | Control/candidate commits, toolchains, host and capture identity, or a concise description with a linked full identity record. |
| `command` | Exact command whose wall time was measured. |
| `note` | Workload details, output validation and limitations. |
| `samples` | Path to the CSV, relative to the original manifest or absolute. |

A baseline additionally requires `configuration`. A comparison requires distinct
`control` and `candidate` configurations plus `decision` (investigator-supplied
acceptance, rejection or uncertainty). One CSV contains exactly the declared
configuration(s) and one workload/boundary. Split edit, no-change, clean and
instrumented measurements into separate entries and files. Link raw logs and
validation records through `links`; the builder cannot verify their conclusions.

An optional `id` gives a stable anchor for each baseline, comparison or profile.
It must start with an ASCII letter and contain only letters, digits, `_` or `-`.
IDs must be globally unique. The UI reserves `baselines`, `progress`,
`attribution`, `measurements`, `evidence`, `filter`, `count`, `toast`, and the
`frame-` prefix. Without explicit IDs, entries get `base-00`, `cmp-00` or
`profile-00` in array order; use explicit IDs for cross-references.

### CSV contract

```csv
configuration,pair,wall_s,exit_status,phase,validated,accepted,exclude_reason
control,1,15.0,0,measured,true,true,
candidate,1,13.0,0,measured,true,true,
```

The eight columns above are required. Headers must be unique and rows must have
the correct field count. Additional columns are retained in the copied CSV.
Optional recognized resource columns are `user_s`, `system_s`, `peak_rss_kib`;
if present they must contain finite nonnegative numbers for every included row.
Do not convert CPU seconds or peak RSS into wall-time phases.

- `pair` is a stable matched-pair ID, not CSV row order. A baseline uses this
  field as a unique observation ID, without implying pairing to other baselines.
- `phase` is `measured` or `warmup`. Warmups are copied but excluded from statistics.
- `validated` and `accepted` must be literal `true` or `false`, including warmups.
  Do not infer successful output validation from exit status alone. Adapters
  must use the campaign's actual validation records and fail on missing evidence.
- `accepted` describes inclusion in a valid distribution, not approval of an
  optimization: a rejected experiment can still have valid measured rows.
  Excluded measured rows require an explicit `exclude_reason`.
- Included rows require exit status `0`, `validated=true`, finite positive
  `wall_s`, and a nonblank, unique ID within each configuration.
- Comparisons require the same set of included IDs on both sides. When a valid
  pair cannot be recovered, exclude both members explicitly with a reason.

There must be at least one included observation per configuration. Single
observations are permitted, but cannot characterize run-to-run variability.
Choose trial counts according to run cost, noise and the claims being made;
the format imposes no universal acceptance threshold. All counts and exclusions
remain visible in the model.

Statistics include `n`, median, `q1`, `q3`, IQR and range. Quartiles use linear
interpolation at `(n - 1) × p`; a singleton has IQR zero. The paired saving is
`control - candidate` for each matching ID, with its own median, IQR and range.
The median of paired savings may differ from the difference of group medians.
Percent reduction is `100 × (1 - candidate_median / control_median)`, so a
negative value means slower. These statistics do not establish significance.

## Summary of improvements

```json
{
  "progress": {
    "note": "Selected results; combined change has its own measured comparison.",
    "selected": ["cache"],
    "totals": ["combined"],
    "historical": [{
      "title": "Earlier baseline to later result",
      "note": "Separate captures; conditions differ. Descriptive only.",
      "from": {"baseline": "original"},
      "to": {"comparison": "cache", "side": "candidate"}
    }]
  }
}
```

`note` is required. `selected` and `totals` reference actual comparison IDs,
without duplicates within each list. A `totals` entry must be a directly measured
comparison of the relevant original and combined configurations; the author is
responsible for that identity. The builder never composes experimental savings.

Historical entries require `title`, `note`, `from` and `to`. Each endpoint is
either `{"baseline": "id"}` or `{"comparison": "id", "side": "control"}`
(also allowing side `candidate`). They must name the same command and timing
boundary. Their distributions, identities, cohorts and hashes are retained;
they get no synthesized paired observations or confidence claims.

## Attribution and evidence

`attribution` entries require `title` and `text`. Use this for investigator-written
phase explanation and explicitly label approximate sums from separate runs.

`profiles` entries require `title`, `kind`, `path`, `boundary`, `identity` and
`note`. Supported kinds are `perfetto`, `viewer` (existing interactive HTML),
`image` and `raw`. Optional `comparison` references a comparison ID, placing the
profile beside that experiment; otherwise it appears with phase attribution.
Include instrumented status, clock origin, units and capture provenance in the
text. Local HTML viewers must be trusted artifacts; they execute when opened.

`links` entries require `title` and `path`. All artifact paths must be existing
local files. Relative paths resolve from the original manifest directory and
retain symlink mount paths for HTTP serving. Profiles and links are not copied;
serve the common ancestor of their paths and the generated report. Perfetto
opens its online UI, then receives a trace locally in the browser on user click.

## Generated output and reproducibility

The builder creates a fresh directory containing `index.html`, local CSS/JS,
`source-manifest.json`, `baseline-NN.csv`, `samples-NN.csv` and `review-data.json`.
CSV snapshots are the exact bytes used for parsing, statistics and SHA-256
hashing. The copied manifest preserves its original bytes; its paths still refer
to its original location. `review-data.json` is a derived evidence model, not a
replacement input manifest.

The model retains measurement metadata, source hashes, copied CSV filenames,
included observation IDs/values, excluded row locations/reasons, and per-resource
distributions. Comparisons also retain matching IDs and wall-time differences.
Profile entries retain source paths and capture-time SHA-256 hashes; the linked
files can change later. General evidence links have paths but no content hashes.

With `--plots`, Matplotlib produces `figures/*.svg` and `*.png`; the model records
each figure's hash, source IDs and descriptive-statistics status. Plot bytes can
vary with library versions, metadata and fonts; numerical reproducibility comes
from the CSV snapshots and model. No benchmark runs or trace conversions happen
during report generation. Keep campaign adapters, version-specific trace
converters and project measurements outside the reusable package.
