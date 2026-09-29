"""The lab floor's replay: a run turned into one ordered list of beats the UI can play back or stream live.

The daemon is single-threaded, so a run really is one sequence: a seat thinks (an LLM call), hands work over
(`queue`), talks (`send`), runs something at the compute cluster, locks a prereg at the vault, or is refused a
move. Every beat comes from the run's own records (rig.db, llm_calls.jsonl, proof files); nothing is inferred
beyond joining them on time.

Each beat has a real time `ts` (epoch seconds; live mode) and a display slot `at`/`dur` (replay mode), where an
LLM call lasts about a fifth of its real time (4-12 s) and code steps get a fixed, readable duration.
"""

from __future__ import annotations

import bisect
import glob
import json
import os
import sqlite3

import numpy as np

SEATS = ("pi", "methodologist", "critic", "experimenter", "statistician", "replicator", "writer")
THINK = dict(
    plan="Planning the campaign",
    draft_prereg="Drafting prereg",
    review_design="Reviewing the design",
    check_implementation="Checking prereg vs config",
    write="Writing up",
    replicate="Re-implementing from text",
)
COMPUTE = dict(
    run_experiment=("gpu1", "Running experiment"),
    power_controls=("gpu2", "Pilot: power + controls"),
    analyse=("gpu2", "Analysing: bootstrap + decision"),
)
DURATION = dict(queue=3.0, compute=9.0, talk=6.0, refuse=4.0, lock=4.0)


def _seat(s):
    return (s or "").split("@")[0]


def _clip(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n].rstrip() + "…"


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _calls(root):
    path = os.path.join(root, "llm_calls.jsonl")
    if not os.path.exists(path):
        return {}, {}
    starts, ends = {}, {}
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue  # a line still being written
            (starts if r["event"] == "start" else ends)[r["call"]] = r
    return starts, ends


def build_replay(root, clip_text=700):
    db = sqlite3.connect(f"file:{os.path.join(root, 'rig.db')}?mode=ro", uri=True)
    try:
        return _build(root, db, clip_text)
    finally:
        db.close()


def _build(root, db, clip_text):
    starts, ends = _calls(root)
    tasks = {
        r[0]: dict(creator=_seat(r[1]), owner=_seat(r[2]), kind=r[3], slice=r[4])
        for r in db.execute("SELECT id, creator, owner, kind, slice FROM tasks")
    }
    tev = {}
    for t, ts, ev in db.execute("SELECT task, ts, event FROM task_events"):
        tev.setdefault(t, {})[ev] = ts

    raw = []
    for tid, t in tasks.items():
        e = tev.get(tid, {})
        if "created" in e and t["creator"] != t["owner"] and t["creator"] in SEATS:
            text = f"Task for {t['owner']}: {t['kind'].replace('_', ' ')}"
            raw.append(
                (
                    e["created"],
                    dict(
                        kind="queue",
                        actor=t["creator"],
                        target=t["owner"],
                        slice=t["slice"] or "",
                        text=text,
                        task=t["kind"],
                    ),
                )
            )
        if t["kind"] in COMPUTE and "claimed" in e:
            place, label = COMPUTE[t["kind"]]
            raw.append(
                (
                    e["claimed"] + 1e-3,
                    dict(
                        kind="compute",
                        actor=t["owner"],
                        place=place,
                        slice=t["slice"],
                        text=f"{label} · {t['slice']}",
                        task=t["kind"],
                    ),
                )
            )
    for n, s in starts.items():
        e = ends.get(n)
        seat, t0 = _seat(s["seat"]), s["t"]
        task = next(
            (
                t
                for tid, t in tasks.items()
                if t["owner"] == seat
                and tev.get(tid, {}).get("claimed", 9e18) <= t0 + 0.01 <= tev.get(tid, {}).get("done", 9e18) + 0.01
            ),
            None,
        )
        label = THINK.get(task["kind"], "Answering a question") if task else "Reading the findings"
        sl = (task or {}).get("slice") or ""
        real = e["s"] if e else None  # None: the call is still in flight
        raw.append(
            (
                t0,
                dict(
                    kind="think",
                    actor=seat,
                    slice=sl,
                    text=label + (f" · {sl}" if sl else ""),
                    call=n,
                    real=real,
                    task=(task or {}).get("kind"),
                ),
            )
        )
    for mid, ts, frm, to, sl, body in db.execute("SELECT id, ts, frm, to_seat, slice, body FROM messages"):
        if _seat(frm) != _seat(to):
            raw.append(
                (
                    ts,
                    dict(kind="talk", actor=_seat(frm), target=_seat(to), slice=sl or "", text=_clip(body, 160), msg=mid),
                )
            )
    for sl, ts, seat, frm, to, ok, note in db.execute(
        "SELECT slice, ts, seat, frm, to_stage, ok, note FROM slice_events"
    ):
        if not ok:
            raw.append(
                (
                    ts,
                    dict(
                        kind="refuse",
                        actor=_seat(seat),
                        slice=sl,
                        text=f"Refused {frm} → {to}: {_clip(note, 100)}",
                        frm=frm,
                        to=to,
                    ),
                )
            )
        elif to == "locked":
            raw.append(
                (
                    ts,
                    dict(
                        kind="lock",
                        actor=_seat(seat),
                        place="vault",
                        slice=sl,
                        text=f"Locking prereg · {sl} · {note[:12]}",
                    ),
                )
            )
    raw.sort(key=lambda x: x[0])

    beats, at, campaign = [], 0.0, 0
    for ts, b in raw:
        if b["kind"] == "think" and b.get("task") == "plan":
            campaign += 1
        dur = min(max((b.get("real") or 20) / 5, 4.0), 12.0) if b["kind"] == "think" else DURATION[b["kind"]]
        b.update(ts=round(ts, 3), at=round(at, 1), dur=round(dur, 1), campaign=max(campaign, 1))
        at += dur
        beats.append(b)
    stamps = [ts for ts, _ in raw]

    def display(ts):
        return beats[max(0, bisect.bisect_right(stamps, ts) - 1)]["at"] if beats else 0.0

    spec = _read(os.path.join(root, "rigspec.json")) or {}
    slices = []
    for sid, stage, title in db.execute("SELECT id, stage, title FROM slices ORDER BY id"):
        events = [
            dict(at=display(ts), ts=round(ts, 3), seat=_seat(seat), frm=frm, to=to, ok=bool(ok), note=note or "")
            for ts, seat, frm, to, ok, note in db.execute(
                "SELECT ts, seat, frm, to_stage, ok, note FROM slice_events WHERE slice=? ORDER BY ts", (sid,)
            )
        ]
        slices.append(
            dict(id=sid, title=title, stage=stage, key=sid.split("-", 2)[-1], events=events, **_slice_proofs(root, sid))
        )
    msgs = [
        dict(id=i, at=display(ts), frm=_seat(f), to=_seat(t), slice=sl or "", body=_clip(b, 600))
        for i, ts, f, t, sl, b in db.execute("SELECT id, ts, frm, to_seat, slice, body FROM messages ORDER BY id")
    ]
    calls = {
        n: dict(
            seat=_seat(e["seat"]),
            tier=e.get("tier"),
            s=e["s"],
            error=e.get("error"),
            prompt=_clip(e["prompt"], clip_text),
            reasoning=_clip(e.get("reasoning"), clip_text),
            reply=_clip(e["reply"], clip_text),
        )  # fmt: skip
        for n, e in ends.items()
    }
    return dict(
        rig=spec.get("rig", ""),
        mission=spec.get("mission", ""),
        seats={
            _seat(s): dict(kind=v["kind"], tier=v.get("tier"), owns=v["owns"]) for s, v in spec.get("seats", {}).items()
        },
        stages=spec.get("workflow", {}).get("stages", []),
        standards={k: v for k, v in spec.get("decision_standards", {}).items() if isinstance(v, (int, float))},
        beats=beats,
        total=round(at, 1),
        calls=calls,
        msgs=msgs,
        slices=slices,
        ledger=_read(os.path.join(root, "ledger.json")) or {},
    )


