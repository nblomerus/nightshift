# Spec: bike-share station demand judge with prospective forecasts (ROADMAP item 8)

Replaces the synthetic forecasting judge with real data: daily pickups per bike-share station, scored against
availability-censored observations, with a monthly forecast that is locked before its month begins.

## 1. Why this problem
- **Censored demand.** A station with no bikes records zero pickups whether or not riders wanted one: the same
  problem as stockout-aware SKU forecasting. Scoring demand forecasts against censored pickups rewards models that
  forecast the stockouts; the judge has to know when the station was empty.
- **Real hypotheses for the seats:** station-level seasonality, holidays, pooling across nearby stations,
  intermittent-demand losses, censoring correction, zero-shot foundation-model challengers.
- **A prospective test.** Each month the lab locks its champion's forecasts for a month that has not started yet,
  with a hash and a public timestamp. When the operator publishes that month, the judge scores them against the
  baseline locked at the same moment. Nothing about that score can come from overfitting or benchmark leakage.

## 2. Data and licence
| Source | What | Where |
|---|---|---|
| Trip history | one row per trip (Lyft schema: `ride_id, rideable_type, started_at, ended_at, start_station_name, start_station_id, end_station_name, end_station_id, start_lat, start_lng, end_lat, end_lng, member_casual`) | monthly zips on S3: `s3.amazonaws.com/divvy-tripdata` (Chicago, 13–33 MB/month), `s3.amazonaws.com/tripdata` (NYC Citi Bike, ~1 GB/month) |
| Station availability | GBFS `station_status` (bikes/docks available, `is_renting`, `last_reported`) | `gbfs.lyft.com/gbfs/2.3/<chi|bkn>/en/station_status.json`, current state only (TTL 60 s) |
| Station metadata | GBFS `station_information` (id, `short_name`, lat/lon, capacity) | same feed |

- Trip files for month *m* appear 3–12 days after *m* ends; the S3 `LastModified` time is the month's
  **publication time** and is recorded for point-in-time replay.
- **Stations are keyed by name.** Divvy replaced every station id in 2025-06 (e.g. `KA1503000071` → `CHI00252`);
  1,008 of the 1,048 station names in 2025-01 still appear in 2025-07. Trip `start_station_id` equals GBFS
  `short_name` only after the switch, so the censoring mask also joins on the name in `station_information`.
- About 22 % of trips (2026-08: 189 k of 868 k) are dockless e-bike rentals with no start station. They are not
  station demand; the manifest counts them.
- The schema above holds from 2021-02; earlier files use a different schema and different station ids and are
  out of scope.
- **Availability history is not published by anyone.** GBFS is current-state only, so the lab has to snapshot it
  itself, starting now. Every day not collected is a day with no censoring mask.
- **Licence.** Both systems use the same Lyft data licence: use for any lawful purpose, published analyses allowed
  for **non-commercial** purposes, **no redistribution of the data as a standalone dataset**, no implied endorsement,
  no trademark use. Consequences for this repo:
  - raw trips, station-day aggregates and GBFS snapshots live under `data/` (gitignored), never in git;
  - test fixtures are **synthetic** files in the same schema;
  - forecasts and scores (model outputs) may be committed and published;
  - the owner confirms that the intended public use is non-commercial before the first publication.
- **Default system: Divvy.** Same code, 30× smaller downloads than Citi Bike, so a full backtest runs on a laptop.
  Citi Bike is a config switch (`system: bkn`) once the pipeline is proven.

## 3. The forecasting task
- **Unit:** station × calendar day. **Target:** pickups (trips whose `start_station_id` is the station).
- **Origin:** the publication time of trip month *m* (`as_of`). **Target month:** *m*+2. Month *m*+1 is the gap
  the publication lag forces: at `as_of`, *m*+1 has already started but none of its trips are published.
  Horizon: 32–62 days.
- **Point-in-time rule:** a feature may use a row only if the row's `available_at <= as_of`. For trips,
  `available_at` is the publication time of the trip's month; for GBFS snapshots it is `fetched_at`; for static
  calendars (holidays) it is the date the calendar was fixed. The judge enforces this; treatments never read files.
- **Weather is out of scope.** No weather forecast reaches 32–62 days; the only honest weather feature at this
  horizon is climatology, which the seasonal features already carry. A treatment that uses observed weather for
  the target month is a leak.
- **Station universe at an origin:** stations with at least one pickup in the 56 days before the end of month *m*.
  Stations that open later are not scored in that origin (reported, not hidden).
- **Metric:** WAPE = Σ|ŷ − y| / Σy over scored station-days. The kernel's paired bootstrap takes unit-level
  errors as `abs_err[station, origin]` (the day errors summed per station per origin); stations absent from an
  origin contribute zero rows, which leave the sums unchanged.

## 4. Censoring
- A station-day is **censored** if, during service hours, the station was renting and had
  `num_bikes_available == 0` for 60 minutes or more in total, from GBFS snapshots taken every 5 minutes.
