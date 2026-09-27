# Recorded run: 3 campaigns with a real model

Seats ran on a reasoning-tier model (PI, methodologist, critic, writer) and a utility-tier model (experimenter,
replicator); 50 LLM calls, ~16 minutes, 59 tasks, 27 messages.

| Campaign | Result |
|---|---|
| 1 | last-year window **supported +13.7 % [9.6, 17.7]**, **replicated** → champion promoted; log target parked (P(decisive) 0.64 even at the largest design) |
| 2 | promotion feature and log target parked at the revision cap (stale champion description — ROADMAP item 1) |
| 3 | promotion feature **supported +1.95 % [0.14, 3.64]**, replication inconclusive → grade B, not promoted (ROADMAP item 2); log target parked |

Open `replay.html` in a browser (space = play). `BOARD.md` is the full text record; `rig.db` is the source of truth;
`ledger.json` holds campaigns, evidence, lessons and champion history. Rebuild the page with
`make replay RUN=examples/forecast-3-campaigns`.