def _slice_proofs(root, sid):
    d = os.path.join(root, "slices", sid, "proof")
    locked, dec, res = (
        _read(os.path.join(d, "prereg_locked.json")),
        _read(os.path.join(d, "decision.json")),
        _read(os.path.join(d, "run_result.json")),
    )
    pcs = sorted(glob.glob(os.path.join(d, "power_controls_r*.json")))
    out = dict(
        locked=None,
        decision=None,
        run=None,
        pilot=_read(pcs[-1]) if pcs else None,
        replication=_read(os.path.join(d, "replication.json")),
    )
    if locked:
        body = locked["body"]
        out["locked"] = dict(
            statement=body["statement"],
            digest=locked["digest"],
            judge=body.get("judge_digest", ""),
            design=body["design"].get("name"),
            months=body["design"].get("origins", []),
            alpha=body["alpha"],
            sesoi=body["sesoi"],
        )
    if dec:
        out["decision"] = {k: dec[k] for k in ("decision", "point", "lo", "hi", "alpha", "sesoi") if k in dec}
    if res:
        et, ec = np.asarray(res["err_t"], float), np.asarray(res["err_c"], float)
        denom = ec.sum(0)
        out["run"] = dict(
            data=res.get("seed"),
            design=res.get("design"),
            judge=res.get("judge_digest", ""),
            stations=int((ec.sum(1) > 0).sum()),
            rel=[round(float(1 - et[:, j].sum() / denom[j]), 4) if denom[j] else None for j in range(et.shape[1])],
        )
    return out


def list_runs(runs_dir):
    """Every run directory with a rig.db, newest first."""
    out = []
    for db in glob.glob(os.path.join(runs_dir, "*", "rig.db")):
        root = os.path.dirname(db)
        spec = _read(os.path.join(root, "rigspec.json")) or {}
        out.append(dict(name=os.path.basename(root), rig=spec.get("rig", ""), modified=os.path.getmtime(db),
                        recorded=os.path.exists(os.path.join(root, "llm_calls.jsonl"))))  # fmt: skip
    return sorted(out, key=lambda r: -r["modified"])
