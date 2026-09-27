# Kickoff prompt for your coding agent

Paste this into the agent in VS Code (Claude Code, Copilot agent, Cursor, …) after opening the repo:

---
You are working in the Nightshift repo. Read `AGENTS.md` fully, then `README.md`, `docs/ARCHITECTURE.md` and
`docs/CONVENTIONS.md`. The repo follows the lab-foundry project structure and pyenv workflow: top-level packages,
no install step, `make pyenv && make install`, `requirements.in` → `make upgrade`, bump `version` every PR,
`make check` and `make test` must pass.

1. Run `make pyenv`, `make install`, `make check`, `make test`, `make demo`, `make replay RUN=runs/demo` and report
   any failure before changing code.
2. Then do ROADMAP item 0 (git init, first commit, CI), then item 1. Work one ROADMAP item per branch/PR.
3. For each item: restate the acceptance criteria, write the failing tests first, implement, run `make check` and
   `make test`, bump `version`, and summarise which invariants in AGENTS.md §1 the change touches.
4. Never let LLM output set a decision, grade, standard or claim status; never edit `judges/` or a locked prereg.
   If a task seems to need that, stop and ask.
---
