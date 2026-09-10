# Reusable profile reviews

Use this reference when presenting multiple experiments, temporal traces or
flamegraphs. Keep the user's current question first (for example build latency
and the edited module's elaboration) while retaining the decision history.

## Evidence and trace conventions

Every comparison needs a workload/cohort, timing endpoint, source/toolchain
identity, sample count and decision. Link exact commands, cache policy, raw
logs, validation and rejected candidates. Cross-campaign medians are historical
context, not a cumulative speedup curve. Do not promote small median changes
without paired evidence and output validation. Label preview feature tradeoffs.
Explain why the trial count supports the stated claim given measurement cost
and noise. Sample count alone does not establish an experiment's validity;
single observations cannot characterize run-to-run variability.

Every profile needs its capture identity, instrumented status, clock origin,
units and boundary. Distinguish these visual forms:

- Chronological trace/flame chart: events at their recorded times.
- Aggregated flamegraph: recorded call paths or sampled stacks grouped by weight.
- Native self profile: reliable program counters without trustworthy callers.

Never convert aggregated flamegraph positions to purported chronological times.
When deriving Chrome trace JSON from Lean scopes, use recorded chronological
intervals, preserve overlapping worker threads, and state whether scopes were
coalesced. Retain the original Firefox profile and conversion provenance.
Chrome `ts`/`dur` fields use microseconds; `displayTimeUnit` does not rescale them.
A trace's first event need not coincide with public invocation.

Validate native sample coverage in the intended child AND its worker threads.
Perf inheritance settings can omit most Lean runtime work. Broken DWARF stacks
(small integer PCs, impossible callers) do not support a native flamegraph even
when self symbols are sound. A symbol name alone does not establish its caller.

Inspect live Perfetto import diagnostics. For partial overlaps on one thread,
first determine whether they are an instrumentation error, uncertain process
observation at exec, or real concurrent work. If appropriate, separate uncertain
observed instances into display lanes, retaining original identifiers, every
event's times, and a transformation log. Do not silently alter durations or drop
events to remove import warnings. Preserve the original capture separately.

## Report builder

`scripts/build_review.py` (Python 3.10+, standard library by default) builds a
plain technical report: baseline measurements, summary of improvements, phase
attribution, individual experiments, and evidence. Empty sections are omitted.
Use baseline tables and distributions to establish the cost before discussing
changes. For each experiment, explain the change and compare it with its own
control. Attach existing profiles beside the relevant explanation.

The builder computes statistics from raw CSV and copies the exact bytes used for
those calculations. It writes `review-data.json` with source hashes, included
observations, exclusions, resource statistics and the quartile convention.
`scripts/review_data.py` supplies the same validated model to tables and plots.
It refuses existing output directories and validates input before creating one;
a later disk or plotting failure can leave a partial directory. It runs no
benchmarks, parses no profiler internals, and invents no flamegraph.

Example invocation (resolve the actual skill path first):

```bash
python3 /path/to/lean-profile-skill/scripts/build_review.py \
  _out/performance/review-input.json --out _out/performance/review-01
python3 -m http.server 8767 --bind 127.0.0.1 --directory _out/performance
```

Open `http://localhost:8767/review-01/`. Choose an available local port. Serve
the common artifact ancestor so linked profiles are reachable; the report does
not copy potentially huge captures. Keep their paths stable, including symlink
mount paths. A copied `source-manifest.json` is provenance of the original input;
its relative paths remain relative to the original manifest's directory. Linked
profiles are hashed when building but remain mutable files outside the report.
Archive their original captures when reproducibility requires immutable evidence.

Add `--plots` with Matplotlib installed to produce standalone SVG and PNG figures.
Plots show all included observations, medians, IQRs and ranges; paired differences
get a separate axis. These are descriptive spreads, not confidence intervals.
The tool does not install dependencies. Use a project environment or, for example,
`uv run --with matplotlib python scripts/build_review.py ... --plots`.

See [review-format.md](review-format.md) for the input contract and
`examples/review/report.json` for a complete synthetic demonstration. From the
skill checkout, a fresh demo can be built with:

```bash
python3 scripts/build_review.py examples/review/report.json --out _out/review-demo
python3 -m http.server 8767 --bind 127.0.0.1 --directory .
```

The demo's invented three-sample distributions exercise presentation and
validation; they are not performance evidence. Open `/_out/review-demo/` on the
local server. Python tests run with `python3 -m unittest discover -s tests -v`;
the plotting check skips unless Matplotlib is installed.
Run `node --test tests/test_review_js.cjs` for deterministic handoff/failure tests
using Node's built-in test runner and mocked windows/timers, without network access.

## Summarizing improvements

Select experiments explicitly by ID. The builder does not decide whether a
candidate should be accepted. A cumulative result must reference an actual
comparison of the original configuration with the combined configuration,
measured at the same public endpoint. Do not add individual time savings or
multiply ratios from different campaigns. If no combined measurement exists,
say that the total remains unmeasured.

Optional historical endpoints reference existing baseline/comparison series.
They are displayed separately as **unpaired**, with identities and cohorts.
The builder requires matching command and boundary strings; this catches obvious
mistakes but cannot establish equivalent workloads, hosts or cache states.
Investigators must assess that comparability and explain remaining differences.
Keep nested module or executable diagnostics separate from full public-command
timing.

## Browser validation

Check local evidence links over HTTP (important for symlinked artifact trees),
filters, mobile overflow, and the attached viewer's configuration/thread/mode
controls. Validate the actual remote Perfetto import as well as the handoff;
a PING/PONG stub proves message handling but not trace validity.

Perfetto transfer uses a window opened synchronously in the click handler,
repeated `PING`, and `PONG` validation against both window and origin. Fetch the
local trace, then send `{perfetto: {buffer, title, fileName, localOnly: true}}`
with a transferable ArrayBuffer to `https://ui.perfetto.dev`. Handle popup
blocking, timeouts, fetch errors and closed windows. Do not create uploads or
share links merely to show a local trace. If the API has changed, check the
[official documentation](https://perfetto.dev/docs/visualization/deep-linking-to-perfetto-ui).

Keep timeout and tab-closure guards active over the whole fetch/readiness/handoff
operation, including response-body reads after PONG. Abort the fetch on failure
and recheck the target window immediately before transfer. Settling the readiness
Promise alone must not disable those guards or allow a late fetch to report success.

Keep user-facing interpretation separate from technical validation: report the
most important measurements and uncertainty, not a checklist of every browser
check. No new measurements are required merely to review retained evidence.
