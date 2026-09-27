# Architecture

## Split of responsibilities
| Owned by LLM seats | Owned by code (agents cannot edit or override) |
|---|---|
| which hypotheses to test (PI) | decision standards (rigspec) |
| prereg statement, design choice, kill criterion (methodologist) | prereg lock + digest (`science/kernel.py`) |
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
        parked: revision cap reached, underpowered at the largest design, or leak canary fired
```
Key guards: `p_decisive>=0.8` and `controls_admissible` (statistician), `prereg_digest`, `digest_matches`,
`independent_seat` + `same_digest` + `fresh_data` (replication), `decision_not_supported` (writing without replication).

## Decisions (science/kernel.py)
Relative WAPE reduction, treatment vs comparator, paired over units × origins, **pigeonhole bootstrap** (resample
series and origins). `supported`: CI lower bound > 0 and estimate ≥ SESOI · `harmful`: CI upper < 0 ·
`no_effect`: CI inside ±SESOI · otherwise `inconclusive`. Grades: A replicated · B awaiting replication ·
C inconclusive/deviated · D failed controls.

## Campaign loop (harness/daemon.py)
1. Explorer screen (code) ranks untested changes vs the champion on exploration panels — never evidence.
2. PI plans ≤ 2 tests from the evidence ledger, variance book, lessons and messages.
3. Slices run the workflow; α per test = campaign α / planned tests, reserved at lock.
4. `promote_champion`: only a grade-A replicated result against the current champion; others are re-tested later.
5. Ledger, lessons and variance book are written (`ledger.json`) and feed the next campaign.

## Data separation (agents/common.py)
Pilot seeds (power only) · exploration seeds (screen only) · primary seed per slice · replication seed per slice.
Never reuse one for another purpose.

## Lab floor (api/floor.py + web/floor.html)
Reads only the run's records (`rig.db`, `ledger.json`, proof files, `rigspec.json` copy). Live mode polls
`/api/state` every 2 s; `build` embeds the same state into one HTML file for replay.
