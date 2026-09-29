"""Writer: writes the finding; cannot change the decision or the grade."""

from __future__ import annotations

import json
from pathlib import Path

from agents.common import ask_json, audit_locked, change_desc, persona, slice_grade


# ---------------------------------------------------------------------------- writer
def writer_write(rig, seat, task, ctx):
    sid = task["slice"]
    pre, dec = ctx["locked"][sid], rig.read_proof(sid, "decision.json")
    repl = rig.read_proof(sid, "replication.json")
    audit_locked(rig, sid, pre, seat, "write-up")
    grade = slice_grade(rig, sid)
    out = ask_json(
        ctx["llm"],
        rig.spec["seats"][seat],
        persona(rig, seat, "You may not change or soften the decision or the grade."),
        f"Write the finding for slice {sid}.\nPrereg statement: {pre.statement}\n"
        f"Treatment actually run by the judge (describe THIS, nothing more): {change_desc(ctx, rig.read_proof(sid, 'prereg_draft.json')['treatment_key'])}\nSESOI {pre.sesoi:.1%}; design "
        f"{pre.design['name']} ({len(pre.design['origins'])} origins)\nKernel decision: {dec['decision']} — estimate "
        f"{dec['point']:.2%}, CI [{dec['lo']:.2%}, {dec['hi']:.2%}] at alpha {dec['alpha']:.4f}\n"
        f"Replication: {json.dumps(repl) if repl else 'not attempted (decision was not supported)'}\n"
        f"Evidence grade: {grade}\n"
        'Reply JSON: {"headline": "...", "finding_md": "150-250 words: result, what it means for the planner, limits"}',
    )
    md = f"# {out['headline']}\n\n**Evidence grade:** {grade}\n\n{out['finding_md']}\n"
    Path(f"{rig.slice_dir(sid)}/finding.md").write_text(md)
    ctx["evidence"].append(
        dict(
            campaign=ctx["campaign"],
            slice=sid,
            key=rig.read_proof(sid, "prereg_draft.json")["treatment_key"],
            champion=ctx["champion_desc"],
            design=pre.design["name"],
            decision=dec["decision"],
            point=dec["point"],
            lo=dec["lo"],
            hi=dec["hi"],
            replication=(repl or {}).get("decision"),
            grade=grade,
            headline=out["headline"],
        )
    )
    rig.advance(seat, sid, "written", checks={"decision_not_supported": dec["decision"] != "supported"})
    rig.send(seat, rig.seat_for("pi"), f"{out['headline']} — grade {grade}", sid)
    return dict(grade=grade, headline=out["headline"])
