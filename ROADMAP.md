# ROADMAP

One item per PR, in order. Each item lists **why**, **what**, and **acceptance** (tests that must exist and pass).
Items 1–4 close gaps found in real-model runs; 5–8 extend the lab; 9–10 are optional.

## 0. Bootstrap the repo
- `git init`, first commit, push; confirm CI is green (lint + version check + tests).
- **Acceptance:** CI green on `master`; `make help` lists all targets.

## 1. Generate prereg arm text and decision clause from config (not free text)
- **Why:** in the 3-campaign run, after the champion changed, the methodologist kept describing the *old* champion;
  the implementation check (correctly) refused every draft and two slices parked — a whole campaign lost. The
  statement also once said "at least 2.5 %", confusing target effect with SESOI.
- **What:** build the comparator/treatment sentences and the decision clause deterministically from the machine
  config + `decision_standards` (template in `agents/common.py`); the LLM writes only the rationale and `kills_if`.
- **Acceptance:** test that after a champion promotion the next prereg's comparator text contains the new champion
  components; test that the decision clause always cites SESOI and never the target effect; e2e fake run with 2
  campaigns parks zero slices for "stale statement".

## 2. Auto-schedule a second replication for grade-B results
- **Why:** a real effect (+1.92 % true; +1.95 % estimated) stayed at grade B because one replication was
  inconclusive, and re-running it depended on the PI remembering.
- **What:** at campaign start, the daemon queues `replicate` (fresh seed, same locked prereg) for every grade-B slice
  tested against the current champion, before new hypotheses; cap at 2 replication attempts; record each attempt.
- **Acceptance:** test that a B slice gets exactly one extra replication next campaign; promotion happens only if it
  succeeds; attempts > cap are refused by a guard.

## 3. Deviation tracking
- **What:** `prereg_deviations` table in `state/rig.py` (slice, field, before, after, reason, seat); any change to a
  locked field after lock is recorded; `evidence_grade(..., deviations=n)` uses the count.
- **Acceptance:** tampering test: modify a locked prereg field → recorded deviation → grade ≤ C; `run_test` still
  refuses an unverifiable digest.

## 4. Stamp and enforce judge integrity
- **What:** compute a SHA-256 of `judges/<module>.py` at lock; store it in the locked prereg and every result/proof;
  refuse `run`/`analysed` if the digest differs. Optionally make `judges/` read-only for seat processes.
- **Acceptance:** test that editing the judge between lock and run makes `advance(..., "run")` fail with a logged
  refusal.

## 5. Code-writing experimenter and replicator (move beyond the config menu)
- **Why:** today "implementing" = choosing a config from `MENU`; real labs write code.
- **What:** judge contract `treatment(train_view) -> predictions` executed in a sandboxed subprocess (no network,
  time/memory caps, read-only judge); the experimenter writes treatment code; the implementation check compares code
  against the prereg (LLM review **plus** deterministic checks: leak canary, runtime, determinism across two runs);
  the replicator writes its own code from the prereg text only; replication counts only if both implementations
  pass the canary and agree in decision.
- **Acceptance:** sandbox tests (network blocked, timeout enforced); a leaky treatment is parked by the canary; two
  independent implementations of a MENU change reproduce the menu result within tolerance.

## 6. Batch multiplicity with Benjamini–Hochberg
- **Why:** the online LOND ledger cut power from 73 % to 33 % in the calibration benchmark; campaign Bonferroni is
  conservative.
- **What:** for a campaign's fixed batch, reserve α via BH-compatible allocation (or run all confirmatory tests, then
  BH across the batch before decisions are released); keep LOND only for open-ended streams. Update the rigspec
  `alpha_rule`.
- **Acceptance:** `eval/lab_calibration.py` gains a BH procedure; FDR ≤ 5 % and power ≥ the Bonferroni rule on the
  planted-truth bank.

## 7. Lab self-calibration as a loop
- **What:** `make calibrate` runs the planted-truth bank through the *same* kernel decisions the rig uses and writes
  FDR, power, CI coverage to `runs/calibration/`; the lab floor shows the latest numbers; CI runs a small version
  (fast bank) and fails if FDR > 10 % or coverage < 85 %.
- **Acceptance:** CI job `calibration-smoke` green; dashboard shows "lab FDR / power / coverage".

## 8. A real-data judge: bike-share station demand with prospective forecasts
- **Why:** the synthetic judge cannot show the lab works on real data. Bike-share demand is censored by empty
  stations (the stockout problem), has real hypotheses, and allows a monthly prospective test: forecasts locked
  with a hash and a public timestamp before their month begins, scored when the operator publishes the data.
- **What:** full spec in [docs/specs/bikeshare.md](docs/specs/bikeshare.md). Six PRs, in order:
  8a GBFS availability collector (first: availability history only accrues from the day it starts);
  8b domain-pluggable lab (judge named in the rigspec; data roles instead of seeds);
  8c trip ingest + `judges/bikeshare.py` + `rigs/bikeshare-lab.json`;
  8d censoring mask; 8e monthly prospective lock and score; 8f foundation-model challenger (optional).
- **Acceptance:** per sub-item in the spec. Tests run on a synthetic fixture in the operator's schema; real data
  stays under the gitignored `data/` (the licence forbids redistributing it).

## 9. Lab floor upgrades (optional)
- Server-sent events instead of 2 s polling; per-seat transcript (prompts/replies from `llm_calls.json`); campaign
  markers on the scrubber; champion history panel.
- **Acceptance:** `tests/test_ops_cli.py` still builds a replay; a JS smoke test (e.g. vitest or QuickJS) renders
  the embedded example without errors.

## 10. OpenRig bridge (optional)
- Map `rigs/*.json` to an OpenRig RigSpec (seats as Claude Code / Codex sessions, `rig send` / `rig queue`), with the
  statistician and judges exposed as a CLI the workflow must call. Keep this repo's SQLite record as the source of
  truth for the lab floor.

## Known limitations (from the runs so far)
- The treatment space is a menu of 8 config changes on a synthetic judge (item 5, item 8).
- LLM seats vary run to run; the workflow guards, not the prompts, keep outcomes in bounds.
- Power/assurance uses pilot estimates from the same synthetic process as the test panels.
