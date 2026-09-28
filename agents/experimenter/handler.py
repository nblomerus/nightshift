"""Experimenter: checks the prereg is implementable exactly, then runs it under the frozen judge."""

from __future__ import annotations

import json

from agents.common import (
    ask_json,
    audit_locked,
    persona,
    prereg_statement,
    require_judge,
)


# ---------------------------------------------------------------------------- experimenter
def experimenter_run(rig, seat, task, ctx):
    sid = task["slice"]
    pre, J = ctx["locked"][sid], ctx["judge"]
    audit_locked(rig, sid, pre, seat, "run")
    judge = require_judge(rig, seat, sid, pre, "run", {"digest_matches": pre.verify(), "judge_result": False}, J)
    for m in rig.inbox(seat):
        rig.note(seat, f"answer from {m['frm']}: {m['body'][:200]}")
    out = dict(run_note="ran treatment and comparator under the frozen judge as locked")
    seed = ctx["primary_seed"][sid]
    d = pre.design["name"]
    t, c = J.evaluate(pre.treatment, d, seed, ctx["cache"]), J.evaluate(pre.comparator, d, seed, ctx["cache"])
    rig.proof(
        sid,
        "run_result.json",
        dict(
            digest=pre.digest,
            judge_digest=judge,
            seed=seed,
            design=d,
            run_note=out.get("run_note"),
            err_t=t["abs_err"].tolist(),
            err_c=c["abs_err"].tolist(),
        ),
    )
    rig.advance(
        seat,
        sid,
        "run",
        checks={"digest_matches": pre.verify(), "judge_result": True, "judge_unchanged": judge == pre.judge_digest},
    )
    rig.queue(seat, rig.seat_for("statistician"), "analyse", sid, {})
    return out


def experimenter_check(rig, seat, task, ctx):
    """Before lock: can the prereg be implemented EXACTLY by the frozen judge's treatment?"""
    sid = task["slice"]
    pre, J = rig.read_proof(sid, "prereg_draft.json"), ctx["judge"]
    impl = J.MENU[pre["treatment_key"]][0]
    out = ask_json(
        ctx["llm"],
        rig.spec["seats"][seat],
        persona(rig, seat),
        f"Draft prereg statement:\n{pre['statement']}\n\nThe frozen judge will run exactly this treatment: "
        f"'{impl}' (naive inverse transforms, no bias corrections), against {ctx['champion_desc']}.\n"
        f"Authoritative machine config, locked together with the statement: treatment="
        f"{json.dumps(dict(ctx['champion'], **J.MENU[pre['treatment_key']][1]))}, comparator={json.dumps(ctx['champion'])}.\n"
        "Question: does the statement CONTRADICT this config, or claim a component the config does not "
        "contain (e.g. a correction, extra feature, different comparator)? Missing detail is NOT a mismatch "
        "— the config supplies it. "
        'Reply JSON: {"implementable_exactly": true/false, "mismatch": "...", "message": "to the methodologist"}',
    )
    # deterministic: the statement must be the one generated from the CURRENT champion config and standards
    expected = prereg_statement(J, ctx["champion"], pre["treatment_key"], rig.spec["decision_standards"], pre["alpha"])
    out["statement_from_config"] = pre["statement"] == expected
    if not out["statement_from_config"]:
        out["mismatch"] = "statement is not the one generated from the current champion config; regenerate it"
    rig.proof(sid, f"implementation_check_r{pre['revision']}.json", out)
    if out.get("implementable_exactly") is True and out["statement_from_config"]:
        rig.advance(
            seat,
            sid,
            "implementation_checked",
            checks={"implementable_exactly": True, "statement_from_config": True},
        )
        rig.queue(seat, rig.seat_for("statistician"), "power_controls", sid, {})
    else:
        rig.send(seat, rig.seat_for("methodologist"), out.get("message") or out.get("mismatch", ""), sid)
        rig.advance(seat, sid, "prereg_draft", note="not implementable as written: " + str(out.get("mismatch"))[:100])
        rig.queue(
            seat,
            rig.seat_for("methodologist"),
            "draft_prereg",
            sid,
            dict(key=pre["treatment_key"], feedback=out.get("message") or out.get("mismatch", "")),
        )
    return out
