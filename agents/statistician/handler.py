"""Statistician (code, no LLM): power/assurance, leak canary, controls, lock, decision, champion promotion."""

from __future__ import annotations

import contextlib

import numpy as np
from scipy.stats import norm

from agents.common import (
    REPLICATION_CAP,
    audit_locked,
    describe_config,
    judge_digest,
    require_judge,
    slice_grade,
)
from science import kernel as sk
from state.rig import GuardError


def promote_champion(rig, ctx):
    """The ONLY way the champion changes: a grade-A replicated result from THIS campaign, tested against
    the CURRENT champion. If several replicate, promote the largest; the others must be re-tested on the
    new champion (interactions are not assumed away)."""
    wins = [
        e
        for e in ctx["evidence"]
        if e["campaign"] == ctx["campaign"]
        and e["grade"].startswith("A: replicated")
        and e["champion"] == ctx["champion_desc"]
    ]
    if not wins:
        return None
    best = max(wins, key=lambda e: e["point"])
    before = ctx["champion_desc"]
    ctx["champion"] = dict(ctx["champion"], **ctx["judge"].MENU[best["key"]][1])
    ctx["champion_desc"] = describe_config(ctx["judge"], ctx["champion"])
    ctx["champion_history"].append(
        dict(
            campaign=ctx["campaign"], promoted=best["key"], evidence=best["slice"], from_=before, to=ctx["champion_desc"]
        )
    )
    for e in wins:
        if e is not best:
            ctx["lessons"].append(f"{e['key']} replicated on the old champion but must be re-tested on the new one")
    return best["key"]


def replication_checks(rig, sid, ctx):
    """Guard evidence for queueing another replication of a locked prereg, read from the proof files."""
    return {
        "grade_b_supported": slice_grade(rig, sid).startswith("B: supported"),
        "tested_on_current_champion": ctx["locked"][sid].comparator == ctx["champion"],
        "under_replication_cap": len(rig.read_proof(sid, "replications.json") or []) < REPLICATION_CAP,
    }


def schedule_replications(rig, ctx):
    """Campaign start, before new hypotheses: every supported grade-B result tested against the current
    champion gets another replication of the SAME locked prereg on a fresh seed. The rig refuses (and logs)
    a slice that has used up its attempts."""
    seat, queued = rig.seat_for("statistician"), []
    latest = {e["slice"]: e for e in ctx["evidence"]}
    for sid, e in latest.items():
        if not e["grade"].startswith("B: supported") or e["champion"] != ctx["champion_desc"]:
            continue
        if rig.stage(sid) != "written":
            continue
        n = len(rig.read_proof(sid, "replications.json") or [])
        keys = ctx["judge"].data_keys("extra_replication", ctx["campaign"], len(queued))
        if not keys:  # finite real data: no fresh months for another replication
            rig.log(sid, seat, "grade B, but the judge has no fresh data for another replication")
            continue
        seed = keys[0]
        try:
            rig.advance(
                seat,
                sid,
                "replication_queued",
                checks=replication_checks(rig, sid, ctx),
                note=f"attempt {n + 1}, seed {seed}",
            )
        except GuardError:
            continue  # the rig logged the refusal
        rig.queue(seat, rig.seat_for("replicator"), "replicate", sid, dict(seed=seed, attempt=n + 1))
        queued.append(e["key"])
    return queued


