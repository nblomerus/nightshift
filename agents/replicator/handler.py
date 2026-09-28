"""Replicator: independent re-implementation from the prereg TEXT only, on fresh data."""

from __future__ import annotations

import numpy as np

from agents.common import ask_json, audit_locked, persona, require_judge
from science import kernel as sk


# ---------------------------------------------------------------------------- replicator
def replicator_replicate(rig, seat, task, ctx):
    sid = task["slice"]
    pre, J = ctx["locked"][sid], ctx["judge"]
    audit_locked(rig, sid, pre, seat, "replication")
    judge = require_judge(rig, seat, sid, pre, "not_replicated", {"same_digest": pre.verify()}, J)
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
        dec = sk.decide(est, pre.sesoi)
    rep = dict(
        reimplemented_as=key,
        same_treatment=same_treatment,
        seed=seed,
        decision=dec,
        reasoning=out.get("reasoning"),
        judge_digest=judge,
    )
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
