---
version: "0.1.2"
level: copilot
processes:
  design: pair
  implementation: copilot
  testing: copilot
  documentation: copilot
  review: pair
  deployment: copilot
---

## Notes

This file follows the [AI-DECLARATION.md](https://ai-declaration.md/) format, version 0.1.2. It describes how AI is used to build this project. The levels above state the intended way of working at the start of the project, and will be revised if practice turns out different.

### Tools

- [Claude Code](https://claude.com/claude-code), using Anthropic's Claude models. The model in use changes over time; each AI-assisted commit names it in a `Co-Authored-By` trailer.
- The [Superpowers](https://github.com/obra/superpowers) plugin for Claude Code. It structures the work as brainstorm, written design, written plan, tests first, then review. The project is partly a trial of that way of working, and `CLAUDE.md` records what is learned.

### How the work is split

- **Design.** Daniel Whitston sets the direction and makes the design decisions, and the rulings during implementation that need him (for example, at which stage the earnings deduction is rounded). Claude made the remaining implementation-level rulings during execution, for example the operator names in the exported IR and the distribution of the random test households. Claude drafts the documents and proposes options. The initial brief in `docs/v2-brief.md` was drafted by Claude from an earlier conversation with Claude about technology choices, then checked against the sources it cites.
- **Implementation and testing.** In the first milestone (October 2026), Claude subagents wrote the code, the tests and the Catala rule files, one task at a time, from a plan Daniel approved.
- **Benefit rules.** LLMs are known to translate legal text unreliably. So rules drafted by Claude are checked by the Catala compiler, by solver-checked assertions, by differential tests against PolicyEngine UK, and by Daniel reading each change against the regulation text on legislation.gov.uk.
- **Review.** A fresh Claude reviewer checked each task, and another reviewed the whole branch at the end. Daniel reviews every pull request before it is merged, including reading the rules against regulations 22 and 36 of the Universal Credit Regulations 2013.

### Responsibility

Daniel Whitston is responsible for everything in this repository, whoever or whatever drafted it. Report errors in the rules as issues.
