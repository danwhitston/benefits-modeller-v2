# benefits-modeller-v2

Public repo. The workspace rules in `~/Develop/CLAUDE.md` apply, including neutral wording and the hostile-check rule for anything committed.

## Framework trial

This project trials **Superpowers**, installed at local scope (`.claude/settings.local.json`, git-ignored). Do not add Ponytail here.

Superpowers writes design and plan documents into the repo. They are public once pushed, so they follow the same wording rules as the README.

Record what worked and what got in the way here as the project goes:

- Milestone 1 (29 October 2026): brainstorm, spec, plan, then subagent-driven execution with a fresh reviewer per task and a whole-branch review at the end.
- Worked: the one-question-at-a-time brainstorm settled the big choices early (an end-to-end slice first, the regulation text as ground truth, a thin OCaml exporter with the translator in Python).
- Worked: per-task reviewers caught defects that the implementers' own tests passed. Examples: a guard in the marginal-rate query that no test could fail, an optimiser check that turned proven optima into "unknown", a random sample that reached the taper in 3 of 50 households, and provenance that could name the wrong Catala version.
- Worked: the whole-branch reviewer caught public-text problems that had got through the per-task reviews: a spliced regulation quote (a task reviewer had flagged it, but as a deferred minor) and a false statement that PolicyEngine UK rounds the award.
- Worked: the exact-match differential test against PolicyEngine UK surfaced a real question of interpretation (at which stage regulation 6 rounds), now logged in `docs/mismatches.md`.
- Got in the way: the plan assumed some tool details that turned out wrong (for example typed comparison operator names that Catala 1.3.0 does not have). Each was resolved with a ruling recorded during execution, and the rulings that changed behaviour are reflected in the docs and code. The plan should still be checked against the installed tools before execution.
- Got in the way: subagents in their own git worktrees could not write to the shared workspace, so their reports had to be copied by hand.
- Got in the way: running two implementers in one checkout at once led to one agent's `git stash` sweeping up the other's uncommitted edits. Nothing was lost. Give concurrent implementers separate worktrees, and never use `git stash` in a shared checkout.
- Cost: most tasks needed one fix round after review, which typically meant an implementer, a reviewer and a scoped re-reviewer per task.
- Milestone 2 (29 October 2026): the same process, 11 tasks, with the controller ruling on plan defects and new findings during execution and recording each ruling in the plan workspace's ledger.
- Worked: the brainstorm caught a modelling trap before any code. Gains from timing pay come almost entirely from pushing an assessment period to a nil award, which is where the rules on the end of an award and surplus earnings apply. The query was limited to awards above nil, and the gap was recorded in `docs/model-gaps.md`, which is now the register of what the model leaves out.
- Worked: the differential test against PolicyEngine UK found that the planned £3,000 housing bound let households reach the benefit cap, which the rules do not model. The bound was set below the cap, not logged as a difference, because a logged difference would have let the strategic queries report gains that the law caps.
- Worked: an agent checked the design's assumptions against DWP's Advice for Decision Making, in parallel with implementation, and a reviewer re-checked its sources. It corrected the surplus earnings threshold that the design had taken from the regulation's main text (£2,500, not £300, in the temporary de minimis period) and found two qualifications (the in-work gateway and notional earnings).
- Worked: reviewers caught a quantifier-order defect in the plan's own test, a time tail in Z3's optimiser, replay running different rules from the ones the provenance described, and legal wording that overstated the law. The whole-branch reviewer again found public-text errors that per-task reviews had passed.
- Got in the way: the run was slow. Most of the time went on implementers running the full suite (about 6 minutes, most of it PolicyEngine UK). Marking those tests `slow` and adding `make test-fast` (under a minute) helped, as did running independent work (the guidance research, the documentation) alongside the main sequence. Mark slow tests from the start.
- Got in the way: Z3's `Optimize` engine had a heavy time tail that depended on what had run earlier in the same process, so tests failed in the full suite and passed alone. Optima are now found by a search of plain Z3 checks in a fresh context, with cvc5 still confirming each one. Measure solver times over several seeds before trusting a single run.
- Got in the way: the plan fixed one commit trailer for every commit, but implementers ran on different models. Trailers now name the model that wrote each commit, with one earlier exception recorded in `AI-DECLARATION.md`.
- Cost: 5 of the 11 tasks needed one fix round. The whole-branch review needed one fix wave.

## Project notes

- Direction and open questions: `docs/v2-brief.md`. The design builds on it.
- `AI-DECLARATION.md` states how AI is used here. If the way of working changes, update its levels and notes in the same pull request.
- Publishing findings: methods, models and findings about classes of input and rule are fine. Nothing that works as a how-to for a particular claim: no worked guides to presenting evidence, no ranked lists of specific declarations to falsify. See "Publishing findings" in the brief.
- Money and legal claims in docs must cite a source (legislation.gov.uk, or the tool's own docs) and give the date checked.
- Toolchain: OCaml and Catala 1.3.0 live in a local opam switch (`_opam/`, git-ignored), an exception to the workspace mise rule because opam is the supported way to build Catala plugins. Run the tools through `opam exec --` (the Makefile does). `make build` typechecks the rules, and `make test` runs `make export` (the bm-ir JSON the Python tests read), then `clerk test`, the exporter's dune tests and `uv run pytest`. `make test-fast` is the same but runs `pytest -m "not slow"`, skipping the tests marked `slow` (those that call PolicyEngine UK for more than a few seconds); `make test` and CI run everything. Python is managed with uv; `.python-version` is read by mise.
- Rules: `rules/uc.catala_en` is the Catala module `Uc`, and `rules/uc_tests.catala_en` holds the assertion tests that `clerk test` runs. Catala's English syntax writes money with `$`; the unit is pounds sterling.
