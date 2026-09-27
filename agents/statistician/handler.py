"""Statistician (code, no LLM): power/assurance, leak canary, controls, lock, decision, champion promotion."""

from __future__ import annotations

import contextlib

import numpy as np
from scipy.stats import norm

from agents.common import DESIGNS, MENU, PILOT_SEEDS, PLACEBO, POSITIVE_CONTROL, evaluate_arm
from judges import forecast as fh
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
    ctx["champion"] = dict(ctx["champion"], **MENU[best["key"]][1])
    ctx["champion_desc"] = before + " + " + MENU[best["key"]][0].lower()
    ctx["champion_history"].append(
        dict(
            campaign=ctx["campaign"], promoted=best["key"], evidence=best["slice"], from_=before, to=ctx["champion_desc"]
        )
    )
    for e in wins:
        if e is not best:
            ctx["lessons"].append(f"{e['key']} replicated on the old champion but must be re-tested on the new one")
    return best["key"]


# ---------------------------------------------------------------------------- statistician (code only)
def statistician_power_controls(rig, seat, task, ctx):
    sid = task["slice"]
    pre = rig.read_proof(sid, "prereg_draft.json")
    rng, cache = np.random.default_rng(0), ctx["cache"]
    ses, pts = [], []
    treat = dict(ctx["champion"], **MENU[pre["treatment_key"]][1])
    for s in PILOT_SEEDS:
        # pilot panels are never reused for confirmation; they only plan the design
        e = sk.paired_effect(
            evaluate_arm(treat, pre["design"], s, cache)["abs_err"],
            evaluate_arm(ctx["champion"], pre["design"], s, cache)["abs_err"],
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
    panel0 = cache.setdefault(
        ("panel", PILOT_SEEDS[0], pre["design"]), fh.make_panel(PILOT_SEEDS[0], T=DESIGNS[pre["design"]]["T"])
    )
    leak = fh.leak_canary(panel0, treat, origin=DESIGNS[pre["design"]]["origins"][0])

    def mk(t):
        return sk.Preregistration(
            hid="control",
            statement="control",
            estimand="rel WAPE reduction",
            treatment=t,
            comparator=fh.BASELINE,
            primary_metric="WAPE",
            unit="series",
            sesoi=pre["sesoi"],
            alpha=alpha,
            n_boot=500,
        ).lock()

    def run(g):
        return evaluate_arm(g, pre["design"], PILOT_SEEDS[0], cache)

    pos = sk.run_test(mk(POSITIVE_CONTROL), run, rng)["decision"]
    neg = sk.run_test(mk(PLACEBO), run, rng)["decision"]
    admissible = pos == "supported" and neg != "supported" and not leak
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
    )
    rig.proof(sid, f"power_controls_r{pre['revision']}.json", rep)
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
        order = list(DESIGNS)
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
        checks={"p_decisive>=0.8": True, "controls_admissible": True},
        note=f"P(decisive) {p_decisive:.2f} at pilot effect {mu:+.2%}; leak canary clean",
    )
    d = DESIGNS[pre["design"]]
    locked = sk.Preregistration(
        hid=pre["hid"],
        statement=pre["statement"],
        estimand="relative WAPE reduction, next-4-week sum, two-way bootstrap",
        treatment=dict(ctx["champion"], **MENU[pre["treatment_key"]][1]),
        comparator=dict(ctx["champion"]),
        primary_metric="WAPE",
        unit="series x origin",
        sesoi=pre["sesoi"],
        alpha=alpha,
        n_boot=1000,
        design=dict(name=pre["design"], T=d["T"], origins=d["origins"], bootstrap="two_way"),
        kills_if=pre["kills_if"],
    ).lock()
    rig.proof(sid, "prereg_locked.json", dict(body=locked._body(), digest=locked.digest, locked_at=locked.locked_at))
    ctx["locked"][sid] = locked
    rig.advance(seat, sid, "locked", checks={"prereg_digest": locked.verify()}, note=locked.digest[:12])
    rig.queue(seat, rig.seat_for("experimenter"), "run_experiment", sid, dict(digest=locked.digest))
    return rep


def statistician_analyse(rig, seat, task, ctx):
    sid = task["slice"]
    pre, res = ctx["locked"][sid], rig.read_proof(sid, "run_result.json")
    rng = np.random.default_rng(1)
    alpha = pre.alpha  # reserved at lock (campaign Bonferroni)
    est = sk.paired_effect(np.array(res["err_t"]), np.array(res["err_c"]), alpha, pre.n_boot, rng)
    dec = sk.decide(est, pre.sesoi)
    ctx["ledger_rows"].append(dict(slice=sid, digest=pre.digest[:12], alpha=alpha, decision=dec, **est))
    out = dict(alpha=alpha, **est, decision=dec, sesoi=pre.sesoi, digest=pre.digest)
    rig.proof(sid, "decision.json", out)
    rig.advance(seat, sid, "analysed", checks={"kernel_decision": True}, note=f"{dec} (alpha {alpha:.4f})")
    nxt = ("replicator", "replicate") if dec == "supported" else ("writer", "write")
    rig.queue(seat, rig.seat_for(nxt[0]), nxt[1], sid, dict(decision=dec))
    return out
