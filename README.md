# Lean Profile Skill

An agent skill for investigating Lean build latency, module elaboration, native
runtime and browser/Wasm widgets, used with Claude Code and Codex. See
[SKILL.md](SKILL.md) for the workflow and reference routing.

## Install

Skills are directories that agents discover by location. Deploy a reviewed commit
rather than a working tree, and replace the directory instead of extracting over it,
which would leave behind files that commit removed:

```bash
# ~/.claude/skills for Claude Code (or .claude/skills/ to scope it to a repository),
# ~/.codex/skills for Codex.
(
  set -euo pipefail
  skills=~/.claude/skills
  mkdir -p -- "$skills"
  stage=$(mktemp -d "$skills/.lean-profile-skill.XXXXXX")
  trap 'rm -rf -- "$stage"' EXIT
  git archive HEAD | tar -x -C "$stage"
  test -f "$stage/SKILL.md"
  rm -rf -- "$skills/lean-profile-skill"
  mv -- "$stage" "$skills/lean-profile-skill"
  trap - EXIT
)
```

The archive keeps the runtime skill, examples, credits, and license while omitting
repository-only CI configuration, eval fixtures, and tests.

Claude Code loads it when a task matches the description, or directly with
`/lean-profile-skill`. Native sampling depends on the host: `samply` and `lake samply`
typically need `perf_event_paranoid` at 1 or lower, while `perf` often works at the
common default of 2 with user-space events. See the [backend preflight](references/profiling-loop.md#backend-preflight).

## Reports

The skill includes a static evidence-report builder. It computes baseline and
paired-comparison statistics from explicitly included CSV or JSONL observations,
with optional Matplotlib figures and links to existing profiles. Shared datasets
support several configurations and explicit pairwise contrasts. Timeouts and
unvalidated outcomes stay visible without becoming timing estimates. See
[the report guide](references/profile-review.md) and
[input format](references/review-format.md). The small example contains invented
data, not benchmark results:

```bash
python3 scripts/build_review.py examples/review/report.json --out _out/review-demo
python3 -m unittest discover -s tests -v
node --test tests/test_review_js.cjs
```

`evals/` holds an agent test case with a known answer, in the layout read by
`claude plugin eval . --allow-tools Write,Edit,Bash --scaffold`.

Serve the common ancestor of the report and its linked profiles over HTTP;
for this example, use `python3 -m http.server 8767 --bind 127.0.0.1` from the
repository root and open `http://localhost:8767/_out/review-demo/`. Add `--plots`
with Matplotlib installed for SVG/PNG distributions. The default report builder
uses only the Python standard library (Python 3.10+).

For retained `compare_commands.py` captures, use the first-party
[command importer](references/command-import.md). It preserves raw records and
exact argv without rerunning commands. Output-validation evidence is explicit:
exit status alone never makes an observation eligible for statistics.

The report format is alpha and deliberately has no compatibility layer. See the
current [input contract](references/review-format.md) when preparing a manifest.

## Repository layout

- `SKILL.md`: workflow routing, read by every agent. `agents/openai.yaml` adds
  Codex interface metadata.
- `references/`: public-build, elaboration, Verso, native-runtime and browser/Wasm
  guidance, plus the report guide and input contract.
- `scripts/`: command comparison harness, profile summarizer, output checker,
  retained-capture importer, shared observation model, report builder, and optional
  plots. Everything except the comparison harness reads evidence without running
  benchmarks.
- `assets/`: local report HTML, CSS and browser controls.
- `examples/review/`: small synthetic report inputs and trace.
- `tests/`: existing command-harness tests and report tests, discovered together
  by Python unittest, plus dependency-free Node tests for filters and the browser
  handoff. CI runs both and also checks optional plots. Node 18+ is needed only
  for the JavaScript tests, not for building a report.

Develop and review skill changes in this repository, then deploy reviewed
commits to installed skill locations. An installed copy may lag behind this
repository and should not replace its source files wholesale.

## Credits

The runtime-mechanics guidance draws on Henrik Böving's presentation
*Everything You Need To Know About The Lean Runtime*, presented at the Lean FRO
offsite on May 18, 2026. We thank Henrik for sharing the presentation and for
his work explaining Lean's runtime.

## License

Apache License 2.0, matching Lean and lean-beam. See [LICENSE](LICENSE).
