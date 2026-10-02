"""Backfill the knowledge graph from a finished run's records (for runs made before the graph existed).

Reads only what the run wrote: the rigspec copy, ledger.json (evidence, screens, lessons, champion history), each
slice's locked prereg and run result, and rig.db's guarded moves and messages for parked slices."""

from __future__ import annotations

import json
import os
import sqlite3

from agents.common import describe_config, evaluation_key, judge_digest, replication_status
from science import kernel as sk


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _grade(e, proof):
    """The ledger's grade, with a B re-read from the replication proof under the current rule."""
    if not e["grade"].startswith("B:"):
        return e["grade"]
    rep = replication_status(e["decision"], _read(os.path.join(proof, "replication.json")))
    return sk.evidence_grade(e["decision"], rep, deviations=0, controls_ok=True)


def import_run(kg, root, judge):
    ledger = _read(os.path.join(root, "ledger.json")) or {}
    db = sqlite3.connect(f"file:{os.path.join(root, 'rig.db')}?mode=ro", uri=True)
    first = db.execute("SELECT min(ts) FROM slice_events").fetchone()[0]  # when the run really happened
    run = kg.begin_run(os.path.basename(os.path.abspath(root)) + " (imported)", judge_digest(judge), started=first)
    promoted = {h["campaign"]: h for h in ledger.get("champion_history", [])}
    champion = dict(judge.BASELINE)
    kg.champion(champion, describe_config(judge, champion))
    n = dict(tests=0, parked=0, lessons=0, promotions=0)
    for c in ledger.get("campaigns", []):
        k = c["campaign"]
        kg.screen(run, k, champion, c.get("screen", {}))
        for e in [e for e in ledger.get("evidence", []) if e["campaign"] == k]:
            proof = os.path.join(root, "slices", e["slice"], "proof")
            body = (_read(os.path.join(proof, "prereg_locked.json")) or {}).get("body")
            res = _read(os.path.join(proof, "run_result.json")) or {}
            if not body:
                continue
            kg.test(
                run,
                k,
                e["slice"],
                change=e["key"],
                change_desc=judge.MENU.get(e["key"], (e["key"],))[0],
                treatment=body["treatment"],
                comparator=body["comparator"],
                comparator_desc=e["champion"],
                judge=body.get("judge_digest", ""),
                evaluation=evaluation_key(judge),  # assumes the data has not changed since the run
                data_key=res.get("seed"),
                design=body["design"].get("name", ""),
                decision=dict(decision=e["decision"], point=e["point"], lo=e["lo"], hi=e["hi"]),
                grade=_grade(e, proof),
                stage="written",
                prereg=(_read(os.path.join(proof, "prereg_locked.json")) or {}).get("digest", ""),
            )
            n["tests"] += 1
        for sid in c.get("parked", []):
            key = sid.split("-", 2)[-1]
            note = db.execute(
                "SELECT note FROM slice_events WHERE slice=? AND to_stage='parked' ORDER BY ts DESC", (sid,)
            ).fetchone()
            msgs = [b for (b,) in db.execute("SELECT body FROM messages WHERE slice=? ORDER BY id", (sid,))]
            draft = _read(os.path.join(root, "slices", sid, "proof", "prereg_draft.json")) or {}
            change = judge.MENU.get(key, (key, {}))
            kg.test(
                run,
                k,
                sid,
                change=key,
                change_desc=change[0],
                treatment=dict(champion, **change[1]),
                comparator=champion,
                comparator_desc=describe_config(judge, champion),
                judge=judge_digest(judge),
                evaluation=evaluation_key(judge),
                data_key=None,
                design=draft.get("design", ""),
                decision=None,
                grade=None,
                stage="parked",
                reason=(note[0] if note else "parked") + (f"; last objection: {msgs[-1][:200]}" if msgs else ""),
            )
            n["parked"] += 1
        if k in promoted:
            h = promoted[k]
            after = dict(champion, **judge.MENU[h["promoted"]][1])
            kg.promote(
                run, k, champion, after, describe_config(judge, after), h["promoted"], f"test:{run}:{h['evidence']}"
            )
            champion = after
            n["promotions"] += 1
    for text in ledger.get("lessons", []):
        kg.lesson(run, 0, text)
        n["lessons"] += 1
    db.close()
    return n


def regrade(kg, runs_dir):
    """Rewrite every grade-B test's grade from its slice's proof files, with the current grading rule (B grades only:
    a deviated or failed-controls test is C or D, which replication does not change). Returns {test id: new grade}
    for the grades that changed. Touches no decision, effect or digest."""
    changed = {}
    rows = kg.db.execute(
        "SELECT n.id, n.label, n.props, r.label FROM nodes n JOIN edges e ON e.src = n.id AND e.type = 'IN' "
        "JOIN nodes r ON r.id = e.dst WHERE n.type = 'test' AND json_extract(n.props, '$.rig') = ?",
        (kg.rig,),
    ).fetchall()
    for tid, sid, props, run in rows:
        p = json.loads(props)
        if not (p.get("grade") or "").startswith("B:") or not p.get("decision"):
            continue
        proof = os.path.join(runs_dir, run.removesuffix(" (imported)"), "slices", sid, "proof")
        decision = p["decision"]["decision"]
        grade = sk.evidence_grade(decision, replication_status(decision, _read(os.path.join(proof, "replication.json"))),
                                  deviations=0, controls_ok=True)  # fmt: skip
        if grade != p["grade"]:
            kg.node(tid, "test", sid, grade=grade)
            changed[tid] = grade
    kg.commit()
    return changed