- A station-day with less than 90 % snapshot coverage is **unknown** and is treated as censored.
- **Scoring:** censored and unknown station-days are excluded from the metric for both arms (the pair stays paired).
  The censor rate per origin is reported next to every score.
- **Months without snapshots** (all history before collection started) have no mask. They can be scored unmasked
  for hypotheses that do not model latent demand. A treatment tagged `needs_censor_mask` (censoring correction) is
  refused by a rigspec guard on any design that includes an unmasked month, because scoring a latent-demand model
  against censored pickups penalises it for being right.
- The minute threshold and coverage threshold are decision standards: fixed in the rigspec, not chosen by a seat.
- **First observation (2026-09-28, one evening):** 43 % of Divvy station polls showed a station renting with no
  bike. Censoring is heavy; expect the mask to remove a large share of station-days, weighted towards the stations
  where latent demand matters most. The censor rate is reported per origin for that reason.
- **Built (8d):** `make censor SYSTEM=chi` reduces snapshots (every complete local day) to
  `data/bikeshare/<system>/censor_day.csv.gz`. The judge joins it on station name, and its file is locked into the
  judge digest. A station a day's snapshots never saw is `unknown`.

## 5. Data roles (invariant 9 on real data)
Synthetic panels got fresh data from a new seed. Real data is finite, so roles are **disjoint target months**:

- Candidate target months: 2022-01 to the latest published month (2022-01 leaves ≥ 11 months of history for
  year-over-year features).
- `role(month) = ROLES[(12 * (year − 2022) + month − 1) % 5]` with
  `ROLES = (pilot, exploration, confirmation, replication, reserve)`. Because 12 mod 5 ≠ 0 the assignment rotates
  through the calendar, so every role sees every season.
- **pilot:** power and controls only. **exploration:** the explorer's screen only. **confirmation:** primary tests.
  **replication:** the replicator's re-run. **reserve:** untouched until the owner opens it (e.g. a second
  confirmation after a year of reuse).
- Features for any origin may use all published history (roles restrict what is *scored*, not what is *known*).
- **Power is limited by months, not stations.** A seasonal feature helps a lot at seasonal turning points and
  little in mid-summer, and the two-way bootstrap counts that month-to-month variation. On the synthetic fixture
  the pilot SE of the `yoy_level` effect is 7.9 points with 20 stations and still 7.9 with 80; about 11
  confirmation months on real data give an SE near 6 points. A 2 % SESOI cannot be confirmed from backtests at
  this split. The owner's options: accept a larger SESOI for backtested promotions; add pre-2021 history (older
  schema, names may link); use fewer roles; or treat backtests as screening and let prospective months decide.
- **Reuse is real:** every confirmatory test in the life of the lab scores against the same confirmation months,
  so they wear out under adaptive reuse. Only prospective months are never reused, and public claims come only
  from prospective scores.
- Designs (rigspec): `A` = confirmation months in the last 24 months; `B` = all confirmation months.

## 6. Treatment menu (initial)
Baseline: per-station Poisson GLM on day-of-week, the station's mean daily pickups over the last 28 published days,
and the system's mean daily pickups over the same window.

| key | change | notes |
|---|---|---|
| `yoy_level` | add the station's mean daily pickups in the same calendar month last year | also the positive control (large known effect) |
| `station_dow` | station-specific day-of-week profile instead of a pooled one | |
| `holidays` | US federal holiday and adjacent-day indicators | calendar known in advance |
| `neighbour_pool` | shrink each station's level towards its 5 nearest stations | coordinates known at origin |
| `system_trend` | 12-month system growth ratio | |
| `tweedie_loss` | Tweedie (p = 1.5) objective instead of Poisson | intermittent stations |
| `censor_correct` | fit on latent demand: drop or impute censored training station-days | `needs_censor_mask` |
| `foundation_zero_shot` | a pretrained time-series model, zero-shot, per station | optional (item 8f), heavy dependency |

Placebo: add a noise feature. Every treatment is a config change on the baseline, as in the forecast lab, until
item 5 lets seats write code.

## 7. Build plan (one PR each, in this order)
### 8a. GBFS collector (first: availability history only accrues from the day it starts)
- `ops/gbfs_collect.py --system chi --every 300`: poll `station_status`, append one row per station per poll
  (`fetched_at, station_id, last_reported, num_bikes_available, num_docks_available, is_renting, is_returning`) to
  `data/gbfs/<system>/<yyyy-mm-dd>.csv.gz`; refresh `station_information` daily. Never crash on a failed fetch: log
  it, and the coverage rule in §4 accounts for the gap.
- A launchd plist (macOS) and a cron line in the docs; `make collect SYSTEM=chi`.
- **Acceptance:** with a stubbed HTTP fetch: rows written per poll; a failed fetch is logged and the loop continues;
  a day file rolls over at local midnight; no network in tests.

