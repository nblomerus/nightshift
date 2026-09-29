"""PI: plans each campaign from the evidence ledger, screen, lessons and messages; reads findings."""

from __future__ import annotations

from agents.common import ask_json, judge_digest, persona


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
        digest, data_key = judge_digest(J), J.data_keys("primary", ctx["campaign"], 0)[0]
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
    screen = "\n".join(f"- {k}: {v:+.2%}" for k, v in ctx["screen"].items())
    vb = (
        "\n".join(
            f"- {k} design {d}: pilot SE {v['se']:.2%}, pilot effect {v['pilot_effect']:+.2%}"
            for (k, d), v in ctx["variance_book"].items()
        )
        or "(none yet)"
    )
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
        "Pick up to TWO changes to test confirmatorily this campaign; only the changes listed above are available. "
        "Do not pick changes already graded A. If nothing is worth testing, pick none. Also state one lesson the lab "
        "should carry forward. "
        'Reply JSON: {"picks": [{"key": "...", "rationale": "..."}], "lesson": "..."}',
    )
    picks = [p for p in out.get("picks", []) if p.get("key") in menu][:2]
    if out.get("lesson"):
        ctx["lessons"].append(f"(after campaign {ctx['campaign'] - 1}) {out['lesson']}")
    ctx["alpha_per_test"] = rig.spec["decision_standards"]["alpha_campaign"] / max(len(picks), 1)
    for i, p in enumerate(picks):
        key = p["key"]
        sid = f"C{ctx['campaign']}-S{i + 1}-{key}"
        rig.new_slice(
            sid,
            J.MENU[key][0],
            f"# {J.MENU[key][0]}\n\nChampion: {ctx['champion_desc']}\n\nRationale (PI): {p['rationale']}\n",
        )
        ctx["primary_seed"][sid] = J.data_keys("primary", ctx["campaign"], i)[0]
        ctx["replication_seed"][sid] = J.data_keys("replication", ctx["campaign"], i)[0]
        rig.advance(seat, sid, "hypothesis", note=p["rationale"][:120])
        rig.queue(seat, rig.seat_for("methodologist"), "draft_prereg", sid, dict(key=key, rationale=p["rationale"]))
    return dict(picks=[p["key"] for p in picks], lesson=out.get("lesson"))


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