# ---------------------------------------------------------------------------- statistician (code only)
def statistician_power_controls(rig, seat, task, ctx):
    sid = task["slice"]
    pre = rig.read_proof(sid, "prereg_draft.json")
    rng, cache, J = np.random.default_rng(0), ctx["cache"], ctx["judge"]
    ses, pts = [], []
    treat = dict(ctx["champion"], **J.MENU[pre["treatment_key"]][1])
    pilot = J.data_keys("pilot")
    for s in pilot:
        # pilot panels are never reused for confirmation; they only plan the design
        e = sk.paired_effect(
            J.evaluate(treat, pre["design"], s, cache)["abs_err"],
            J.evaluate(ctx["champion"], pre["design"], s, cache)["abs_err"],
            0.05,
            500,
            rng,
        )
        ses.append((e["hi"] - e["lo"]) / (2 * 1.96))
        pts.append(e["point"])
    se, mu = float(np.mean(ses)), float(np.mean(pts))
    ctx["variance_book"][(pre["treatment_key"], pre["design"])] = dict(se=se, pilot_effect=mu)
    alpha = pre["alpha"]
    z = norm.ppf(1 - alpha / 2)
    power = float(norm.cdf((pre["target_effect"] - max(pre["sesoi"], z * se)) / se))  # reported only
    d_sup = norm.cdf((mu - max(pre["sesoi"], z * se)) / se)
    d_harm = norm.cdf((-mu - z * se) / se)
    w = pre["sesoi"] - z * se
    d_null = max(0.0, norm.cdf((w - mu) / se) - norm.cdf((-w - mu) / se)) if w > 0 else 0.0
    p_decisive = float(min(1.0, d_sup + d_harm + d_null))
    leak = J.leak_canary(treat, pre["design"], pilot[0], cache)

    def mk(t, c=J.BASELINE):
        return sk.Preregistration(
            hid="control",
            statement="control",
            estimand="rel WAPE reduction",
            treatment=t,
            comparator=c,
            primary_metric="WAPE",
            unit="series",
            sesoi=pre["sesoi"],
            alpha=alpha,
            n_boot=500,
        ).lock()

    def run(g):
        return J.evaluate(g, pre["design"], pilot[0], cache)

    pos_comparator = getattr(J, "POSITIVE_CONTROL_COMPARATOR", J.BASELINE)  # optional in the judge contract
    pos = sk.run_test(mk(J.POSITIVE_CONTROL, pos_comparator), run, rng)["decision"]
    neg = sk.run_test(mk(J.PLACEBO), run, rng)["decision"]
    admissible = pos == "supported" and neg != "supported" and not leak
    # judge-specific guards the rigspec requires before lock (e.g. a censoring mask for latent-demand models)
    design_ok = J.design_checks(treat, pre["design"], J.data_keys("primary")[0]) if hasattr(J, "design_checks") else {}
    rep = dict(
        design=pre["design"],
        alpha=alpha,
        pilot_se=se,
        pilot_effect=mu,
        p_decisive=p_decisive,
        power_at_target=power,
        target_effect=pre["target_effect"],
        leak_canary=leak,
        positive_control=pos,
        negative_control=neg,
        admissible=admissible,
        **design_ok,
    )
    rig.proof(sid, f"power_controls_r{pre['revision']}.json", rep)
    if not all(design_ok.values()):
        failed = [k for k, v in design_ok.items() if not v]
        with contextlib.suppress(GuardError):  # refusal is logged by the rig
            rig.advance(seat, sid, "controls_passed", checks=design_ok)
        # every design scores the same kind of months, so no larger design fixes this
        rig.advance(seat, sid, "parked", checks={"no_larger_design": True}, note=f"design check failed: {failed}")
        rig.send(seat, rig.seat_for("pi"), f"{sid}: parked, the design fails {failed}.", sid)
        return rep
    if leak:
        with contextlib.suppress(GuardError):  # refusal is logged by the rig; route back
            rig.advance(
                seat, sid, "controls_passed", checks={"p_decisive>=0.8": p_decisive >= 0.8, "controls_admissible": False}
            )
        rig.advance(seat, sid, "parked", checks={"no_larger_design": True}, note="leak canary fired")
        rig.send(
            seat,
            rig.seat_for("pi"),
            f"{sid}: the treatment's predictions change when future demand is hidden "
            "(leak canary). Parked; fix the feature before any confirmatory test.",
            sid,
        )
        return rep
    if p_decisive < 0.8 or not admissible:
        with contextlib.suppress(GuardError):  # refusal is logged by the rig; route back
            rig.advance(
                seat,
                sid,
                "controls_passed",
                checks={"p_decisive>=0.8": p_decisive >= 0.8, "controls_admissible": admissible},
            )
        order = list(J.DESIGNS)
        larger = order[order.index(pre["design"]) + 1 :]
        base = (
            f"Design {pre['design']}: probability of a decisive result {p_decisive:.2f} at the pilot effect "
            f"{mu:+.2%} (pilot SE {se:.2%}, alpha {alpha:.3f}); power at the {pre['target_effect']:.1%} target "
            f"{power:.2f}. Leak canary clean. Controls: positive={pos}, placebo={neg}."
        )
        if larger:
            msg = base + f" Use the larger design {larger[0]}; I cannot lock this one."
            rig.send(seat, rig.seat_for("methodologist"), msg, sid)
            rig.advance(seat, sid, "prereg_draft", note="underpowered")
            rig.queue(
                seat, rig.seat_for("methodologist"), "draft_prereg", sid, dict(key=pre["treatment_key"], feedback=msg)
            )
        else:
            rig.advance(seat, sid, "parked", checks={"no_larger_design": True}, note="underpowered at largest design")
            rig.send(
                seat,
                rig.seat_for("pi"),
                base + " No larger design exists: the lab cannot answer this with the "
                "available data at the fixed standards. Parked.",
                sid,
            )
        return rep
    rig.advance(
        seat,
        sid,
        "controls_passed",
        checks={"p_decisive>=0.8": True, "controls_admissible": True, **design_ok},
        note=f"P(decisive) {p_decisive:.2f} at pilot effect {mu:+.2%}; leak canary clean",
    )
    d = J.DESIGNS[pre["design"]]
    locked = sk.Preregistration(
        hid=pre["hid"],
        statement=pre["statement"],
        estimand=f"relative reduction in {J.TARGET}, two-way bootstrap",
        treatment=dict(ctx["champion"], **J.MENU[pre["treatment_key"]][1]),
        comparator=dict(ctx["champion"]),
        primary_metric="WAPE",
        unit="series x origin",
        sesoi=pre["sesoi"],
        alpha=alpha,
        n_boot=1000,
        design=dict(name=pre["design"], T=d["T"], origins=d["origins"], bootstrap="two_way"),
        kills_if=pre["kills_if"],
        judge_digest=judge_digest(J),
    ).lock()
    rig.proof(sid, "prereg_locked.json", dict(body=locked._body(), digest=locked.digest, locked_at=locked.locked_at))
    ctx["locked"][sid] = locked
    rig.advance(seat, sid, "locked", checks={"prereg_digest": locked.verify()}, note=locked.digest[:12])
    rig.queue(seat, rig.seat_for("experimenter"), "run_experiment", sid, dict(digest=locked.digest))
    return rep


