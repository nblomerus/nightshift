"""Backfill the knowledge graph from a finished run's records (for runs made before the graph existed).

Reads only what the run wrote: the rigspec copy, ledger.json (evidence, screens, lessons, champion history), each
slice's locked prereg and run result, and rig.db's guarded moves and messages for parked slices."""

from __future__ import annotations

import json
import os
import sqlite3

from agents.common import describe_config, evaluation_key, judge_digest


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def import_run(kg, root, judge):
    ledger = _read(os.path.join(root, "ledger.json")) or {}
    db = sqlite3.connect(f"file:{os.path.join(root, 'rig.db')}?mode=ro", uri=True)
    run = kg.begin_run(os.path.basename(os.path.abspath(root)) + " (imported)", judge_digest(judge))
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
                grade=e["grade"],
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
