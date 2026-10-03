"""The lab's progress across runs and days, for the lab floor's Progress view and the daily digest.

Everything comes from the lab's own records: the knowledge graph (every test and its kernel decision, promotions,
lessons, data requests), the supervisor's state (last run, pacing, goal check) and its alerts. Nothing is recomputed
here, so the page and the digest can never disagree with the kernel.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os

from ops.prospective import prospective_worktree_path
from state.knowledge import Knowledge, config_id


def _read(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _day(ts):
    return dt.datetime.fromtimestamp(ts).date().isoformat() if ts else None


def _prospective_decisions(repo_root):
    """The latest pooled prospective decision (ROADMAP 8e) for every system that has one, read from
    scores/<system>/cumulative.json in the dedicated prospective worktree. Empty if that worktree, or a system's
    cumulative score, does not exist yet."""
    worktree = prospective_worktree_path(repo_root)
    out = []
    for path in sorted(glob.glob(os.path.join(worktree, "scores", "*", "cumulative.json"))):
        c = _read(path)
        if not c:
            continue
        out.append(
            dict(
                system=os.path.basename(os.path.dirname(path)),
                months=len(c["months"]),
                point=c["estimate"]["point"],
                sesoi=c["sesoi"],
                decision=c["decision"],
            )
        )
    return out


def build_progress(repo_root, rig):
    kdir = os.path.join(repo_root, "knowledge")
    kg = Knowledge(os.path.join(kdir, f"{rig}.db"), rig)
    state = _read(os.path.join(kdir, "labd_state.json"), {}) or {}
    champion = kg.current_champion()
    tests = kg.tests()
    current = champion[0] if champion else None
    ideas = []
    for n, t in enumerate(tests, 1):
        d = t.get("decision") or {}
        ideas.append(
            dict(
                n=n,
                change=t["change"],
                seat_written=t["change"].startswith("code:"),
                run=t["run"],
                campaign=t["campaign"],
                day=_day(t.get("run_started")),
                decision=d.get("decision") or ("parked" if t["stage"] == "parked" else t["stage"]),
                point=d.get("point"),
                lo=d.get("lo"),
                hi=d.get("hi"),
                grade=t.get("grade"),
                against_current=current is None or t["champion"] == config_id(current),
                reason=(t.get("reason") or "")[:240],
            )
        )
    decided = [i for i in ideas if i["point"] is not None]
    candidates = [i for i in decided if i["against_current"] and i["lo"] is not None and i["lo"] > 0]
    best = max(candidates or decided, key=lambda i: i["point"], default=None)
    runs = sorted(glob.glob(os.path.join(repo_root, "runs", "*", "rig.db")))
    per_day: dict[str, dict] = {}
    for db in runs:
        day = _day(os.path.getmtime(db))
        per_day.setdefault(day, dict(day=day, runs=0, tests=0))["runs"] += 1
    for i in decided:
        if i["day"]:
            per_day.setdefault(i["day"], dict(day=i["day"], runs=0, tests=0))["tests"] += 1
    alerts_path = os.path.join(kdir, "alerts.jsonl")
    alerts = []
    if os.path.exists(alerts_path):
        with open(alerts_path) as f:
            alerts = [json.loads(x) for x in f if x.strip()][-20:]
    last_start, every = state.get("last_start"), state.get("every")
    goal = state.get("goal")
    return dict(
        rig=rig,
        champion=dict(desc=champion[1] if champion else "the baseline (never beaten)", promoted=bool(champion)),
        goal=goal,
        best=best,
        ideas=ideas,
        counts=dict(
            tested=len(decided),
            seat_written=sum(1 for i in decided if i["seat_written"]),
            stopped=len(ideas) - len(decided),
            candidates=len(candidates),
            runs=len(runs),
        ),
        per_day=sorted(per_day.values(), key=lambda r: r["day"]),
        supervisor=dict(
            runs=state.get("runs", 0),
            idle=state.get("idle", 0),
            last_run=state.get("last_run"),
            last_start=last_start,
            every=every,
            next_run=(last_start + every) if last_start and every else None,
            status=state.get("status"),
        ),
        prospective=_prospective_decisions(repo_root),
        lessons=kg.lessons(10),
        requests=[
            r[0] for r in kg.db.execute("SELECT label FROM nodes WHERE type='request' ORDER BY created DESC LIMIT 5")
        ],
        alerts=alerts,
    )


def digest_text(p, day=None):
    """The day's digest: what the lab did, the best result, and how far it is from its goal."""
    day = day or dt.date.today().isoformat()
    today = [i for i in p["ideas"] if i["day"] == day]
    runs = next((r["runs"] for r in p["per_day"] if r["day"] == day), 0)
    decided = [i for i in today if i["point"] is not None]
    by = {}
    for i in decided:
        by[i["decision"]] = by.get(i["decision"], 0) + 1
    best = max(decided, key=lambda i: i["point"], default=None)
    g = p.get("goal") or {}
    lines = [
        f"Nightshift {day}: {runs} run(s), {len(decided)} idea(s) tested"
        + (" (" + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(by.items())) + ")" if by else ""),
        f"Best today: {best['change']} {best['point']:+.1%} [{best['lo']:+.1%}, {best['hi']:+.1%}], {best['decision']}"
        if best
        else "Best today: nothing tested",
        f"Champion: {p['champion']['desc'][:120]}",
        f"Goal: {g['point']:+.1%} of {g['goal']:.0%} (CI low {g['lo']:+.1%})"
        if g.get("goal") is not None
        else "Goal: not checked yet",
    ]
    if p.get("prospective"):
        parts = [f"{d['system']}: {d['decision']} over {d['months']} mo ({d['point']:+.1%})" for d in p["prospective"]]
        lines.append("Prospective: " + "; ".join(parts))
    return "\n".join(lines)