**Running it (built).** `make collect SYSTEM=chi` runs in the foreground. To keep it running on macOS across
sleep and restarts:
```bash
python -m ops.gbfs_collect --system chi --print-launchd > ~/Library/LaunchAgents/com.nightshift.gbfs.chi.plist
launchctl load ~/Library/LaunchAgents/com.nightshift.gbfs.chi.plist
```
Or with cron: `*/5 * * * * cd <repo> && PYTHONPATH=. <python> -m ops.gbfs_collect --system chi --polls 1`.
One poll of Divvy is about 2,000 rows and 23 KB gzipped: about 0.6 M rows and 7 MB per day, 2.5 GB per year.

### 8b. Domain-pluggable lab
- Move BASELINE, MENU, DESIGNS, controls and the data-role map out of `agents/common.py` into the judge module; the
  rigspec names the judge (`"judge": "judges.forecast"`); seats and the statistician get panels through
  `judge.panel(role, design, slot)` instead of seeds. `JUDGE_PATH` follows the rigspec.
- **Acceptance:** the fake-LLM forecast demo produces the same decisions, grades and champion history as before
  the refactor (golden test); a rigspec naming a missing judge is refused at start.

### 8c. Ingest and judge
- `ops/bikeshare_ingest.py --system chi --from 2021-02`: download month zips, record `LastModified`, SHA-256 and
  row counts in `data/bikeshare/<system>/manifest.json`, aggregate to station-day pickups
  (`data/bikeshare/<system>/station_day.parquet`). Streaming per month; no whole-history load.
- `judges/bikeshare.py` with the judge contract: `panel(role, design, slot)`, `evaluate(panel, config, origins,
  cache, pit)` → `abs_err[station, origin]` and `actual`, `leak_canary(panel, config, origin)`; BASELINE, MENU,
  DESIGNS, controls, ROLES as in §5–6. `rigs/bikeshare-lab.json` with the same seats and workflow and its own
  decision standards (SESOI to be set by the owner before the first campaign; proposal: 2 % relative WAPE).
- **Acceptance** (all on a synthetic fixture in the Lyft schema under `tests/fixtures/bikeshare/`, ~20 stations ×
  30 months, with a planted day-of-week effect and planted stockouts):
  - PIT equivalence: predictions at an origin from the full panel equal predictions from a panel ingested only from
    files whose publication time is ≤ `as_of`;
  - leak canary: a treatment that reads the target month's actual pickups is flagged; the baseline is not;
  - roles: target months of different roles never overlap, and every role covers all 12 calendar months by 2026;
  - positive control (`yoy_level`) is `supported` and the placebo is not, on the fixture;
  - `make demo RIGSPEC=rigs/bikeshare-lab.json` runs offline end to end with the fake LLM.

### 8d. Censoring mask
- `ops/gbfs_reduce.py`: snapshots → `data/bikeshare/<system>/censor_day.parquet` (station-day empty-minutes,
  coverage, censored flag). The judge joins it; `needs_censor_mask` guard in the rigspec.
- **Acceptance:** planted stockouts in the fixture are flagged; a day at 80 % coverage is `unknown`; a
  `needs_censor_mask` treatment on an unmasked design is refused with a logged guard; masking changes both arms'
  scored rows identically.

### 8e. Monthly prospective lock and score
- `make lock-month SYSTEM=chi` (run when month *m* is published): forecast every universe station-day of *m*+2 with
  the current champion **and** the baseline; write `forecasts/<system>/<yyyymm>/{champion,baseline}.csv` and
  `lock.json` (champion config, judge digest, data manifest digest, `as_of`, `created_at`, SHA-256 of both forecast
  files); commit and push. The git commit and the GitHub push time are the public timestamp; optionally stamp
  `lock.json` with OpenTimestamps.
- `make score-month SYSTEM=chi MONTH=yyyymm` (run when *m*+2 is published): refuse if a forecast file's hash does not
  match `lock.json` or if `created_at` is after the first day of the target month; score both forecasts on
  uncensored station-days; paired bootstrap over stations; write `scores/<system>/<yyyymm>.json`.
- **Acceptance:** a lock → edit forecast → score sequence is refused; a lock dated inside the target month is
  refused; scoring the fixture reproduces a hand-computed WAPE.

### 8f. Foundation-model challenger (optional)
- A zero-shot pretrained time-series model as a MENU treatment, behind an optional dependency group, run in the
  item-5 sandbox once that exists.

## 8. Open decisions for the owner
- Confirm the public use is non-commercial under the Lyft data licence (read the full agreement for the system you
  pick).
- Divvy or Citi Bike for the headline (default Divvy).
- SESOI and target effect for `rigs/bikeshare-lab.json`, fixed before the first campaign.
- Where the collector runs (this Mac under launchd, or an always-on machine). A laptop that sleeps produces
  `unknown` days.
