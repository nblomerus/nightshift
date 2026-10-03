"""Replicator: independent re-implementation from the prereg TEXT only, on fresh data."""

from __future__ import annotations

import hashlib

import numpy as np

from agents.common import ask_json, audit_locked, extract_code, is_code, persona, require_judge
from science import kernel as sk


# ---------------------------------------------------------------------------- replicator
def replicator_replicate(rig, seat, task, ctx):
    sid = task["slice"]
    pre, J = ctx["locked"][sid], ctx["judge"]
    audit_locked(rig, sid, pre, seat, "replication")
    judge = require_judge(rig, seat, sid, pre, "not_replicated", {"same_digest": pre.verify()}, J)
    key0 = (rig.read_proof(sid, "prereg_draft.json") or {}).get("treatment_key", "")
    if is_code(key0):
        return replicate_code(rig, seat, task, ctx, pre, J, judge, key0)
    menu = "\n".join(f"- {k}: {v[0]}" for k, v in J.MENU.items())
    out = ask_json(
        ctx["llm"],
        rig.spec["seats"][seat],
        persona(rig, seat, "You have NOT seen the original code, genome or results."),
        f"Reimplement this preregistered treatment from its TEXT alone.\nStatement: {pre.statement}\n"
        f"Comparator: {ctx['champion_desc']}\nWhich implementation matches the statement?\n{menu}\n"
        'Reply JSON: {"key": "...", "reasoning": "..."}',
    )
    key = out.get("key")
    genome = dict(ctx["champion"], **J.MENU[key][1]) if key in J.MENU else None
    same_treatment = genome == pre.treatment
    seed = task["payload"].get("seed", ctx["replication_seed"][sid])
    attempts = rig.read_proof(sid, "replications.json") or []
    used = {ctx["primary_seed"][sid]} | {a["seed"] for a in attempts}
    rng = np.random.default_rng(2)
    if genome is None:
        dec = "inconclusive"
    else:
        d = pre.design["name"]
        t, c = J.evaluate(genome, d, seed, ctx["cache"]), J.evaluate(pre.comparator, d, seed, ctx["cache"])
        est = sk.paired_effect(t["abs_err"], c["abs_err"], pre.alpha, pre.n_boot, rng)
        dec = sk.decide(est, pre.sesoi, pre.min_effect)
    rep = dict(
        reimplemented_as=key,
        same_treatment=same_treatment,
        seed=seed,
        decision=dec,
        reasoning=out.get("reasoning"),
        judge_digest=judge,
    )
    return finish(rig, seat, sid, ctx, pre, judge, rep, seed, used, attempts, dec, same_treatment)


def replicate_code(rig, seat, task, ctx, pre, J, judge, key):
    """A code idea is replicated by NEW code, written from the prereg text alone, run on fresh data. It counts only if
    that code passes the judge's checks and the decision agrees."""
    sid = task["slice"]
    reply = ctx["llm"](
        "Reimplement this preregistered change as code from its TEXT alone. You have NOT seen the original code.\n"
        f"Change: {ctx['ideas'][key]['idea'] if key in ctx['ideas'] else key}\nStatement: {pre.statement}\n\n"
        f"Contract:\n{J.CODE_CONTRACT}\nReply with the complete source in ONE ```python fenced block, nothing else.",
        system=persona(rig, seat, "You have NOT seen the original code, genome or results."),
        tier=rig.spec["seats"][seat]["tier"],
    )
    source = extract_code(reply)
    check = J.check_code(source) if source else dict(ok=False, error="no ```python block in the reply")
    seed = task["payload"].get("seed", ctx["replication_seed"][sid])
    attempts = rig.read_proof(sid, "replications.json") or []
    used = {ctx["primary_seed"][sid]} | {a["seed"] for a in attempts}
    dec = "inconclusive"
    if check["ok"]:
        mine = dict(name=ctx["ideas"].get(key, {}).get("name", key), source=source)
        genome = dict(pre.comparator, code=list(pre.comparator.get("code") or []) + [mine])
        d = pre.design["name"]
        t, c = J.evaluate(genome, d, seed, ctx["cache"]), J.evaluate(pre.comparator, d, seed, ctx["cache"])
        est = sk.paired_effect(t["abs_err"], c["abs_err"], pre.alpha, pre.n_boot, np.random.default_rng(2))
        dec = sk.decide(est, pre.sesoi, pre.min_effect)
    rep = dict(
        reimplemented_as="independent code",
        code_sha=hashlib.sha256((source or "").encode()).hexdigest(),
        code_check=check,
        same_treatment=bool(check["ok"]),  # an independent implementation of the same idea that passed the checks
        seed=seed,
        decision=dec,
        judge_digest=judge,
    )
    rig.proof(sid, "replication_code.json", dict(source=source, sha=rep["code_sha"]))
    return finish(rig, seat, sid, ctx, pre, judge, rep, seed, used, attempts, dec, rep["same_treatment"])


def finish(rig, seat, sid, ctx, pre, judge, rep, seed, used, attempts, dec, same_treatment):
    rig.proof(sid, "replication.json", rep)
    rig.proof(sid, "replications.json", attempts + [dict(rep, attempt=len(attempts) + 1, campaign=ctx["campaign"])])
    to = "replicated" if (dec == "supported" and same_treatment) else "not_replicated"
    rig.advance(
        seat,
        sid,
        to,
        checks={
            "independent_seat": seat != rig.seat_for("experimenter"),
            "same_digest": pre.verify(),
            "fresh_data": seed not in used,
            "judge_unchanged": judge == pre.judge_digest,
        },
        note=f"{dec}; reimplementation {'matched' if same_treatment else 'DIFFERED'}",
    )
    rig.queue(seat, rig.seat_for("writer"), "write", sid, {})
    return rep
