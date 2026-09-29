"""Experimenter: checks the prereg is implementable exactly, then runs it under the frozen judge."""

from __future__ import annotations

import hashlib
import json

from agents.common import (
    ask_json,
    audit_locked,
    change_desc,
    extract_code,
    is_code,
    persona,
    require_judge,
    statement_for,
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


def review_code(rig, ctx, idea, statement, source):
    """The critic reads the code against the idea before lock (the LLM half of the implementation check)."""
    critic = rig.seat_for("critic")
    return ask_json(
        ctx["llm"],
        rig.spec["seats"][critic],
        persona(rig, critic, "You review code BEFORE any confirmatory data exists."),
        f"The preregistered change: {idea}\n\nPrereg statement:\n{statement}\n\nThe experimenter's code:\n```python\n{source}```\n"
        "It will run under this contract:\n" + ctx["judge"].CODE_CONTRACT + "\n"
        "Does the code implement THIS idea, and only it (no extra features, no tuning to outcomes, no hard-coded "
        "dates, stations or results)? The sandbox and the judge's checks already ensure it runs, is deterministic and "
        "sees only point-in-time data; do not re-check those. Object only to a real mismatch with the idea. "
        'Reply JSON: {"verdict": "approve" or "object", "message": "to the experimenter"}',
    )


def write_code(rig, seat, sid, key, pre, ctx, attempts=3):
    """Implement a seat-proposed idea as code: write it, pass the judge's deterministic checks, pass the critic's
    review. Up to `attempts` tries, each told why the last one failed."""
    J, idea = ctx["judge"], change_desc(ctx, key)
    feedback = ""
    for attempt in range(attempts):
        reply = ctx["llm"](
            f"Implement this preregistered change as code.\nChange: {idea}\n\nPrereg statement:\n{pre['statement']}\n\n"
            f"Contract:\n{J.CODE_CONTRACT}\n"
            + (f"\nYour previous attempt was rejected: {feedback}\n" if feedback else "")
            + "\nReply with the complete source in ONE ```python fenced block, nothing else.",
            system=persona(rig, seat),
            tier=rig.spec["seats"][seat]["tier"],
        )
        source = extract_code(reply)
        if not source:
            feedback = "no ```python block in your reply"
            continue
        sha = hashlib.sha256(source.encode()).hexdigest()
        check = J.check_code(source)
        rig.proof(sid, f"code_check_a{attempt}.json", dict(check, sha=sha))
        if not check["ok"]:
            feedback = f"the judge's checks failed: {check['error']}"
            continue
        review = review_code(rig, ctx, idea, pre["statement"], source)
        rig.proof(sid, f"code_review_a{attempt}.json", review)
        if review.get("verdict") != "approve":
            feedback = f"the critic objected: {review.get('message', '')}"
            continue
        ctx["code"][sid] = dict(name=ctx["ideas"][key]["name"], source=source, sha=sha)
        rig.proof(sid, "treatment_code.json", ctx["code"][sid])
        return dict(implementable_exactly=True, code_checked=True, mismatch="", message="", sha=sha, attempts=attempt + 1)
    return dict(
        implementable_exactly=False,
        code_checked=False,
        mismatch=feedback,
        message=f"Could not implement the idea: {feedback}",
    )


def experimenter_check(rig, seat, task, ctx):
    """Before lock: can the prereg be implemented EXACTLY? A menu change by the frozen judge's config; a new idea by
    code the experimenter writes, which must pass the judge's checks and the critic's review."""
    sid = task["slice"]
    pre, J = rig.read_proof(sid, "prereg_draft.json"), ctx["judge"]
    key = pre["treatment_key"]
    if is_code(key):
        out = write_code(rig, seat, sid, key, pre, ctx)
    else:
        impl = J.MENU[key][0]
        out = ask_json(
            ctx["llm"],
            rig.spec["seats"][seat],
            persona(rig, seat),
            f"Draft prereg statement:\n{pre['statement']}\n\nThe frozen judge will run exactly this treatment: "
            f"'{impl}' (naive inverse transforms, no bias corrections), against {ctx['champion_desc']}.\n"
            f"Authoritative machine config, locked together with the statement: treatment="
            f"{json.dumps(dict(ctx['champion'], **J.MENU[key][1]))}, comparator={json.dumps(ctx['champion'])}.\n"
            f"The treatment differs from the comparator ONLY in these config fields: {json.dumps(J.MENU[key][1])}. "
            "Every other field is identical in both arms and unrelated to this treatment; do not map words in the "
            "statement onto other field names (e.g. 'adjacent-day' holiday indicators are part of the holidays field).\n"
            "Question: does the statement CONTRADICT this config, or claim a component the config does not "
            "contain (e.g. a correction, extra feature, different comparator)? Missing detail is NOT a mismatch "
            "— the config supplies it. "
            'Reply JSON: {"implementable_exactly": true/false, "mismatch": "...", "message": "to the methodologist"}',
        )
        out["code_checked"] = True  # no code: nothing to check
    # deterministic: the statement must be the one generated from the CURRENT champion config and standards
    expected = statement_for(ctx, key, rig.spec["decision_standards"], pre["alpha"])
    out["statement_from_config"] = pre["statement"] == expected
    if not out["statement_from_config"]:
        out["mismatch"] = "statement is not the one generated from the current champion config; regenerate it"
    rig.proof(sid, f"implementation_check_r{pre['revision']}.json", out)
    if out.get("implementable_exactly") is True and out["statement_from_config"] and out["code_checked"]:
        rig.advance(
            seat,
            sid,
            "implementation_checked",
            checks={"implementable_exactly": True, "statement_from_config": True, "code_checked": True},
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
            dict(key=key, feedback=out.get("message") or out.get("mismatch", "")),
        )
    return out
