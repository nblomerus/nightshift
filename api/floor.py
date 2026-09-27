"""Lab floor dashboard for the science rig.

Two ways to use it:
  make floor RUN=runs/latest            # live: http://localhost:8765 polls rig.db while the rig runs
  make replay RUN=runs/latest   # static replay: one self-contained HTML file

Everything the page shows comes from the rig's own records: messages (send), task events (queue),
slice transitions (workflow, including refused moves) and the proof files in each slice.
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR_HTML = os.path.join(REPO_ROOT, "web", "floor.html")


def _read(p):
    try:
        return json.load(open(p))
    except Exception:
        return None


def slice_details(root, sid):
    d = os.path.join(root, "slices", sid)

    def proof(n):
        return _read(os.path.join(d, "proof", n))

    pcs = sorted(glob.glob(os.path.join(d, "proof", "power_controls_r*.json")))
    reviews = sorted(glob.glob(os.path.join(d, "proof", "design_review_r*.json")))
    locked = proof("prereg_locked.json")
    fnd = os.path.join(d, "finding.md")
    return dict(
        prereg=proof("prereg_draft.json"),
        locked=dict(
            statement=locked["body"]["statement"],
            digest=locked["digest"],
            design=locked["body"]["design"]["name"],
            alpha=locked["body"]["alpha"],
            sesoi=locked["body"]["sesoi"],
        )
        if locked
        else None,
        power=[_read(p) for p in pcs],
        reviews=[_read(p) for p in reviews],
        decision=proof("decision.json"),
        replication=proof("replication.json"),
        finding=open(fnd).read() if os.path.exists(fnd) else None,
        progress=open(os.path.join(d, "progress.md")).read() if os.path.exists(os.path.join(d, "progress.md")) else "",
    )


def build_state(root, since=0.0):
    db = sqlite3.connect(os.path.join(root, "rig.db"))
    ev = []
    for i, ts, frm, to, body, sl in db.execute(
        "SELECT id, ts, frm, to_seat, body, slice FROM messages WHERE ts>?", (since,)
    ):
        ev.append(dict(t=ts, kind="msg", id=i, frm=frm, to=to, body=body, slice=sl))
    for task, ts, seat, event, kind, sl, owner, creator in db.execute(
        "SELECT e.task, e.ts, e.seat, e.event, t.kind, t.slice, t.owner, t.creator FROM task_events e "
        "JOIN tasks t ON t.id=e.task WHERE e.ts>?",
        (since,),
    ):
        ev.append(
            dict(
                t=ts,
                kind="task",
                task=task,
                seat=seat,
                event=event,
                task_kind=kind,
                slice=sl,
                owner=owner,
                creator=creator,
            )
        )
    for sl, ts, seat, frm, to, ok, note in db.execute(
        "SELECT slice, ts, seat, frm, to_stage, ok, note FROM slice_events WHERE ts>?", (since,)
    ):
        ev.append(dict(t=ts, kind="stage", slice=sl, seat=seat, frm=frm, to=to, ok=bool(ok), note=note or ""))
    ev.sort(key=lambda e: e["t"])
    spec = _read(os.path.join(root, "rigspec.json")) or _read(os.path.join(REPO_ROOT, "rigs", "forecast-lab.json"))
    slices = [dict(id=i, title=t, stage=s) for i, s, t in db.execute("SELECT id, stage, title FROM slices ORDER BY id")]
    ledger = _read(os.path.join(root, "ledger.json")) or {}
    return dict(
        events=ev,
        seats=spec["seats"],
        stages=spec["workflow"]["stages"],
        mission=spec["mission"],
        standards=spec.get("decision_standards", {}),
        slices=slices,
        details={s["id"]: slice_details(root, s["id"]) for s in slices},
        campaigns=ledger.get("campaigns", []),
        champion_history=ledger.get("champion_history", []),
        lessons=ledger.get("lessons", []),
    )


def serve(root, port=8765):
    Handler.root = root
    print(f"lab floor on http://localhost:{port}  (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def build_static(root, out):
    html = Path(FLOOR_HTML).read_text()
    data = json.dumps(build_state(root), default=str).replace("</", "<\\/")
    Path(out).write_text(html.replace("/*__RIG_DATA__*/null", data))
    return out


class Handler(BaseHTTPRequestHandler):
    root = "rig_run"

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/state":
            since = float(parse_qs(u.query).get("since", ["0"])[0])
            body, ctype = json.dumps(build_state(self.root, since), default=str).encode(), "application/json"
        else:
            body, ctype = Path(FLOOR_HTML).read_bytes(), "text/html"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass
