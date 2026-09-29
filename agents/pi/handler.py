"""PI: plans each campaign from the evidence ledger, screen, lessons and messages; reads findings."""

from __future__ import annotations

import re

from agents.common import ask_json, change_desc, evaluation_key, persona


# ---------------------------------------------------------------------------- PI
def pi_plan(rig, seat, task, ctx):
    """Plan campaign k from everything the lab knows: champion, exploratory screen, evidence ledger,
    lessons, critic suggestions. Re-testing an inconclusive change is allowed only as a NEW prereg
    (fresh data, typically a larger design); earlier data are never pooled post hoc."""
    J, kg = ctx["judge"], ctx.get("knowledge")
    menu = {
        k: v
        for k, v in J.MENU.items()
        if not all(ctx["champion"].get(a) == b for a, b in v[1].items()) and k not in ctx["replicating"]
    }
    # Deterministic: a change already decided against this champion, on the same data, under the same judge, is not
    # offered again. Re-running it scores the same numbers under the same rule and can only reproduce the answer.
    unavailable = []
    if kg is not None:
        digest, data_key = evaluation_key(J), J.data_keys("primary", ctx["campaign"], 0)[0]
        unavailable = [
            k for k, v in menu.items() if kg.is_repeat(dict(ctx["champion"], **v[1]), ctx["champion"], digest, data_key)
        ]
        menu = {k: v for k, v in menu.items() if k not in unavailable}
    ev = (
        "\n".join(
            f"- campaign {e['campaign']} {e['key']} on [{e['champion']}] design {e['design']}: "
            f"{e['decision']} {e['point']:+.2%} [{e['lo']:+.2%}, {e['hi']:+.2%}], replication={e['replication']}, "
            f"grade {e['grade']}"
            for e in ctx["evidence"]
        )
        or "(none yet)"
    )
    screen = "\n".join(f"- {k}: {v:+.2%}" for k, v in ctx["screen"].items() if k in menu) or "(nothing left to screen)"
    vb = (
        "\n".join(
            f"- {k} design {d}: pilot SE {v['se']:.2%}, pilot effect {v['pilot_effect']:+.2%}"
            for (k, d), v in ctx["variance_book"].items()
        )
        or "(none yet)"
    )
    new_ideas = hasattr(J, "check_code")  # the judge can run seat-written code
    msgs = rig.inbox(seat)
    notes = "\n".join(f"- from {m['frm']}: {m['body'][:300]}" for m in msgs) or "(none)"
    out = ask_json(
        ctx["llm"],
        rig.spec["seats"][seat],
        persona(rig, seat),
        f"Campaign {ctx['campaign']} of {ctx['n_campaigns']}. Current champion: {ctx['champion_desc']}.\n\n"
        f"Untested or unsettled changes (key: description):\n"
        + "\n".join(f"- {k}: {v[0]}" for k, v in menu.items())
        + f"\n\nEXPLORATORY screen vs the current champion (2 cheap panels; NOT evidence, only for prioritising):\n{screen}\n\n"
        + (
            kg.brief(ctx["champion"], ctx["champion_desc"], unavailable)
            if kg is not None
            else f"Confirmatory evidence ledger so far:\n{ev}\n\nLab lessons:\n"
            + ("\n".join(f"- {lesson}" for lesson in ctx["lessons"]) or "(none yet)")
        )
        + f"\n\nMeasured treatment SEs (for design choice):\n{vb}\n\n"
        + f"Messages to you:\n{notes}\n\n"
        + (
            "You may also propose ONE new idea that is not on the list: a feature computable from each station's "
            "daily pickup history up to the forecast origin, the target dates and station coordinates. The experimenter "
            'will write it as code. Pick it as {"key": "new", "name": "short_snake_case_name", "idea": "what the feature '
            'is and why it should reduce the error, in 2-3 sentences", "rationale": "..."}. A new idea has no exploratory '
            "screen yet, so lessons about screens do not apply to it; it is judged only by the preregistered test. "
            + (
                "None of the listed changes has a positive screen: a well-reasoned new idea is how the lab keeps "
                "learning now. "
                if not any(v > 0 for k, v in ctx["screen"].items() if k in menu)
                else ""
            )
            if new_ideas
            else ""
        )
        + "Pick up to TWO changes in all to test confirmatorily this campaign: listed changes"
        + (" and at most one new idea. " if new_ideas else ". ")
        + "Do not pick changes already graded A. If nothing is worth testing, pick none. Also state one lesson the lab "
        "should carry forward. "
        'Reply JSON: {"picks": [{"key": "...", "rationale": "..."}], "lesson": "..."}',
    )
    picks = []
    for p in out.get("picks", []):
        if p.get("key") in menu:
            picks.append(p)
        elif p.get("key") == "new" and new_ideas and not any(q["key"].startswith("code:") for q in picks):
            name = re.sub(r"[^a-z0-9_]+", "_", str(p.get("name", "")).lower()).strip("_")[:40]
            key = f"code:{name}"
            decided = kg is not None and any(
                t["change"] == key and t["decision"] and t["champion"] == kg_champion(ctx) for t in kg.tests()
            )
            if len(name) >= 3 and p.get("idea") and not decided:
                ctx["ideas"][key] = dict(name=name, idea=str(p["idea"])[:600])
                picks.append(dict(p, key=key))
    picks = picks[:2]
    if out.get("lesson"):
        ctx["lessons"].append(f"(after campaign {ctx['campaign'] - 1}) {out['lesson']}")
    ctx["alpha_per_test"] = rig.spec["decision_standards"]["alpha_campaign"] / max(len(picks), 1)
    for i, p in enumerate(picks):
        key = p["key"]
        sid = f"C{ctx['campaign']}-S{i + 1}-{key.replace(':', '_')}"
        rig.new_slice(
            sid,
            change_desc(ctx, key),
            f"# {change_desc(ctx, key)}\n\nChampion: {ctx['champion_desc']}\n\nRationale (PI): {p.get('rationale', '')}\n",
        )
        ctx["primary_seed"][sid] = J.data_keys("primary", ctx["campaign"], i)[0]
        ctx["replication_seed"][sid] = J.data_keys("replication", ctx["campaign"], i)[0]
        rig.advance(seat, sid, "hypothesis", note=str(p.get("rationale", ""))[:120])
        rig.queue(
            seat, rig.seat_for("methodologist"), "draft_prereg", sid, dict(key=key, rationale=p.get("rationale", ""))
        )
    return dict(picks=[p["key"] for p in picks], lesson=out.get("lesson"))


def kg_champion(ctx):
    from state.knowledge import config_id

    return config_id(ctx["champion"])


def pi_read(rig, seat, msgs, ctx):
    body = "\n\n".join(f"From {m['frm']} ({m['slice']}):\n{m['body']}" for m in msgs)
    out = ask_json(
        ctx["llm"],
        rig.spec["seats"][seat],
        persona(rig, seat),
        f"Results arrived:\n{body}\n\nWhat should the lab do next, given ONLY these evidence grades? "
        'Reply JSON: {"next": "...", "agenda_update": "..."}',
    )
    rig.note(seat, f"agenda: {out.get('agenda_update', '')}")
    ctx["pi_next"] = out
