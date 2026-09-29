# Nightshift lab floor (UI)

A pixel-art research lab where you watch Nightshift's seats work: each LLM call is a seat typing at its computer,
experiments run at the GPU workstations, messages and task handovers are seats walking up to each other, and every
prompt, reasoning trace, reply, guarded move and decision is one click away.

```bash
make floor RUN=runs/latest      # terminal 1: the data API (api/floor.py) on :18765
make ui                         # terminal 2: this app on http://localhost:18088
```

- **Replay** plays a finished run (`/api/replay`); **Live** follows a running one (`/api/events`, server-sent
  snapshots whenever the run's records change).
- Deep links: `?run=latest&t=201&tab=screen` opens that moment, paused. Tabs: `screen`, `seat` (`&seat=critic`),
  `slice`, `talk`.
- Keys: Space play/pause, ←/→ step beats, 1–4 speed, ⌘K help.

`lib/scene.ts` is the whole scene as a pure function of (replay, time): replay and live share it, and it is
unit-tested (`npm test`). The art follows `docs/design/` (palette, SVG primitives, concept image).

This app uses Next.js 16: read `AGENTS.md` before changing it.
