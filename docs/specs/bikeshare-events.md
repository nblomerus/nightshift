# Spec: street events for the bike-share judge (ROADMAP item 8g)

The PI asked for "an events/works calendar" (request `d1297baf526654ae`, closed 2026-10-02 with a pointer here). This
spec says which of the two the lab can have at a 32–62 day horizon, from which source, and under which
point-in-time rule.

## 1. What was checked (2026-10-02)
Source: the City of Chicago's [Transportation Department Permits](https://data.cityofchicago.org/Transportation/Transportation-Department-Permits/pubx-yq2d)
(CDOT, Socrata id `pubx-yq2d`, 2.3 M rows, updated daily). Each permit has a work type, a street-closure kind, start
and end dates, coordinates (92 % of event permits, 100 % of full closures), and three dates in its life:
`applicationprocesseddate`, `applicationissueddate`, `applicationfinalizeddate`.

Lead time = start date − the date the permit could have been known:

| permits (start dates) | n | known from | median lead | ≥ 32 d ahead | ≥ 62 d ahead |
|---|---|---|---|---|---|
| Festival / Parade / Athletic (2023–25) | 4,988 | processed | 59 d | 72 % | 48 % |
| same | 4,625 | issued | 3 d | 8 % | 5 % |
| Full street closures, works (2024) | 5,292 | processed | −1 d | 2 % | 1 % |
| Block parties (2024) | 4,196 | issued | 25 d | 44 % | 23 % |

- **Works are out of scope.** Full closures are processed on or after the day the work starts; two months ahead
  almost none are known. A works feature could only be built from the future, which is a leak.
- **Street events are in scope** when known from the processed date: most festivals, parades and races apply two
  months or more ahead. `applicationprocesseddate <= applicationissueddate` holds for every event permit since 2022
  (0 of 9,873 violate it).
- Event permits per year: 1,644 (2022), 1,809 (2023), 2,022 (2024), 2,216 (2025); history reaches back before 2021,
  so every scored month (2022-01 on) has events.
- The Chicago Park District's outdoor event permits (`pk66-w54g`) have no request or issue date at all, so they
  cannot be placed in time. Events in parks (Lollapalooza, Air & Water Show in Grant Park) are therefore **not**
  covered; street events are (neighbourhood festivals, parades, the marathon and other races).

## 2. Point-in-time rule
- An event permit is **known at origin `as_of`** iff `applicationprocesseddate <= as_of`. Its `available_at` is
  that date. The judge enforces it, as for trips.
- The permit's **current status is never read.** The table shows today's milestone (Complete, Cancelled, …), which
  was not known at `as_of`; filtering on it would use the future. An event cancelled after it was processed still
  counts at origins before the cancellation, as it would have in real time.
- **Known residual risks**, which the leak canary cannot detect because they live in the source table:
  1. Applications cancelled *before* processing have no processed date and are invisible at every origin
     (survivorship). They never had a date the lab could have used, so this drops events rather than leaking them.
  2. Start/end dates or locations may have been revised after processing; the portal keeps only the latest values.
     Backtests carry that risk. From the first ingest the lab keeps a monthly snapshot of the table, and prospective
     locks use only snapshots taken before the lock, which removes it for every prospective month.

## 3. Data
- `ops/events_ingest.py --system chi`: fetch Festival / Parade / Athletic permits through the Socrata API
  (`$where=worktypedescription in(...)`, paged), keep `uniquekey, worktypedescription, applicationname,
  applicationprocesseddate, applicationstartdate, applicationenddate, latitude, longitude, streetclosure`, and write
  `data/events/chi/permits-<yyyymmdd>.csv.gz` (the snapshot) plus `data/events/chi/manifest.json` (fetch time, row
  count, SHA-256 per snapshot). Rows without a processed date, start date or coordinates are counted and dropped.
- Run by the supervisor's data refresh once a month (with the trip ingest); failures are logged, not fatal.
- Licence: City of Chicago open data terms. Snapshots stay under `data/` (gitignored), like the trip files.

## 4. Treatment
Menu item `events` (a config change on the champion, like `holidays`):
- for each station and target day, `event_near` = 1 if a permit known at the origin is active that day
  (start ≤ day ≤ end) within **400 m** of the station, and `log1p(events_near)` for several at once;
- both enter the GLM as covariates. The 400 m radius is fixed here, before any result, and no seat may change it.

Seat-written features do not see the events table in this item; exposing it to the sandbox is a later item.

## 5. Judge, digest and the knowledge graph
- The events snapshot used by an evaluation is locked into `FILES`, so every prereg's judge digest covers it.
- `evaluation_key()` does not change for configs without `events`: adding the menu item reopens no decided test,
  and the knowledge graph needs no rebuild.
- `data_notes` in `rigs/bikeshare-lab.json` gain a line saying the street-events covariate exists, what it misses
  (park events), and that works cannot be known at this horizon.

## 6. Expected effect (honest)
Events touch a small share of station-days: about 2,000 events a year, mostly one to three days, each near a few
stations, against roughly 1,000 stations × 365 days. Even a large local effect (a festival closing a street can
halve or double pickups at the nearest dock) moves system-wide WAPE by little, likely well under the 10 % SESOI.
**The likely decision for `events` is `no_effect` at the current standards.** It is still worth having: the PI asked
for it, it closes a question the lab keeps raising, and a station-level effect can feed later work (an event-aware
prospective forecast for the stations affected). Acceptance step 1 measures the affected share before any campaign.

**Measured (2026-10-02, first real snapshot):** 18,455 permits kept, 4,234 dropped (no processed date, i.e.
cancelled before processing, or no coordinates). Over the 24 latest target months, 3.2 % of universe station-days
have a known event within 400 m: 6–9 % in June to September, under 0.5 % in January to April. Counting events that
were not yet known at the origin would add about a fifth more, which is the share the point-in-time rule withholds.

## 7. Build (one PR) — built in 0.24.0
- ingest + snapshot + manifest; judge feature; menu item; `data_notes` line; supervisor refresh hook.
- **Acceptance** (offline, on a synthetic permit fixture):
  - PIT: an event processed after `as_of` is invisible at that origin, visible at a later one; a permit's status
    column is never read (removing it changes nothing);
  - geometry: a station 399 m from an event is flagged, one at 401 m is not;
  - leak canary: a variant that uses issued dates or reads events processed after the origin is flagged;
  - the share of real station-days with `event_near = 1` per month is reported (step 1 of §6), and the planted
    effect on the fixture is `supported`.
