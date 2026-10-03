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
import re
import sqlite3
import time

UNDERPOWERED = "underpowered at largest design"  # agents/statistician/handler.py's park note
DESIGN_CHECK_FAILED = "design check failed"  # agents/statistician/handler.py's park note (judge-specific guard)
LEAK_CANARY_FIRED = "leak canary fired"  # agents/statistician/handler.py's park note
REVISION_CAP_REACHED = "revision cap reached"  # agents/methodologist/handler.py's park note
# Park notes whose cause is a function only of the treatment/data (seeded power check, judge guards, leak canary):
# re-running the same treatment on the same data under the same judge can only park it again. Defined once here and
# imported by the handlers that write these notes, so the literal strings cannot drift out of sync with is_repeat.
TERMINAL_PARK_REASONS = (UNDERPOWERED, DESIGN_CHECK_FAILED, LEAK_CANARY_FIRED)
# A revision cap comes from LLM review rounds, not from the data, so one could be bad luck: it counts as terminal only
# once the same treatment has hit it this many times on the same data.
REVISION_CAP_REPEATS = 2
LESSON_OVERLAP = 0.6  # share of the shorter lesson's words two lessons must share to count as one idea restated
RECENT_TESTS = 20  # individual lines kept in the PI's brief for the current champion; older tests fold by change


def config_id(config: dict) -> str:
    return "cfg:" + hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]


def is_terminal_park(reason: str | None) -> bool:
    """Whether a park note names a deterministic, terminal cause (see TERMINAL_PARK_REASONS)."""
    return any((reason or "").startswith(r) for r in TERMINAL_PARK_REASONS)


def settled(tests: list[dict]) -> bool:
    """Whether these earlier attempts at one treatment (same champion, judge and data) already settle it: a decision,
    a deterministic terminal park, or the revision cap hit REVISION_CAP_REPEATS times."""
    parked = [t for t in tests if t["stage"] == "parked"]
    return (
        any(t["decision"] for t in tests)
        or any(is_terminal_park(t.get("reason")) for t in parked)
        or sum((t.get("reason") or "").startswith(REVISION_CAP_REACHED) for t in parked) >= REVISION_CAP_REPEATS
    )


def idea_fingerprint(idea: str) -> str:
    """Short content hash of a seat-written idea's text, used to tell two different ideas apart when their
    slugified names collide (agents/pi/handler.py::take_picks)."""
    return hashlib.sha256(str(idea).strip().encode()).hexdigest()[:12]


def request_id(what: str) -> str:
    """The id `Knowledge.request()` gives a request for this exact text, computed the same way it is stored so a
    caller can check whether it is already open without writing to the graph."""
    return "request:" + hashlib.sha256(str(what).strip()[:800].encode()).hexdigest()[:16]


