"""Nightshift rig: an OpenRig-style rig for a scientific lab: durable seats with addresses, messages
(`send`) that never change state, an owned work queue (`queue`/`claim`/`complete`), and a
daemon-enforced workflow whose transition guards encode the scientific method.

State lives in one SQLite file; every seat's notes and every slice's proof live on disk:
    <root>/rig.db
    <root>/seats/<seat>/notes.md          durable per-specialist memory
    <root>/slices/<slice>/spec.md         the question + hypothesis
    <root>/slices/<slice>/progress.md     append-only log
    <root>/slices/<slice>/proof/*.json    prereg, controls, results, decisions

A change to a locked prereg is a deviation: it is recorded in `prereg_deviations` and downgrades the grade.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path


class GuardError(Exception):
    """Raised when a seat attempts a transition the workflow does not allow."""


class Rig:
    def __init__(self, root: str, spec: dict):
        self.root, self.spec = root, spec
        os.makedirs(root, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(root, "rig.db"))
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, ts REAL, frm TEXT, to_seat TEXT,
            body TEXT, slice TEXT, reply_to INTEGER, read INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, ts REAL, creator TEXT, owner TEXT,
            kind TEXT, slice TEXT, payload TEXT, state TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS task_events(task INTEGER, ts REAL, seat TEXT, event TEXT, note TEXT);
        CREATE TABLE IF NOT EXISTS slices(id TEXT PRIMARY KEY, stage TEXT, title TEXT);
        CREATE TABLE IF NOT EXISTS slice_events(slice TEXT, ts REAL, seat TEXT, frm TEXT, to_stage TEXT,
            ok INTEGER, note TEXT);
        CREATE TABLE IF NOT EXISTS prereg_deviations(slice TEXT, ts REAL, seat TEXT, field TEXT, before TEXT,
            after TEXT, reason TEXT);
        """)
        self.transitions = {(t["from"], t["to"]): t for t in spec["workflow"]["transitions"]}
        for s in spec["seats"]:
            os.makedirs(os.path.join(root, "seats", s), exist_ok=True)

    # ------------------------------------------------------------------ identity
    def role(self, seat):
        return self.spec["seats"][seat]["role"]

    def seat_for(self, role):
        return next(s for s, v in self.spec["seats"].items() if v["role"] == role)

    # ------------------------------------------------------------------ messaging
    def send(self, frm, to, body, slice_id=None, reply_to=None):
        assert to in self.spec["seats"], f"unknown seat {to}"
        cur = self.db.execute(
            "INSERT INTO messages(ts,frm,to_seat,body,slice,reply_to) VALUES(?,?,?,?,?,?)",
            (time.time(), frm, to, body, slice_id, reply_to),
        )
        self.db.commit()
        return cur.lastrowid

    def inbox(self, seat, mark_read=True):
        rows = self.db.execute(
            "SELECT id,frm,body,slice FROM messages WHERE to_seat=? AND read=0 ORDER BY id", (seat,)
        ).fetchall()
        if mark_read and rows:
            self.db.execute(f"UPDATE messages SET read=1 WHERE id IN ({','.join(str(r[0]) for r in rows)})")
            self.db.commit()
        return [dict(id=r[0], frm=r[1], body=r[2], slice=r[3]) for r in rows]

    # ------------------------------------------------------------------ queue
    def queue(self, creator, owner, kind, slice_id, payload=None):
        cur = self.db.execute(
            "INSERT INTO tasks(ts,creator,owner,kind,slice,payload,state) VALUES(?,?,?,?,?,?,?)",
            (time.time(), creator, owner, kind, slice_id, json.dumps(payload or {}), "pending"),
        )
        self._task_event(cur.lastrowid, creator, "created", f"{kind} -> {owner}")
        return cur.lastrowid

    def pending(self, seat):
        rows = self.db.execute(
            "SELECT id,kind,slice,payload FROM tasks WHERE owner=? AND state='pending' ORDER BY id", (seat,)
        ).fetchall()
        return [dict(id=r[0], kind=r[1], slice=r[2], payload=json.loads(r[3])) for r in rows]

    def claim(self, seat, task_id):
        n = self.db.execute(
            "UPDATE tasks SET state='claimed' WHERE id=? AND owner=? AND state='pending'", (task_id, seat)
        ).rowcount
        if n != 1:
            raise GuardError(f"{seat} cannot claim task {task_id}")
        self._task_event(task_id, seat, "claimed", "")

    def complete(self, seat, task_id, result=None, state="done"):
        n = self.db.execute(
            "UPDATE tasks SET state=?, result=? WHERE id=? AND owner=? AND state='claimed'",
            (state, json.dumps(result or {}), task_id, seat),
        ).rowcount
        if n != 1:
            raise GuardError(f"{seat} cannot complete task {task_id}")
        self._task_event(task_id, seat, state, "")

    def _task_event(self, task, seat, event, note):
        self.db.execute("INSERT INTO task_events VALUES(?,?,?,?,?)", (task, time.time(), seat, event, note))
        self.db.commit()

    # ------------------------------------------------------------------ slices + workflow
    def new_slice(self, slice_id, title, spec_md):
        self.db.execute("INSERT INTO slices VALUES(?,?,?)", (slice_id, "question", title))
        self.db.commit()
        d = self.slice_dir(slice_id)
        os.makedirs(os.path.join(d, "proof"), exist_ok=True)
        Path(d, "spec.md").write_text(spec_md)
        self.log(slice_id, "system", f"slice created: {title}")

    def slice_dir(self, slice_id):
        return os.path.join(self.root, "slices", slice_id)

    def stage(self, slice_id):
        return self.db.execute("SELECT stage FROM slices WHERE id=?", (slice_id,)).fetchone()[0]

    def advance(self, seat, slice_id, to_stage, checks: dict | None = None, note=""):
        """Daemon-enforced transition. `checks` maps each required guard to the evidence the
        caller presents; the rig verifies the guard list, the seat's role, and the edge."""
        frm = self.stage(slice_id)
        t = self.transitions.get((frm, to_stage))
        ok, why = True, ""
        if t is None:
            ok, why = False, f"no edge {frm} -> {to_stage}"
        elif self.role(seat) not in t["by"]:
            ok, why = False, f"role {self.role(seat)} may not move {frm} -> {to_stage}"
        else:
            missing = [g for g in t.get("requires", []) if not (checks or {}).get(g)]
            if missing:
                ok, why = False, f"unmet guards: {missing}"
        self.db.execute(
            "INSERT INTO slice_events VALUES(?,?,?,?,?,?,?)",
            (slice_id, time.time(), seat, frm, to_stage, int(ok), why or note),
        )
        if not ok:
            self.db.commit()
            self.log(slice_id, seat, f"REFUSED {frm} -> {to_stage}: {why}")
            raise GuardError(why)
        self.db.execute("UPDATE slices SET stage=? WHERE id=?", (to_stage, slice_id))
        self.db.commit()
        self.log(slice_id, seat, f"{frm} -> {to_stage}" + (f" ({note})" if note else ""))

    # ------------------------------------------------------------------ deviations
    def record_deviation(self, slice_id, seat, field, before, after, reason):
        """`seat` is the seat that found the change; values are stored as JSON."""
        self.db.execute(
            "INSERT INTO prereg_deviations VALUES(?,?,?,?,?,?,?)",
            (slice_id, time.time(), seat, field, json.dumps(before, default=str), json.dumps(after, default=str), reason),
        )
        self.db.commit()
        self.log(slice_id, seat, f"DEVIATION {field}: {before!r} -> {after!r} ({reason})")

    def deviations(self, slice_id):
        rows = self.db.execute(
            "SELECT seat, field, before, after, reason FROM prereg_deviations WHERE slice=? ORDER BY ts", (slice_id,)
        )
        return [dict(seat=s, field=f, before=json.loads(b), after=json.loads(a), reason=r) for s, f, b, a, r in rows]

    # ------------------------------------------------------------------ workspace
    def proof(self, slice_id, name, obj):
        p = os.path.join(self.slice_dir(slice_id), "proof", name)
        Path(p).write_text(json.dumps(obj, indent=1, default=str))
        return p

    def read_proof(self, slice_id, name):
        p = os.path.join(self.slice_dir(slice_id), "proof", name)
        return json.load(open(p)) if os.path.exists(p) else None

    def log(self, slice_id, seat, line):
        with open(os.path.join(self.slice_dir(slice_id), "progress.md"), "a") as f:
            f.write(f"- [{time.strftime('%H:%M:%S')}] {seat}: {line}\n")

    def note(self, seat, line):
        with open(os.path.join(self.root, "seats", seat, "notes.md"), "a") as f:
            f.write(f"- {line}\n")
