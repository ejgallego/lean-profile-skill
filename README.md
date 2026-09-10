# Lean Profile Skill

A Codex skill for investigating Lean build latency, module elaboration and
compiled native runtime. See [SKILL.md](SKILL.md) for the workflow and reference
routing.

The skill includes a static evidence-report builder. It computes baseline and
paired-comparison statistics from explicitly validated CSV samples, with optional
Matplotlib figures and links to existing profiles. See
[the report guide](references/profile-review.md) and
[input format](references/review-format.md). The small example contains invented
data, not benchmark results:

```bash
python3 scripts/build_review.py examples/review/report.json --out _out/review-demo
python3 -m unittest discover -s tests -v
```

Serve the common ancestor of the report and its linked profiles over HTTP;
for this example, use `python3 -m http.server 8767 --bind 127.0.0.1` from the
repository root and open `http://localhost:8767/_out/review-demo/`. Add `--plots`
with Matplotlib installed for SVG/PNG distributions. The default report builder
uses only the Python standard library (Python 3.10+).

## Repository layout

- `SKILL.md` and `agents/openai.yaml`: workflow routing and skill metadata.
- `references/`: public-build, elaboration, Verso and native-runtime guidance,
  plus the report guide and input contract.
- `scripts/`: command comparison harness, validated report data model and builder,
  and optional plots. The builder consumes evidence without running benchmarks.
- `assets/`: local report HTML, CSS and browser controls.
- `examples/review/`: small synthetic report inputs and trace.
- `tests/`: existing command-harness tests and report tests, discovered together
  by `python3 -m unittest discover -s tests -v`. CI also runs the optional plots.

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
