"""The lab's knowledge graph: what every run of a rig has learned, kept across runs.

A run's rig.db is its own record and starts empty. The knowledge graph is the lab's memory: which changes were
tested against which champion, on which data, under which judge, and what the kernel decided; which attempts were
parked and why; how the champion was earned; what exploratory screens and seats' lessons suggested.

Evidence in the graph comes only from the kernel's records (decisions, CIs, grades, digests, guarded moves). Screens
and lessons are stored too, but typed as `screen` and `lesson` and never read as evidence. Nothing here sets a
decision, a grade or a claim's status (AGENTS.md invariant 1); the graph is read by the PI to plan.

    nodes(id, type, label, props)          run | champion | change | test | data | lesson
    edges(src, dst, type, props, run, campaign, ts)
        test -TESTS-> change, test -AGAINST-> champion, test -ON-> data, champion -PROMOTED_TO-> champion,
        run -SCREENED-> change (props: value, champion), lesson -FROM-> run, test -IN-> run
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time


def config_id(config: dict) -> str:
    return "cfg:" + hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]


class Knowledge:
    def __init__(self, path: str, rig: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path, self.rig = path, rig
        self.db = sqlite3.connect(path)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, type TEXT, label TEXT, props TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS edges(id INTEGER PRIMARY KEY, src TEXT, dst TEXT, type TEXT, props TEXT,
            run TEXT, campaign INTEGER, ts REAL);
        CREATE INDEX IF NOT EXISTS edges_src ON edges(src, type);
        CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst, type);
        """)

    # ------------------------------------------------------------------ primitives
    def node(self, nid, type_, label, **props):
        row = self.db.execute("SELECT props FROM nodes WHERE id=?", (nid,)).fetchone()
        merged = {**(json.loads(row[0]) if row else {}), **props}
        self.db.execute(
            "INSERT INTO nodes VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET label=excluded.label, props=excluded.props",
            (nid, type_, label, json.dumps(merged, default=str), time.time()),
        )
        return nid

    def edge(self, src, dst, type_, run=None, campaign=None, **props):
        self.db.execute(
            "INSERT INTO edges(src, dst, type, props, run, campaign, ts) VALUES(?,?,?,?,?,?,?)",
            (src, dst, type_, json.dumps(props, default=str), run, campaign, time.time()),
        )

    def commit(self):
        self.db.commit()

    def props(self, nid):
        row = self.db.execute("SELECT props FROM nodes WHERE id=?", (nid,)).fetchone()
        return json.loads(row[0]) if row else None

    # ------------------------------------------------------------------ writes (from the kernel's records)
    def begin_run(self, name: str, judge: str) -> str:
        rid = f"run:{name}@{int(time.time() * 1000)}"
        self.node(rid, "run", name, rig=self.rig, judge=judge, started=time.time())
        self.commit()
        return rid

    def champion(self, config: dict, desc: str) -> str:
        return self.node(config_id(config), "champion", desc, config=config, rig=self.rig)

    def promote(self, run: str, campaign: int, before: dict, after: dict, desc: str, change: str, test: str):
        self.champion(after, desc)
        self.edge(config_id(before), config_id(after), "PROMOTED_TO", run, campaign, change=change, test=test)
        self.commit()

    def test(self, run: str, campaign: int, sid: str, *, change: str, change_desc: str, treatment: dict, comparator: dict,
             comparator_desc: str, judge: str, data_key, design: str, decision: dict | None, grade: str | None,
             stage: str, reason: str = "", prereg: str = "", evaluation: str = ""):  # fmt: skip
        """One slice: tested (decision, grade) or stopped before a decision (stage parked, reason)."""
        tid = f"test:{run}:{sid}"
        seen = self.props(tid) is not None
        self.node(tid, "test", sid, rig=self.rig, treatment=config_id(treatment), decision=decision, grade=grade,
                  stage=stage, reason=reason, design=design, judge=judge, data=str(data_key), prereg=prereg,
                  evaluation=evaluation or judge)  # fmt: skip
        if seen:
            self.commit()
            return tid
        self.node(f"change:{change}", "change", change_desc, rig=self.rig)
        self.champion(comparator, comparator_desc)
        did = self.node(f"data:{judge[:16]}:{data_key}", "data", str(data_key), judge=judge)
        self.edge(tid, f"change:{change}", "TESTS", run, campaign)
        self.edge(tid, config_id(comparator), "AGAINST", run, campaign)
        self.edge(tid, did, "ON", run, campaign)
        self.edge(tid, run, "IN", run, campaign)
        self.commit()
        return tid

    def screen(self, run: str, campaign: int, champion: dict, results: dict):
        for change, value in results.items():
            self.node(f"change:{change}", "change", change, rig=self.rig)
            self.edge(
                run, f"change:{change}", "SCREENED", run, campaign, value=float(value), champion=config_id(champion)
            )
        self.commit()

    def lesson(self, run: str, campaign: int, text: str, seat: str = "pi"):
        lid = "lesson:" + hashlib.sha256(text.encode()).hexdigest()[:16]
        self.node(lid, "lesson", text, seat=seat, rig=self.rig)
        self.edge(lid, run, "FROM", run, campaign)
        self.commit()

    # ------------------------------------------------------------------ reads
    def current_champion(self) -> tuple[dict, str] | None:
        """The champion the latest promotion in this rig produced (None: never promoted)."""
        row = self.db.execute(
            "SELECT e.dst FROM edges e JOIN nodes n ON n.id = e.dst WHERE e.type='PROMOTED_TO' AND "
            "json_extract(n.props, '$.rig') = ? ORDER BY e.ts DESC, e.id DESC LIMIT 1",
            (self.rig,),
        ).fetchone()
        if not row:
            return None
        n = self.db.execute("SELECT label, props FROM nodes WHERE id=?", (row[0],)).fetchone()
        return json.loads(n[1])["config"], n[0]

    def tests(self, comparator: dict | None = None) -> list[dict]:
        """Every recorded test of this rig (optionally only those against one champion), oldest first."""
        q = (
            "SELECT t.id, t.label, t.props, tc.dst, ag.dst, r.label, ag.campaign FROM nodes t "
            "JOIN edges tc ON tc.src = t.id AND tc.type = 'TESTS' JOIN edges ag ON ag.src = t.id AND ag.type = 'AGAINST' "
            "JOIN edges ir ON ir.src = t.id AND ir.type = 'IN' JOIN nodes r ON r.id = ir.dst "
            "WHERE t.type = 'test' AND json_extract(t.props, '$.rig') = ?"
        )
        args = [self.rig]
        if comparator is not None:
            q += " AND ag.dst = ?"
            args.append(config_id(comparator))
        out = []
        for tid, sid, props, change, champ, run_name, campaign in self.db.execute(q + " ORDER BY ag.ts", args):
            p = json.loads(props)
            out.append(
                dict(
                    id=tid,
                    slice=sid,
                    change=change.split(":", 1)[1],
                    champion=champ,
                    run=run_name,
                    campaign=campaign,
                    **p,
                )
            )
        return out

    def is_repeat(self, treatment: dict, comparator: dict, evaluation: str, data_key) -> bool:
        """A decided test with the same treatment, comparator, evaluation (the judge's scoring semantics and data; the
        full judge digest for judges that do not declare one) and data already exists: running it again scores the same
        data under the same rule and can only reproduce the answer."""
        return any(
            t["treatment"] == config_id(treatment)
            and t.get("evaluation", t["judge"]) == evaluation
            and t["data"] == str(data_key)
            and t["decision"]
            for t in self.tests(comparator)
        )

    def lessons(self, limit=8) -> list[str]:
        q = (
            "SELECT n.label FROM nodes n JOIN edges e ON e.src = n.id AND e.type = 'FROM' WHERE n.type='lesson' "
            "AND json_extract(n.props, '$.rig') = ? ORDER BY e.ts DESC, e.id DESC LIMIT ?"
        )
        return [r[0] for r in self.db.execute(q, (self.rig, limit))][::-1]

    def screens(self, champion: dict) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for dst, props in self.db.execute("SELECT dst, props FROM edges WHERE type='SCREENED' ORDER BY ts"):
            p = json.loads(props)
            if p["champion"] == config_id(champion):
                out.setdefault(dst.split(":", 1)[1], []).append(p["value"])
        return out

    def brief(self, champion: dict, champion_desc: str, unavailable: list[str]) -> str:
        """What the PI needs to plan, from every run of this rig. Evidence first; screens and lessons marked."""
        n_runs = self.db.execute(
            "SELECT count(*) FROM nodes WHERE type='run' AND json_extract(props,'$.rig')=?", (self.rig,)
        ).fetchone()[0]
        lines = [f"LAB KNOWLEDGE ({n_runs} run(s) of this rig; evidence is the kernel's, never an LLM's):"]
        hist = self.db.execute(
            "SELECT e.props, e.campaign, r.label FROM edges e JOIN nodes r ON r.id = e.run WHERE e.type='PROMOTED_TO' "
            "AND e.dst = ?",
            (config_id(champion),),
        ).fetchone()
        how = (
            f"promoted in run {hist[2]} campaign {hist[1]} by {json.loads(hist[0])['change']}"
            if hist
            else "the baseline, never beaten"
        )
        lines.append(f"- Current champion: {champion_desc} ({how}).")
        mine = self.tests(champion)
        if mine:
            lines.append("- Tested against THIS champion:")
            for t in mine:
                d = t["decision"]
                res = (
                    f"{d['decision']} {d['point']:+.2%} [{d['lo']:+.2%}, {d['hi']:+.2%}], grade {t['grade']}"
                    if d
                    else f"stopped at {t['stage']}: {t['reason'][:140]}"
                )
                lines.append(
                    f"  - {t['change']} (run {t['run']} C{t['campaign']}, design {t['design']}, data {t['data']}): {res}"
                )
        else:
            lines.append("- Nothing has been tested against this champion yet.")
        older = [t for t in self.tests() if t["champion"] != config_id(champion) and t["decision"]]
        if older:
            lines.append("- Tested against EARLIER champions (effects may differ now):")
            lines += [f"  - {t['change']}: {t['decision']['decision']} {t['decision']['point']:+.2%}" for t in older[-8:]]
        if unavailable:
            lines.append(
                "- Not available this campaign, already decided against this champion on the same data under the same "
                f"judge (re-running reproduces the answer): {', '.join(unavailable)}."
            )
        scr = self.screens(champion)
        if scr:
            lines.append(
                "- Earlier exploratory screens vs this champion (NOT evidence): "
                + ", ".join(f"{k} {v[-1]:+.2%}" for k, v in scr.items())
            )
        ls = self.lessons()
        if ls:
            lines.append("- Lessons written by seats in earlier campaigns (narrative, NOT evidence):")
            lines += [f"  - {x[:220]}" for x in ls]
        return "\n".join(lines)

    def export(self) -> dict:
        nodes = [
            dict(id=i, type=t, label=lab, props=json.loads(p))
            for i, t, lab, p in self.db.execute("SELECT id, type, label, props FROM nodes")
        ]
        edges = [
            dict(src=s, dst=d, type=t, props=json.loads(p), run=r, campaign=c)
            for s, d, t, p, r, c in self.db.execute("SELECT src, dst, type, props, run, campaign FROM edges ORDER BY id")
        ]
        return dict(rig=self.rig, nodes=nodes, edges=edges)
