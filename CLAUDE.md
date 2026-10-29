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
- Got in the way: the plan assumed some tool details that turned out wrong (for example typed comparison operator names that Catala 1.3.0 does not have). The controller resolved each with a recorded ruling, but the plan should be checked against the installed tools before execution.
- Got in the way: subagents in their own git worktrees could not write to the shared workspace, so their reports had to be copied by hand.
- Got in the way: running two implementers in one checkout at once led to one agent's `git stash` sweeping up the other's uncommitted edits. Nothing was lost. Give concurrent implementers separate worktrees, and never use `git stash` in a shared checkout.
- Cost: most tasks needed one fix round after review, so each task cost an implementer, a reviewer and a re-reviewer.

## Project notes

- Direction and open questions: `docs/v2-brief.md`. The design builds on it.
- `AI-DECLARATION.md` states how AI is used here. If the way of working changes, update its levels and notes in the same pull request.
- Publishing findings: methods, models and findings about classes of input and rule are fine. Nothing that works as a how-to for a particular claim: no worked guides to presenting evidence, no ranked lists of specific declarations to falsify. See "Publishing findings" in the brief.
- Money and legal claims in docs must cite a source (legislation.gov.uk, or the tool's own docs) and give the date checked.
- Toolchain: OCaml and Catala 1.3.0 live in a local opam switch (`_opam/`, git-ignored), an exception to the workspace mise rule because opam is the supported way to build Catala plugins. Run the tools through `opam exec --` (the Makefile does). `make build` typechecks the rules, and `make test` runs `make export` (the bm-ir JSON the Python tests read), then `clerk test`, the exporter's dune tests and `uv run pytest`. Python is managed with uv; `.python-version` is read by mise.
- Rules: `rules/uc.catala_en` is the Catala module `Uc`, and `rules/uc_tests.catala_en` holds the assertion tests that `clerk test` runs. Catala's English syntax writes money with `$`; the unit is pounds sterling.
