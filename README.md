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
