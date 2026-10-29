# benefits-modeller-v2

Public repo. The workspace rules in `~/Develop/CLAUDE.md` apply, including neutral wording and the hostile-check rule for anything committed.

## Framework trial

This project trials **Superpowers**, installed at local scope (`.claude/settings.local.json`, git-ignored). Do not add Ponytail here.

Superpowers writes design and plan documents into the repo. They are public once pushed, so they follow the same wording rules as the README.

Record what worked and what got in the way here as the project goes:

- (nothing yet)

## Project notes

- Direction and open questions: `docs/v2-brief.md`. The design builds on it.
- `AI-DECLARATION.md` states how AI is used here. If the way of working changes, update its levels and notes in the same pull request.
- Publishing findings: methods, models and findings about classes of input and rule are fine. Nothing that works as a how-to for a particular claim: no worked guides to presenting evidence, no ranked lists of specific declarations to falsify. See "Publishing findings" in the brief.
- Money and legal claims in docs must cite a source (legislation.gov.uk, or the tool's own docs) and give the date checked.
- Toolchain: OCaml and Catala 1.3.0 live in a local opam switch (`_opam/`, git-ignored), an exception to the workspace mise rule because opam is the supported way to build Catala plugins. Run the tools through `opam exec --` (the Makefile does). `make build` typechecks the rules, and `make test` runs `clerk test` and then `uv run pytest`. Python is managed with uv; `.python-version` is read by mise.
- Rules: `rules/uc.catala_en` is the Catala module `Uc`, and `rules/uc_tests.catala_en` holds the assertion tests that `clerk test` runs. Catala's English syntax writes money with `$`; the unit is pounds sterling.
