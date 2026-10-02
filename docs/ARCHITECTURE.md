# Architecture

## Split of responsibilities
| Owned by LLM seats | Owned by code (agents cannot edit or override) |
|---|---|
| which hypotheses to test (PI) | decision standards (rigspec) |
| rationale, design choice, kill criterion (methodologist) | prereg lock + digest (`science/kernel.py`) |
| | prereg statement: arm text and decision clause generated from the machine config and standards (`agents/common.py`) |
| design review before data (critic) | frozen judge: data, splits, metric, PIT replay, leak canary (`judges/`) |
| implementability check; running the locked arms (experimenter) | power/assurance, controls, α reservation, decision (`agents/statistician`) |
| independent re-implementation from text (replicator) | evidence grade, champion promotion |
| the write-up (writer) | workflow edges, roles and guards (`state/rig.py` + rigspec) |

## Seats and channels
```
             you ──queue──▶ pi ──queue──▶ methodologist ◀──send── critic / experimenter / statistician
                             ▲                 │ queue
                   send (findings,             ▼
                   suggestions)             critic ──queue──▶ experimenter ──queue──▶ statistician (code)
                             │                                                            │ queue
                          writer ◀──queue── replicator ◀──queue── statistician (if supported)
```
- **send** → `messages`: questions, objections, answers, suggestions. No state change, no work created.
- **queue** → `tasks` + `task_events`: pending → claimed → done | parked. Only way to assign work.
- **workflow** → `slices` + `slice_events`: every move checked for edge, role and guards; refusals recorded.
- **proof** → `runs/<run>/slices/<id>/proof/*.json`.

## Workflow (one slice = one hypothesis)
```
question → hypothesis → prereg_draft → design_review → approved_design → implementation_checked
        → controls_passed → locked → run → analysed → {replicated | not_replicated} → written
                                                   └→ written (only if the decision is not "supported")
        written (grade B, supported) → replication_queued → {replicated | not_replicated} → written
        parked: revision cap reached, underpowered at the largest design, or leak canary fired
```
Key guards: `p_decisive>=0.8` and `controls_admissible` (statistician), `prereg_digest`, `digest_matches`,
`independent_seat` + `same_digest` + `fresh_data` (replication), `decision_not_supported` (writing without replication),
`grade_b_supported` + `tested_on_current_champion` + `under_replication_cap` (another replication attempt).

Judge integrity: the SHA-256 of the judge's source files (`FILES`: the frozen judge and its lab adapter) is locked into the prereg as
`judge_digest` and stamped on `run_result`, `decision` and `replication`. `judge_unchanged` guards `locked → run`,
`run → analysed` and both replication edges, and is checked before the judge runs.

Deviations: at run, analysis, replication and write-up, `audit_locked` compares the prereg in use with the body
written at lock (`proof/prereg_locked.json`). Every changed field goes into the `prereg_deviations` table
(and BOARD.md) once, and any deviation grades the slice C. A change that kept the old digest also fails
`digest_matches`, so the run is refused; a change that was re-locked passes the digest check but not the audit.

## Decisions (science/kernel.py)
Relative WAPE reduction, treatment vs comparator, paired over units × origins, **pigeonhole bootstrap** (resample
series and origins). `supported`: CI lower bound > 0 and estimate ≥ SESOI · `harmful`: CI upper < 0 ·
`no_effect`: CI inside ±SESOI · otherwise `inconclusive`. Grades: A replicated · B awaiting replication ·
C inconclusive/deviated · D failed controls.

## Campaign loop (harness/daemon.py)
1. Explorer screen (code) ranks untested changes vs the champion on exploration panels — never evidence.
   The statistician queues another replication (same locked prereg, fresh seed) for every supported grade-B
   result tested against the current champion, before new hypotheses; at most 2 attempts per prereg.
2. PI plans ≤ 2 tests from the evidence ledger, variance book, lessons and messages.
3. Slices run the workflow; α per test = campaign α / planned tests, reserved at lock.
4. `promote_champion`: only a grade-A replicated result against the current champion; others are re-tested later.
5. Ledger, lessons and variance book are written (`ledger.json`) and feed the next campaign.

## Seat-written code (ROADMAP 5: judges/sandbox.py, judges/bikeshare.py)
Beyond the judge's menu, the PI may propose one new idea per campaign (a feature computable from the point-in-time
view). The experimenter writes it as `features(view)` under the judge's `CODE_CONTRACT`; `check_code` runs it in the
sandbox (no network, subprocesses or files outside scratch; bounded CPU, memory and time) on real point-in-time views,
twice, and requires finite, non-constant, identical output; the critic then reviews the code against the idea. The
`code_checked` guard gates the implementation step. The locked prereg carries the exact source, so the digest locks
the code. The frozen judge adds the returned columns to the champion's GLM, so a code change is compared exactly like
a menu change. The replicator writes its own implementation from the prereg text alone; it counts only if that code
passes the checks and the decision agrees. A promoted champion carries its code forward verbatim.

## The continuous lab (ops/labd.py)
`make labd` (or the launchd job it prints) runs the lab until its goal: refresh data, one lab run with the knowledge
graph, then a kernel check of the champion against the original baseline on the design-B confirmation months. It
pings the owner once per event (macOS notification + `knowledge/alerts.jsonl`) when the goal is reached (it then
stops), the PI asks the owner for something the lab cannot get itself (`ask_owner`, at most one ping a day), runs in
a row test nothing (stall), or a run crashes (once a day per error). A request is a brief, {what, why, how, done}, kept
in the knowledge graph as open until the owner answers it: in the lab floor's mailbox, or with `make requests` and
`make reply REQUEST=<id> MSG="..."`. Answers go into the PI's brief from its next plan. The rigspec's `data_notes` tell the PI
what data it can and cannot get, so it does not ask for what is ruled out (weather at this horizon) or what
accumulates by itself (the censoring mask). The supervisor waits by the wall clock, so a Mac that slept starts the
next run when it wakes, and a digest missed overnight goes out the next morning. The goal lives in the rigspec's
decision standards.

## Knowledge graph (state/knowledge.py)
The lab's memory across runs, one SQLite graph per rig (`knowledge/<rig>.db`, gitignored). After every campaign
the daemon records the kernel's records: each test (change, champion, judge digest, data key, design, decision,
grade, prereg digest), each parked attempt with its reason, promotions, plus exploratory screens and seats' lessons,
typed as such and never read as evidence. Before planning, the PI gets the graph's brief, and a change already decided
against the current champion on the same data under the same judge is not offered again (re-running it can only
reproduce the answer; the synthetic judge's fresh seeds are never a repeat). A new run continues from the graph's
champion. The graph never sets a decision or a grade. `make knowledge RIGSPEC=...` prints the brief;
`IMPORT=runs/<run>` backfills a run made before the graph existed.

## Data separation (the judge's `data_keys`; `judges/forecast_lab.py` for the synthetic judge)
Pilot seeds (power only) · exploration seeds (screen only) · primary seed per slice · replication seed per slice · extra-replication seeds; per-slice seeds come from
`slice_seed(purpose, campaign, slot)`, one block of a million per purpose.
Never reuse one for another purpose.

## Lab floor (api/floor.py + web/floor.html)
Reads only the run's records (`rig.db`, `ledger.json`, proof files, `rigspec.json` copy). Live mode polls
`/api/state` every 2 s; `build` embeds the same state into one HTML file for replay.
