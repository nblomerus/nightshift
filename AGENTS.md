# AGENTS.md — brief for coding agents working on Nightshift

You are extending **Nightshift**, an ML engineer's own autonomous ML lab. LLM "seats" do the creative work; deterministic code
decides what counts. Your job is to build the roadmap in [ROADMAP.md](ROADMAP.md) without weakening that split.

## 1. Invariants — never break these
1. **No LLM decides whether a result counts.** Decisions come only from `science/kernel.py` (`decide`,
   `evidence_grade`) applied to unit-level data produced by a frozen judge. LLM output may narrate; it may not set
   `decision`, `grade`, `supports`, confidence, or a claim's status.
2. **Standards are fixed before results exist.** SESOI, target effect, α rule, power/assurance threshold, leak rule
   live in `rigs/*.json` → `decision_standards`. No seat may change them during a campaign; don't add code paths that
   let a seat choose them.
3. **Locked preregistrations are immutable.** `Preregistration.lock()` hashes the body; `run_test` refuses anything
   unlocked or modified. Changes after lock are *deviations*: they must be recorded and downgrade the grade (recording is ROADMAP item 3).
4. **The machine config is the treatment.** A slice's treatment/comparator config is authoritative and locked with
   the statement. A request to change the treatment is a *new hypothesis* for the PI, not a revision.
5. **Judges are frozen.** Agents call `judges/*`; they never edit them. Every result must be reproducible from
   (prereg digest, judge code, seed); stamping the judge digest on results is ROADMAP item 4.
6. **Every state change goes through `Rig.advance()`** with its guards; refusals are logged, not swallowed.
   `send` never changes state or creates work; `queue` is the only way to assign work.
7. **Exploration never changes a claim's status.** The explorer screen ranks candidates only.
8. **Champion changes only on a replicated grade-A result** tested against the *current* champion
   (`agents/statistician/handler.py::promote_champion`).
9. **Pilot / exploration / confirmation / replication data never overlap** (separate seeds or disjoint target months; see the judge's `data_keys`).

If a task seems to require breaking an invariant, stop and write the conflict into the PR description instead.

## 2. Repo map
| Path | What it is | Edit freely? |
|---|---|---|
| `science/kernel.py` | prereg lock, paired (pigeonhole) bootstrap, decision rule, FDR ledger, evidence grades | only with tests + a note in the PR |
| `judges/forecast.py` | frozen synthetic forecasting judge (rolling origins, PIT replay, leak canary) | no (add new judges beside it) |
| `state/rig.py` | SQLite store: messages, tasks, slices, guards, proof files | yes, keep semantics |
| `rigs/forecast-lab.json` | seats, workflow edges + guards, decision standards | yes (it is the lab's constitution — explain changes) |
| `judges/forecast_lab.py` | lab adapter for the synthetic judge: baseline, menu, designs, controls, data keys | yes (it is locked into the judge digest) |
| `agents/<seat>/handler.py` | one package per seat; `agents/common.py` shared helpers; the domain comes from `ctx["judge"]` | yes |
| `harness/daemon.py` | campaign loop (explore → plan → slices → promote → learn) | yes |
| `harness/llm.py`, `harness/fake_llm.py` | OpenAI-compatible client; deterministic offline stand-in | yes |
| `api/floor.py`, `web/floor.html` | lab-floor backend and page | yes |
| `ops/nightshift.py` | CLI (`run`, `floor serve|build`) | yes |
| `eval/` | lab self-calibration + promotion-protocol benchmarks | yes |

## 3. Conventions (lab-foundry style — see docs/CONVENTIONS.md)
- Setup: `make pyenv && make install`. Deps: add to `requirements.in`, run `make upgrade`, commit both files.
- Top-level packages, imports from repo root (`from science import kernel as sk`); no `src/`, no install step.
- **Bump `version` on every PR.** Run `make check` and `make test` before opening it; both must pass.
- ruff 0.15.14, line length 122. Long LLM prompt strings are allowed in `agents/*/handler.py` (E501 ignored there).
- Tests are offline: never call a real LLM or the network in tests. Extend `harness/fake_llm.py` when a new seat or
  prompt needs a scripted reply.
- Keep PRs small: one roadmap item per PR, with tests.

## 4. How to…
- **Add a workflow stage:** add the stage + edges (with `by` roles and `requires` guards) to the rigspec; implement
  the step in the owning seat's handler, calling `rig.advance(..., checks={guard: bool})`; queue the next seat; add
  a test that the rig *refuses* the move when the guard is false.
- **Add a seat:** add it to the rigspec (`role`, `kind` = `llm`|`code`, `tier`, `owns`); create
  `agents/<role>/handler.py`; register task kinds in `agents/__init__.py::HANDLERS`; give it a position in
  `web/floor.html` (`POS`); add a fake reply in `harness/fake_llm.py`.
- **Add a judge (new domain / real data):** a module in `judges/` exposing the lab contract documented in
  `judges/forecast_lab.py` (`agents/common.py::JUDGE_API`: baseline, menu, designs, controls, `FILES`,
  `data_keys`, `evaluate` → unit-level `abs_err[unit, origin]`, `leak_canary`); name it in the rigspec's `judge`
  field; add PIT-equivalence and leak-canary tests. `load_judge` refuses a rigspec whose judge is missing or
  incomplete.

## 5. Definition of done (every PR)
- [ ] Invariants in §1 still hold (say which ones the change touches).
- [ ] New behaviour has a test; refusals/guards have a *negative* test.
- [ ] `make check` and `make test` pass locally; coverage ≥ 75 %.
- [ ] `version` bumped; README / docs updated if commands or behaviour changed.
