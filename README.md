# Nightshift

**Your own autonomous ML lab.** Agents work the night shift — proposing changes to your model, designing and running
experiments, reviewing and replicating each other's work — and in the morning you review evidence you can trust,
because the agents cannot talk their way past the scientific method.

LLM specialists ("seats") propose hypotheses, write preregistrations, review designs, implement, replicate and
write up. **Deterministic code owns everything that decides whether a result counts**: the preregistration lock,
the frozen judge, power and controls, the decision rule, the evidence grade and champion promotion. Seats talk to
each other in the open; a web page (the *lab floor*) shows them working in real time.

> **Project conventions.** Nightshift follows the **lab-foundry project structure and pyenv workflow**: top-level
> domain packages importable from the repo root (no `src/`, no install step), a pyenv virtualenv created by
> `make pyenv`, dependencies pinned in `requirements.txt` compiled from `requirements.in` with uv, a `version` file
> bumped on every PR (CI checks it), ruff 0.15.14 at line length 122, and `make check` / `make test` for CI parity.
> See [docs/CONVENTIONS.md](docs/CONVENTIONS.md).

## Quick start
```bash
make pyenv        # pyenv install 3.11 + virtualenv "nightshift" + .python-version + uv
make install      # uv pip sync requirements.txt
make test         # offline: the whole rig runs with a deterministic fake LLM
make demo         # 2 campaigns offline -> runs/demo
make replay RUN=runs/demo && open runs/demo/replay.html
```
Run against a real model (any OpenAI-compatible endpoint: local vLLM / SGLang / Ollama, or a hosted API):
```bash
cp .env.example .env        # set LLM_BASE_URL, REASONING_MODEL, UTILITY_MODEL
make floor                  # terminal 1: the lab-floor data API on :18765 (RUN=runs/latest)
make ui                     # terminal 2: the lab floor UI on http://localhost:18088 (make ui-install once)
make rig CAMPAIGNS=3        # terminal 3: the lab
```
A recorded 3-campaign run with a real model is in [examples/forecast-3-campaigns](examples/forecast-3-campaigns)
(open `replay.html`).

## How it works
**Seats** (defined in [rigs/forecast-lab.json](rigs/forecast-lab.json)): `pi`, `methodologist`, `critic`,
`experimenter`, `statistician` (**code, no LLM**), `replicator`, `writer`, plus a code-only exploratory screen.

**Communication** — nothing passes privately; every exchange is a row in the run's `rig.db`:

| Channel | Meaning |
|---|---|
| `send` (messages) | questions, objections, answers, suggestions. Never changes state, never creates work |
| `queue` (tasks) | owned work: created by one seat for another → claimed → done / parked. The only way work is assigned |
| workflow (slices) | one hypothesis moves through the method's stages; the rig checks the seat's role and the guards, and records refusals |
| proof files | prereg drafts, design reviews, power/leak/controls, locked prereg, results, decision, replication, finding |

**The method, enforced as workflow guards:**
`question → hypothesis → prereg_draft → design_review → approved_design → implementation_checked → controls_passed →
locked → run → analysed → {replicated | not_replicated} → written` (or `parked`).
Decision standards (SESOI 1 %, target effect 2.5 %, campaign α 0.05 Bonferroni, P(decisive) ≥ 0.8) are fixed in the
rigspec before any hypothesis exists; no seat can change them.

**Feedback loops:** in-slice revision (critic / experimenter / statistician → methodologist), campaigns (exploratory
screen → PI plans → tests → the champion changes **only** on a replicated grade-A result), learning (evidence ledger,
variance book, lessons carried forward, and a knowledge graph of every run that the PI plans from), replication (a supported grade-B result gets one more attempt next campaign).

## Evidence that the design matters
Synthetic benchmarks in [eval/](eval/) (full write-ups in [docs/background/](docs/background/)):
- Without a leak canary, a keep-if-better agent loop shipped a leaky feature in 20/20 campaigns and over-reported
  its gain by ~9 points ([figure](docs/figures/promotion_protocols.png)).
- Series-only bootstrap CIs covered the true effect 67.5 % of the time; series × time (pigeonhole) CIs 92–93 %.
  The number of time origins mattered more than any decision rule ([figure](docs/figures/lab_calibration.png)).

## Layout (lab-foundry style)
```
agents/     one package per seat: pi, methodologist, critic, experimenter, statistician, replicator, writer, explorer
harness/    daemon.py (the campaign loop), llm.py (OpenAI-compatible client), fake_llm.py (offline stand-in)
state/      rig.py — the SQLite record: messages, queue, workflow guards, proof files
science/    kernel.py — prereg lock, paired bootstrap, decision rule, FDR ledger, evidence grades
judges/     frozen domain judges (forecast.py: synthetic demand panel, rolling origins, leak canary)
api/        floor.py — lab-floor backend (stdlib HTTP) + static replay builder
web/        floor.html — the lab-floor page (vanilla JS, no build step)
rigs/       rigspecs: seats, workflow edges + guards, decision standards
ops/        nightshift.py — CLI used by the Makefile
eval/       lab self-calibration + promotion-protocol benchmarks
tests/      offline test suite (fake LLM, no network)
docs/       architecture, conventions, roadmap context, background write-ups, figures
examples/   a recorded real-model run
```
Start with [AGENTS.md](AGENTS.md) (for coding agents) and [ROADMAP.md](ROADMAP.md); [KICKOFF.md](KICKOFF.md) is a ready-to-paste prompt for your coding agent.
