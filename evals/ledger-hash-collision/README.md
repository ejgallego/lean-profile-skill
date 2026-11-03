# ledger-hash-collision

A native-runtime case whose cause, a degenerate `Hashable` instance, is not described
anywhere in `references/`. It measures whether the skill transfers to an unseen hotspot
shape, not whether the agent recalls a reference example.

Keep this case blind: do not describe the cause or the fix in `SKILL.md` or
`references/`. Generic guidance (for example, classifying the hot leaf) is fine; once a
reference mentions hash collisions, this case stops measuring transfer and needs a
successor.

## Run 2026-11-03

- Skill: `git archive` of `main` at `297d043`, extracted outside the checkout; no
  `evals/` or `tests/` in it. The agent loaded `SKILL.md` from that directory, not the
  installed copy.
- Rubric and expected stdout (`sha256 a7b7fefb…`) were sealed by hash before the run in a
  directory the agent was told not to read. An audit of every tool call found no access
  outside the skill copy and the work project.
- Host: `perf_event_paranoid=0`; `lake samply` and `perf stat` used, `perf record`
  probed only. Lean `4.36.0-rc2`. Load average about 5 on 24 CPUs.
- Result: all eight graders pass. 8.327 s to 0.0386 s median, 6 passes per side, AB/BA;
  14 captured outputs and 6 argument sets byte-identical; distinct hashes 4 against
  45,880. About 8 minutes and 31 tool calls.
- Friction, in order of weight:
  1. no step classifying the hot leaf, so the agent first chased ownership;
  2. a low share of stacks reaching a thread entry was read as a capture defect, but here
     it came from deep legitimate recursion, and the summarizer shows no stack depth;
  3. how to keep `_out/` out of the project's commits is only in
     `build-and-elaboration.md`;
  4. no tool compares baseline and candidate output across argument sets without timing;
  5. the sub-100 ms warning reads as a red flag on a large effect.
