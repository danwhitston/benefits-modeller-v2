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

- [Claude Code](https://claude.com/claude-code), using Anthropic's Claude models. The model in use changes over time; each AI-assisted commit names it in a `Co-Authored-By` trailer. One known exception: commit `06b19ef` names Claude Opus 5.5, but Claude Sonnet 5.5 wrote it.
- The [Superpowers](https://github.com/obra/superpowers) plugin for Claude Code. It structures the work as brainstorm, written design, written plan, tests first, then review. The project is partly a trial of that way of working, and `CLAUDE.md` records what is learned.

### How the work is split

- **Design.** Daniel Whitston sets the direction and makes the design decisions, and the rulings during implementation that need him (for example, at which stage the earnings deduction is rounded). Claude made the remaining implementation-level rulings during execution, for example the operator names in the exported IR and the distribution of the random test households. Claude drafts the documents and proposes options. The initial brief in `docs/v2-brief.md` was drafted by Claude from an earlier conversation with Claude about technology choices, then checked against the sources it cites.
- **Implementation and testing.** In the first three milestones (October 2026), Claude subagents wrote the code, the tests and the Catala rule files, one task at a time, from a plan Daniel approved. In the third milestone, two tasks that worked on separate files apart from agreed corrections to the design (an independent reference implementation for the tests, and a research note) ran alongside the main sequence, each in its own git worktree, and were merged locally before the tasks that needed them.
- **Legal research.** In the second milestone, Claude agents researched DWP's *Advice for Decision Making* and the legislation on legislation.gov.uk, to check the design's assumptions and to record the model's gaps. Other Claude agents spot-checked what they found against the sources. In the third milestone, before the design, Claude agents made readings of the legislation and the ADM on nil assessment periods, and gathered evidence on practice from official statements, DWP staff guides, research and advocacy reports; a second agent checked the readings at source, and the evidence was checked at source when the research note `docs/nil-months.md` was written. The readings that result are recorded as the project's own, with their sources, pending specialist review.
- **Benefit rules.** LLMs are known to translate legal text unreliably. So rules drafted by Claude are checked by the Catala compiler and by solver-checked assertions. The rules of the first two milestones are also checked by differential tests against PolicyEngine UK and by Daniel reading each change against the regulation text on legislation.gov.uk. The claim window added in the third milestone, which implements regulation 54A of the Universal Credit Regulations 2013 and regulation 32A of the Claims and Payments Regulations 2013, is not compared with PolicyEngine UK. It is checked instead against a reference model in the tests, which Claude wrote separately from the same design. Daniel's reading against the regulation text does not yet cover it.
- **Review.** In each milestone, a fresh Claude reviewer checked each task, and another reviewed the whole branch at the end. Daniel reviews every pull request before it is merged, including reading the rules against regulations 22 and 36 of the Universal Credit Regulations 2013. That reading does not yet cover regulation 54A or regulation 32A (see Benefit rules).

### Responsibility

Daniel Whitston is responsible for everything in this repository, whoever or whatever drafted it. Report errors in the rules as issues.