def statistician_analyse(rig, seat, task, ctx):
    sid = task["slice"]
    pre, res = ctx["locked"][sid], rig.read_proof(sid, "run_result.json")
    audit_locked(rig, sid, pre, seat, "analysis")
    judge = require_judge(rig, seat, sid, pre, "analysed", {"kernel_decision": False}, ctx["judge"])
    rng = np.random.default_rng(1)
    alpha = pre.alpha  # reserved at lock (campaign Bonferroni)
    est = sk.paired_effect(np.array(res["err_t"]), np.array(res["err_c"]), alpha, pre.n_boot, rng)
    dec = sk.decide(est, pre.sesoi)
    ctx["ledger_rows"].append(dict(slice=sid, digest=pre.digest[:12], alpha=alpha, decision=dec, **est))
    out = dict(alpha=alpha, **est, decision=dec, sesoi=pre.sesoi, digest=pre.digest, judge_digest=judge)
    rig.proof(sid, "decision.json", out)
    rig.advance(
        seat,
        sid,
        "analysed",
        checks={"kernel_decision": True, "judge_unchanged": judge == pre.judge_digest},
        note=f"{dec} (alpha {alpha:.4f})",
    )
    nxt = ("replicator", "replicate") if dec == "supported" else ("writer", "write")
    rig.queue(seat, rig.seat_for(nxt[0]), nxt[1], sid, dict(decision=dec))
    return out
