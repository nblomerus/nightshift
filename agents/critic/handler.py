"""Critic: design review BEFORE data (registered-report stage 1)."""

from __future__ import annotations

import json

from agents.common import DESIGNS, ask_json, persona


# ---------------------------------------------------------------------------- critic
def critic_review(rig, seat, task, ctx):
    sid = task["slice"]
    pre = rig.read_proof(sid, "prereg_draft.json")
    final_round = pre["revision"] >= 1
    out = ask_json(
        ctx["llm"],
        rig.spec["seats"][seat],
        persona(rig, seat, "You review designs BEFORE any data exists. You never see results."),
        f"Preregistration draft (comparator: {ctx['champion_desc']}; designs: "
        f"{json.dumps({k: v['desc'] for k, v in DESIGNS.items()})}):\n{json.dumps(pre, indent=1)}\n\n"
        "Check: is the comparator explicit; is the statement falsifiable and does it match the estimand; is the "
        "SESOI justified for a demand-planning decision; is kills_if concrete; any leakage or confound risk "
        "(features must be known at forecast time)? Object only to BLOCKING problems."
        + (" This is the final round: approve unless a blocking problem remains." if final_round else "")
        + " The SESOI, target effect and alpha are fixed lab standards; do not object to them. A request to change "
        "the TREATMENT itself (e.g. add a correction) is not a revision: put it in new_hypothesis_for_pi instead."
        + '\nReply JSON: {"verdict": "approve" or "object", "blocking": ["..."], "message": "to the methodologist", '
        '"new_hypothesis_for_pi": null or "..."}',
    )
    rig.proof(sid, f"design_review_r{pre['revision']}.json", out)
    if out.get("new_hypothesis_for_pi"):
        rig.send(seat, rig.seat_for("pi"), f"Suggested new hypothesis: {out['new_hypothesis_for_pi']}", sid)
    if out["verdict"] == "object" and not final_round:
        rig.send(seat, rig.seat_for("methodologist"), out["message"], sid)
        rig.advance(seat, sid, "prereg_draft", note="design objections: " + "; ".join(out.get("blocking", []))[:150])
        rig.queue(
            seat,
            rig.seat_for("methodologist"),
            "draft_prereg",
            sid,
            dict(key=pre["treatment_key"], feedback=out["message"]),
        )
    else:
        rig.advance(seat, sid, "approved_design", note=out.get("message", "")[:120])
        rig.queue(seat, rig.seat_for("experimenter"), "check_implementation", sid, {})
    return out
