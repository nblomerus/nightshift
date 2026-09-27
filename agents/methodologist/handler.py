"""Methodologist: drafts preregistrations; answers questions about them."""

from __future__ import annotations

import json

from agents.common import (
    DESIGNS,
    LLM_PREREG_KEYS,
    MENU,
    PREREG_KEYS,
    REVISION_CAP,
    ask_json,
    persona,
    prereg_statement,
)


def methodologist_draft(rig, seat, task, ctx):
    sid, key = task["slice"], task["payload"]["key"]
    prev = rig.read_proof(sid, "prereg_draft.json")
    feedback = task["payload"].get("feedback", "")
    designs = "\n".join(f"- {k}: {v['desc']}" for k, v in DESIGNS.items())
    std = rig.spec["decision_standards"]
    if prev and prev.get("revision", 0) + 1 >= REVISION_CAP:
        rig.advance(seat, sid, "parked", checks={"revision_cap_reached": True}, note="revision cap reached")
        rig.send(seat, rig.seat_for("pi"), f"{sid} parked after {REVISION_CAP} prereg revisions: {feedback[:300]}", sid)
        return dict(parked=True)
    out = ask_json(
        ctx["llm"],
        rig.spec["seats"][seat],
        persona(rig, seat),
        f"Draft a preregistration for this change to {ctx['champion_desc']}.\n"
        f"The frozen judge implements EXACTLY this treatment and nothing else: '{MENU[key][0]}'. "
        f"Its machine config (authoritative, locked with your prereg): treatment="
        f"{json.dumps(dict(ctx['champion'], **MENU[key][1]))}, comparator={json.dumps(ctx['champion'])} "
        "(naive inverse transforms, no bias corrections, no extra tuning). The statement naming both arms and "
        "the decision rule is generated from this config; if you believe a variant is better, say so in "
        "rationale — it would be a separate hypothesis.\n"
        f"Decision standards are FIXED by the PI and not yours to set: SESOI {std['sesoi']:.1%} relative "
        f"WAPE reduction; target effect for 80% power {std['target_effect']:.1%}; alpha per test "
        f"{ctx['alpha_per_test']:.3f}.\n"
        "Estimand: relative reduction in WAPE of the next-4-week unit sum, treatment vs comparator, "
        "resampling series AND rolling origins (two-way bootstrap).\n"
        f"Available designs:\n{designs}\n"
        + (f"\nPrevious draft:\n{json.dumps(prev)}\nFeedback to address:\n{feedback}\n" if prev else "")
        + "\nFields: design ('A' or 'B'), kills_if (result that would drop the idea), rationale. "
        "Reply with ONE JSON object with exactly these keys.",
    )
    pre = {k: out.get(k) for k in LLM_PREREG_KEYS}
    pre["hid"] = f"H-{key}"
    pre["statement"] = prereg_statement(ctx["champion"], key, std, ctx["alpha_per_test"])
    pre["design"] = pre["design"] if pre["design"] in DESIGNS else "A"
    pre["sesoi"], pre["target_effect"], pre["alpha"] = std["sesoi"], std["target_effect"], ctx["alpha_per_test"]
    pre["treatment_key"], pre["revision"] = key, (prev or {}).get("revision", -1) + 1
    rig.proof(sid, "prereg_draft.json", pre)
    fields_ok = all(pre.get(k) not in (None, "") for k in PREREG_KEYS)
    if rig.stage(sid) == "hypothesis":
        rig.advance(seat, sid, "prereg_draft", checks=dict(prereg_fields=fields_ok))
    rig.advance(seat, sid, "design_review", note=f"rev {pre['revision']}, design {pre['design']}")
    rig.queue(seat, rig.seat_for("critic"), "review_design", sid, dict(revision=pre["revision"]))
    return pre


def methodologist_answer(rig, seat, msgs, ctx):
    for m in msgs:
        pre = rig.read_proof(m["slice"], "prereg_draft.json") if m["slice"] else None
        out = ask_json(
            ctx["llm"],
            rig.spec["seats"][seat],
            persona(rig, seat),
            f"{m['frm']} asks about slice {m['slice']}:\n{m['body']}\n\nThe prereg:\n{json.dumps(pre)}\n"
            "Answer from the prereg only; if the prereg is silent, say so (that is a deviation risk). "
            'Reply JSON: {"answer": "..."}',
        )
        rig.send(seat, m["frm"], out["answer"], m["slice"], reply_to=m["id"])
