"""Writer: writes the finding; cannot change the decision or the grade."""

from __future__ import annotations

import json
from pathlib import Path

from agents.common import MENU, ask_json, persona
from science import kernel as sk


# ---------------------------------------------------------------------------- writer
def writer_write(rig, seat, task, ctx):
    sid = task["slice"]
    pre, dec = ctx["locked"][sid], rig.read_proof(sid, "decision.json")
    repl = rig.read_proof(sid, "replication.json")
    grade = sk.evidence_grade(
        dec["decision"],
        (repl or {}).get("decision") == "supported" and (repl or {}).get("same_treatment"),
        deviations=0,
        controls_ok=True,
    )
    out = ask_json(
        ctx["llm"],
        rig.spec["seats"][seat],
        persona(rig, seat, "You may not change or soften the decision or the grade."),
        f"Write the finding for slice {sid}.\nPrereg statement: {pre.statement}\n"
        f"Treatment actually run by the judge (describe THIS, nothing more): {MENU[rig.read_proof(sid, 'prereg_draft.json')['treatment_key']][0]}\nSESOI {pre.sesoi:.1%}; design "
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
