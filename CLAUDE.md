# CLAUDE.md

Read **[AGENTS.md](AGENTS.md)** first — it holds the invariants, repo map, conventions and definition of done for
any coding agent working in this repo. The task list is **[ROADMAP.md](ROADMAP.md)**.

Quick commands: `make pyenv && make install`, `make check`, `make test`, `make demo`, `make replay RUN=runs/demo`.

**Merging:** Claude merges its own PRs on nblomerus/nightshift (`gh pr merge <n> --merge`) once `make check` and
`make test` pass (plus `make ui-check` for UI changes), using the nblomerus GitHub account only. Then it runs
`git pull --ff-only` in the main checkout and deploys. If the lab is mid-run, it waits for the run to finish before
reloading the launchd job.
