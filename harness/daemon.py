"""Daemon for the science rig: each tick, every seat reads its inbox and works its queue.
Run from the workspace root with an `llm(prompt, system, tier) -> str` callable."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import agents as S
from harness.llm import recording_llm
from state.knowledge import Knowledge
from state.rig import GuardError, Rig

TASK_ATTEMPTS = 3  # an LLM seat that returns no usable answer gets its task again, up to this many times in all

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RIGSPEC = os.path.join(REPO_ROOT, "rigs", "forecast-lab.json")


def load_rigspec(path: str | None = None) -> dict:
    return json.loads(Path(path or DEFAULT_RIGSPEC).read_text())


def make_ctx(llm, judge):
    return dict(
        llm=llm,
        judge=judge,
        cache={},
        locked={},
        ledger_rows=[],
        alpha_per_test=0.05,
        pi_next=None,
        primary_seed={},
        replication_seed={},
        champion=dict(judge.BASELINE),
        champion_desc=S.describe_config(judge, judge.BASELINE),
        evidence=[],
        lessons=[],
        variance_book={},
        screen={},
        champion_history=[],
        campaign=0,
        n_campaigns=0,
        campaigns=[],
        replicating=[],
        ideas={},  # code:<name> -> {name, idea}: seat-proposed changes (ROADMAP 5)
        code={},  # slice -> {name, source, sha}: the code written for it
    )


def tick(rig, ctx, transcript):
    did = False
    for seat, spec in rig.spec["seats"].items():
        role = spec["role"]
        # 1) messages: questions get answered by their owner; other messages are filed as notes
        if role == "methodologist":
            msgs = rig.inbox(seat)
            qs = [m for m in msgs if m["body"].strip().endswith("?")]  # questions get answers
            for m in msgs:
                if m not in qs:
                    rig.note(seat, f"from {m['frm']}: {m['body'][:300]}")
            if qs:
                S.methodologist_answer(rig, seat, qs, ctx)
                did = True
        # 2) owned work
        for task in rig.pending(seat):
            rig.claim(seat, task["id"])
            t0 = time.time()
            try:
                result = S.HANDLERS[task["kind"]](rig, seat, task, ctx)
                rig.complete(seat, task["id"], result)
                transcript.append(
                    dict(seat=seat, task=task["kind"], slice=task["slice"], ok=True, s=round(time.time() - t0, 1))
                )
            except (GuardError, ValueError, KeyError) as e:
                rig.complete(seat, task["id"], dict(error=str(e)), state="parked")
                transcript.append(dict(seat=seat, task=task["kind"], slice=task["slice"], ok=False, error=str(e)))
                # A seat that could not answer (no JSON from its LLM) gets the same task again, twice at most. A guard
                # refusal is never retried: the rig said no.
                tries = task["payload"].get("attempt", 1)
                if (
                    isinstance(e, ValueError)
                    and not isinstance(e, GuardError)
                    and tries < TASK_ATTEMPTS
                    and task["slice"]
                ):
                    rig.queue(seat, seat, task["kind"], task["slice"], dict(task["payload"], attempt=tries + 1))
            did = True
            if (
                task["kind"] == "plan"
                and ctx["campaign"] == 1
                and rig.db.execute("SELECT count(*) FROM slices").fetchone()[0]
            ):
                # the daemon refuses an out-of-order move, whoever asks
                sid0 = rig.db.execute("SELECT id FROM slices ORDER BY id").fetchone()[0]
                try:
                    rig.advance(rig.seat_for("experimenter"), sid0, "run", checks={"judge_result": True})
                except GuardError as e:
                    transcript.append(
                        dict(
                            seat=rig.seat_for("experimenter"),
                            task="(attempted run before lock)",
                            slice=sid0,
                            ok=False,
                            error=str(e),
                        )
                    )
    return did


def board(rig):
    lines = ["## Seats", "| Seat | Kind | Owns |", "|---|---|---|"]
    for s, v in rig.spec["seats"].items():
        lines.append(f"| `{s}` | {v['kind']} | {v['owns']} |")
    lines += ["", "## Slices", "| Slice | Stage |", "|---|---|"]
    for sid, st in rig.db.execute("SELECT id, stage FROM slices ORDER BY id"):
        lines.append(f"| {sid} | {st} |")
    lines += [
        "",
        "## Queue (every task has an owner)",
        "| # | Kind | Slice | Creator → Owner | State |",
        "|---|---|---|---|---|",
    ]
    for r in rig.db.execute("SELECT id, kind, slice, creator, owner, state FROM tasks ORDER BY id"):
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3].split('@')[0]} → {r[4].split('@')[0]} | {r[5]} |")
    lines += ["", "## Messages (send: questions and answers, no state change)", ""]
    for r in rig.db.execute("SELECT id, frm, to_seat, slice, body FROM messages ORDER BY id"):
        lines.append(f"**#{r[0]} {r[1].split('@')[0]} → {r[2].split('@')[0]}** ({r[3]}): {r[4]}\n")
    lines += ["## Prereg deviations (changes after lock; each downgrades the grade)", ""]
    devs = rig.db.execute(
        "SELECT slice, seat, field, before, after, reason FROM prereg_deviations ORDER BY ts"
    ).fetchall()
    lines += (
        ["| Slice | Found by | Field | Locked | Found | Reason |", "|---|---|---|---|---|---|"] if devs else ["(none)"]
    )
    for r in devs:
        lines.append(f"| {r[0]} | {r[1].split('@')[0]} | {r[2]} | {r[3][:60]} | {r[4][:60]} | {r[5]} |")
    lines += ["", "## Workflow guard log", "| Slice | Seat | From → To | Allowed | Note |", "|---|---|---|---|---|"]
    for r in rig.db.execute("SELECT slice, seat, frm, to_stage, ok, note FROM slice_events"):
        lines.append(
            f"| {r[0]} | {r[1].split('@')[0]} | {r[2]} → {r[3]} | "
            f"{'yes' if r[4] else '**REFUSED**'} | {(r[5] or '')[:110]} |"
        )
    return "\n".join(lines)


def rebuild_config(judge, stored):
    """A config read back from JSON (tuples became lists) as the judge's own baseline plus its menu changes, or None
    if it is not one."""
    canon = json.loads(json.dumps(stored, default=str))
    config = dict(judge.BASELINE)
    for _, change in judge.MENU.values():
        if all(json.loads(json.dumps(v, default=str)) == canon.get(f) for f, v in change.items()):
            config.update(change)
    return (
        config
        if json.dumps(config, sort_keys=True, default=str) == json.dumps(canon, sort_keys=True, default=str)
        else None
    )


def open_knowledge(path, spec, judge, ctx, run_name):
    """Attach the lab's knowledge graph and continue from its champion (when it still fits this judge's menu)."""
    kg = Knowledge(path, spec.get("rig", "rig"))
    ctx["knowledge"], ctx["run_id"] = kg, kg.begin_run(run_name, S.judge_digest(judge))
    resumed = kg.current_champion()
    if resumed:
        champ = rebuild_config(judge, resumed[0])
        if champ is not None:  # None: the judge changed shape since; start from its baseline
            ctx["champion"], ctx["champion_desc"] = champ, S.describe_config(judge, champ)
    kg.champion(ctx["champion"], ctx["champion_desc"])
    kg.commit()
    return kg


def record_campaign(rig, ctx, k, champion_before, screen, new, parked, lessons_before, promoted):
    """What campaign k established, into the knowledge graph: the kernel's records, plus screens and lessons typed as
    such. Called once per campaign, after promotion."""
    kg, run, J = ctx.get("knowledge"), ctx.get("run_id"), ctx["judge"]
    if kg is None:
        return
    kg.screen(run, k, champion_before, screen)
    for e in new:
        pre = ctx["locked"][e["slice"]]
        kg.test(run, k, e["slice"], change=e["key"], change_desc=S.change_desc(ctx, e["key"]), treatment=pre.treatment,
                comparator=pre.comparator, comparator_desc=S.describe_config(J, pre.comparator), judge=pre.judge_digest,
            evaluation=S.evaluation_key(J),
                data_key=ctx["primary_seed"][e["slice"]], design=pre.design["name"],
                decision=dict(decision=e["decision"], point=e["point"], lo=e["lo"], hi=e["hi"]), grade=e["grade"],
                stage="written", prereg=pre.digest)  # fmt: skip
    for sid in parked:
        draft = rig.read_proof(sid, "prereg_draft.json") or {}
        key = draft.get("treatment_key") or sid.split("-", 2)[-1]
        note = rig.db.execute(
            "SELECT note FROM slice_events WHERE slice=? AND to_stage='parked' ORDER BY ts DESC", (sid,)
        ).fetchone()
        failed = rig.db.execute(
            "SELECT kind, result FROM tasks WHERE slice=? AND state='parked' ORDER BY id DESC", (sid,)
        ).fetchone()
        if not note and failed:  # stalled: the workflow never reached a terminal stage
            error = json.loads(failed[1] or "{}").get("error", "")[:120]
            note = (f"stalled at {rig.stage(sid)}: {failed[0]} failed ({error})",)
        refused = [
            n for (n,) in rig.db.execute("SELECT note FROM slice_events WHERE slice=? AND ok=0 ORDER BY ts", (sid,))
        ]
        msgs = [b for (b,) in rig.db.execute("SELECT body FROM messages WHERE slice=? ORDER BY id", (sid,))]
        reason = (
            (note[0] if note else "parked")
            + (f"; last objection: {msgs[-1][:200]}" if msgs else "")
            + (f"; refused: {refused[-1]}" if refused else "")
        )
        try:
            treatment = S.treatment_of(ctx, key, sid, champion_before)
        except (ValueError, KeyError):  # a code idea parked before its code existed
            treatment = dict(champion_before, idea=key)
        change = (S.change_desc(ctx, key) if (key in ctx["ideas"] or key in J.MENU) else key, None)
        kg.test(
            run,
            k,
            sid,
            change=key,
            change_desc=change[0],
            treatment=treatment,
            comparator=champion_before,
            comparator_desc=S.describe_config(J, champion_before),
            judge=S.judge_digest(J),
            evaluation=S.evaluation_key(J),
            data_key=ctx["primary_seed"].get(sid),
            design=draft.get("design", ""),
            decision=None,
            grade=None,
            stage=rig.stage(sid),
            reason=reason,
        )
    for text in ctx["lessons"][lessons_before:]:
        kg.lesson(run, k, text)
    if promoted:
        sid = ctx["champion_history"][-1]["evidence"]
        kg.promote(run, k, champion_before, ctx["champion"], ctx["champion_desc"], promoted, f"test:{run}:{sid}")


def run(llm, root="runs/latest", max_ticks=40, n_campaigns=3, rigspec: str | None = None, knowledge: str | None = None):
    """The outer feedback loop. Each campaign: explore (cheap, exploratory) -> PI plans from the
    evidence ledger + lessons -> slices run the preregistered workflow -> champion is promoted only on
    a replicated result -> lessons and variance estimates carry into the next campaign."""
    spec = load_rigspec(rigspec)
    judge = S.load_judge(spec)  # refuse a missing judge before anything is written
    if os.path.exists(root):
        shutil.rmtree(root)
    llm = recording_llm(llm, os.path.join(root, "llm_calls.jsonl"))  # every prompt and reply, for the lab floor
    rig, ctx, transcript = Rig(root, spec), make_ctx(llm, judge), []
    Path(root, "rigspec.json").write_text(json.dumps(spec, indent=1))  # the dashboard reads this copy
    ctx["n_campaigns"] = n_campaigns
    if knowledge:
        open_knowledge(knowledge, spec, judge, ctx, os.path.basename(os.path.abspath(root)))
    for k in range(1, n_campaigns + 1):
        ctx["campaign"] = k
        champion_before, lessons_before = dict(ctx["champion"]), len(ctx["lessons"])
        screen = S.explorer_screen(ctx)
        rig.send(
            rig.seat_for("pi"),
            rig.seat_for("pi"),
            "(explorer) exploratory screen vs champion: " + ", ".join(f"{a} {b:+.2%}" for a, b in screen.items()),
        )
        ctx["replicating"] = S.schedule_replications(rig, ctx)  # before new hypotheses
        rig.queue("human" if k == 1 else rig.seat_for("pi"), rig.seat_for("pi"), "plan", None, {"campaign": k})
        n_before = len(ctx["evidence"])
        for _ in range(max_ticks):
            if not tick(rig, ctx, transcript):
                break
        promoted = S.promote_champion(rig, ctx)
        new = ctx["evidence"][n_before:]
        parked = [
            sid
            for sid, st in rig.db.execute("SELECT id, stage FROM slices WHERE id LIKE ?", (f"C{k}-%",))
            if st == "parked"
        ]
        # Slices that ended the campaign mid-workflow (a seat kept failing): recorded as stalled, never lost.
        stalled = [
            sid
            for sid, st in rig.db.execute("SELECT id, stage FROM slices WHERE id LIKE ?", (f"C{k}-%",))
            if st not in ("written", "parked") and not any(e["slice"] == sid for e in new)
        ]
        ctx["campaigns"].append(
            dict(
                campaign=k,
                screen=screen,
                tested=[e["key"] for e in new],
                decisions=[(e["key"], e["decision"], e["grade"]) for e in new],
                parked=parked,
                stalled=stalled,
                promoted=promoted,
                champion_after=ctx["champion_desc"],
            )
        )
        record_campaign(rig, ctx, k, champion_before, screen, new, parked + stalled, lessons_before, promoted)
        write_ledger(root, ctx)  # the dashboard reads this live
        if not new and not parked:
            break  # PI chose nothing worth testing: the loop converged
    msgs = rig.inbox(rig.seat_for("pi"))
    if msgs:
        S.pi_read(rig, rig.seat_for("pi"), msgs, ctx)
    Path(root, "BOARD.md").write_text(board(rig))
    Path(root, "transcript.json").write_text(json.dumps(transcript, indent=1))
    write_ledger(root, ctx)
    return rig, ctx, transcript


def write_ledger(root, ctx):
    tmp = os.path.join(root, "ledger.json.tmp")
    payload = dict(
        campaigns=ctx["campaigns"],
        evidence=ctx["evidence"],
        lessons=ctx["lessons"],
        champion_history=ctx["champion_history"],
        ledger=ctx["ledger_rows"],
        variance_book={f"{a}|{b}": v for (a, b), v in ctx["variance_book"].items()},
        pi_next=ctx["pi_next"],
    )
    Path(tmp).write_text(json.dumps(payload, indent=1, default=str))
    os.replace(tmp, os.path.join(root, "ledger.json"))