class Knowledge:
    def __init__(self, path: str, rig: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path, self.rig = path, rig
        self.db = sqlite3.connect(path, timeout=30)  # the floor server and `make reply` share this file
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
    def begin_run(self, name: str, judge: str, started: float | None = None) -> str:
        started = time.time() if started is None else started
        rid = f"run:{name}@{int(started * 1000)}"
        self.node(rid, "run", name, rig=self.rig, judge=judge, started=started)
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
             stage: str, reason: str = "", prereg: str = "", evaluation: str = "", idea_fp: str = ""):  # fmt: skip
        """One slice: tested (decision, grade) or stopped before a decision (stage parked, reason). `idea_fp`
        (code ideas only) fingerprints the idea's text, so a later idea whose slugified name collides with this
        one's can still be told apart from it (agents/pi/handler.py::take_picks)."""
        tid = f"test:{run}:{sid}"
        seen = self.props(tid) is not None
        self.node(tid, "test", sid, rig=self.rig, treatment=config_id(treatment), decision=decision, grade=grade,
                  stage=stage, reason=reason, design=design, judge=judge, data=str(data_key), prereg=prereg,
                  evaluation=evaluation or judge, idea_fp=idea_fp)  # fmt: skip
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

    def request(self, run: str, campaign: int, ask: dict | str):
        """The PI asked the owner for something the lab cannot get itself (the supervisor pings the owner). `ask` is
        the PI's brief, {what, why, how, done}; a bare string is just `what`. Asking the same thing again counts,
        and reopens it if it had already been answered: the same condition recurring is itself new information."""
        fields = ("what", "why", "how", "done")
        ask = {"what": ask} if isinstance(ask, str) else ask
        ask = {k: str(ask.get(k) or "").strip()[:800] for k in fields}
        rid = request_id(ask["what"])
        row = self.db.execute("SELECT props FROM nodes WHERE id=?", (rid,)).fetchone()
        old = json.loads(row[0]) if row else {}
        new = {"status": "open"} if not row or old.get("status") == "answered" else {}
        self.node(rid, "request", ask["what"], rig=self.rig, asks=old.get("asks", 1 if row else 0) + 1,
                  last_asked=time.time(), **new, **{k: v for k, v in ask.items() if v})  # fmt: skip
        self.edge(rid, run, "FROM", run, campaign)
        self.commit()
        return rid

    def request_open(self, what: str) -> bool:
        """Whether a request for this exact text is already open and unanswered, without writing anything: lets a
        caller that must ask only once per condition (e.g. ask_for_fresh_data) skip re-filing while it still is."""
        row = self.db.execute("SELECT props FROM nodes WHERE id=?", (request_id(what),)).fetchone()
        return bool(row) and json.loads(row[0]).get("status") == "open"

    def reply(self, text: str, request: str | None = None):
        """The owner's answer to the lab (`make reply`, or the lab floor's mailbox); the PI reads it in its next
        brief. Naming a request answers it, which closes it."""
        row = None
        if request is not None:
            row = self.db.execute("SELECT label FROM nodes WHERE id=? AND type='request'", (request,)).fetchone()
            if row is None:  # checked before writing anything, so a refused reply leaves no open transaction
                raise KeyError(f"no such request: {request}")
        rid = f"reply:{int(time.time() * 1000)}"
        self.node(rid, "reply", text, rig=self.rig, request=request)
        if row is not None:
            self.node(request, "request", row[0], status="answered", reply=text, answered=time.time())
        self.commit()
        return rid

    def requests(self, status: str | None = None) -> list[dict]:
        """Everything the PI has asked the owner, newest first, with its status and the owner's reply."""
        out = []
        for nid, label, props, created in self.db.execute(
            "SELECT id, label, props, created FROM nodes WHERE type='request' AND json_extract(props, '$.rig') = ? "
            "ORDER BY created DESC",
            (self.rig,),
        ):
            p = json.loads(props)
            r = dict(id=nid, what=p.get("what") or label, why=p.get("why", ""), how=p.get("how", ""),
                     done=p.get("done", ""), status=p.get("status", "open"), asks=p.get("asks", 1),
                     asked=p.get("last_asked", created), reply=p.get("reply"), answered=p.get("answered"))  # fmt: skip
            if status is None or r["status"] == status:
                out.append(r)
        return out

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
            "SELECT t.id, t.label, t.props, tc.dst, ag.dst, r.label, ag.campaign, r.props FROM nodes t "
            "JOIN edges tc ON tc.src = t.id AND tc.type = 'TESTS' JOIN edges ag ON ag.src = t.id AND ag.type = 'AGAINST' "
            "JOIN edges ir ON ir.src = t.id AND ir.type = 'IN' JOIN nodes r ON r.id = ir.dst "
            "WHERE t.type = 'test' AND json_extract(t.props, '$.rig') = ?"
        )
        args = [self.rig]
        if comparator is not None:
            q += " AND ag.dst = ?"
            args.append(config_id(comparator))
        out = []
        for tid, sid, props, change, champ, run_name, campaign, rprops in self.db.execute(q + " ORDER BY ag.ts", args):
            p = json.loads(props)
            out.append(
                dict(
                    id=tid,
                    slice=sid,
                    change=change.split(":", 1)[1],
                    champion=champ,
                    run=run_name,
                    campaign=campaign,
                    run_started=json.loads(rprops).get("started"),
                    **p,
                )
            )
        out.sort(key=lambda t: (t["run_started"] or 0, t["campaign"] or 0, t["slice"]))  # when it really happened
        return out

    def is_repeat(self, treatment: dict, comparator: dict, evaluation: str, data_key) -> bool:
        """A decided test with the same treatment, comparator, evaluation (the judge's scoring semantics and data; the
        full judge digest for judges that do not declare one) and data already exists: running it again scores the same
        data under the same rule and can only reproduce the answer. A test parked for a deterministic, terminal reason
        (see TERMINAL_PARK_REASONS) counts too: the cause is a function only of the treatment/data, so on the same
        data it parks again the same way."""
        return settled(
            [
                t
                for t in self.tests(comparator)
                if t["treatment"] == config_id(treatment)
                and t.get("evaluation", t["judge"]) == evaluation
                and t["data"] == str(data_key)
            ]
        )

    def lessons(self, limit=8, distinct=True) -> list[str]:
        """The latest lessons, oldest first. With `distinct`, a lesson that restates a newer one (most of the same
        words) is folded into it and counted, so one idea repeated every campaign cannot fill the PI's whole view."""
        q = (
            "SELECT n.label FROM nodes n JOIN edges e ON e.src = n.id AND e.type = 'FROM' WHERE n.type='lesson' "
            "AND json_extract(n.props, '$.rig') = ? ORDER BY e.ts DESC, e.id DESC LIMIT ?"
        )
        newest = [r[0] for r in self.db.execute(q, (self.rig, limit * 8 if distinct else limit))]
        if not distinct:
            return newest[::-1]
        kept: list[list] = []  # [text, words, times stated], newest first
        for text in newest:
            words = set(re.findall(r"[a-z0-9_]{3,}", re.sub(r"^\(after campaign \d+\)\s*", "", text.lower())))
            # A lesson with no real words (an LLM's "N/A", "none", "-") can never match, swallow, or be swallowed:
            # it keeps its own slot like any other lesson, instead of silently absorbing every other one into it.
            same = next(
                (k for k in kept if words and k[1] and len(words & k[1]) >= LESSON_OVERLAP * min(len(words), len(k[1]))),
                None,
            )
            if same is not None:
                same[2] += 1
            elif len(kept) < limit:
                kept.append([text, words, 1])
        return [t if n == 1 else f"{t} (stated {n} times)" for t, _, n in kept][::-1]

    def _runs_since(self, exclude: str | None, stage_filter: str) -> int:
        last = self.db.execute(
            "SELECT max(json_extract(r.props, '$.started')) FROM nodes r JOIN edges e ON e.dst = r.id AND "
            "e.type = 'IN' JOIN nodes t ON t.id = e.src AND t.type = 'test' WHERE r.type = 'run' AND "
            f"json_extract(r.props, '$.rig') = ?{stage_filter}",
            (self.rig,),
        ).fetchone()[0]
        return self.db.execute(
            "SELECT count(*) FROM nodes WHERE type = 'run' AND json_extract(props, '$.rig') = ? AND id != ? AND "
            "json_extract(props, '$.started') > ?",
            (self.rig, exclude or "", last if last is not None else -1),
        ).fetchone()[0]

    def runs_without_tests(self, exclude: str | None = None) -> int:
        """Runs since the last one that tested (or stopped) any slice: how long the lab has been idle."""
        return self._runs_since(exclude, "")

    def runs_without_progress(self, exclude: str | None = None) -> int:
        """Like `runs_without_tests`, but ignoring test nodes whose stage is neither 'written' nor 'parked': a
        slice that stalled mid-workflow (a handler kept failing on it) never reached either terminal outcome, and
        counting it as activity is what let a recurring handler bug hide from the PI's idle-streak circuit breaker."""
        return self._runs_since(exclude, " AND json_extract(t.props, '$.stage') IN ('written', 'parked')")

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
            recent, earlier = (mine[-RECENT_TESTS:], mine[:-RECENT_TESTS]) if len(mine) > RECENT_TESTS else (mine, [])
            if earlier:  # folded, not dropped: one line per change key, with counts by decision, however many there are
                folded: dict[str, dict[str, int]] = {}
                for t in earlier:
                    d = t["decision"]["decision"] if t["decision"] else f"stopped at {t['stage']}"
                    folded.setdefault(t["change"], {})[d] = folded.setdefault(t["change"], {}).get(d, 0) + 1
                summary = "; ".join(
                    f"{change} ({', '.join(f'{n}x {d}' for d, n in counts.items())})" for change, counts in folded.items()
                )
                lines.append(f"  - ({len(earlier)} earlier test(s) against this champion, folded by change): {summary}")
            for t in recent:
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
        reqs = self.requests()
        open_ = [r for r in reqs if r["status"] == "open"]
        if open_:
            lines.append("- Requests open with the owner (do not ask again; keep testing what the data allows):")
            lines += [f"  - {r['what'][:200]}" for r in open_[:5]]
        replies = self.db.execute(
            "SELECT label, props, created FROM nodes WHERE type='reply' AND json_extract(props, '$.rig') = ? "
            "ORDER BY created DESC LIMIT 5",
            (self.rig,),
        ).fetchall()
        if replies:
            asked = {r["id"]: r["what"] for r in reqs}
            lines.append("- Replies from the owner, newest first (they outrank lessons):")
            for text, props, t in replies:
                about = asked.get(json.loads(props).get("request"))
                re_ = f' (to "{about[:120]}")' if about else ""
                lines.append(f"  - {time.strftime('%Y-%m-%d', time.localtime(t))}{re_}: {text[:400]}")
        scr = self.screens(champion)
        if scr:
            lines.append(
                "- Earlier exploratory screens vs this champion (NOT evidence): "
                + ", ".join(f"{k} {v[-1]:+.2%}" for k, v in scr.items())
            )
        ls = self.lessons()
        if ls:
            lines.append(
                "- Lessons written by seats in earlier campaigns (narrative, NOT evidence; weigh them, not rules):"
            )
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
