"""PI: plans each campaign from the evidence ledger, screen, lessons and messages; reads findings."""

from __future__ import annotations

from agents.common import MENU, ask_json, persona


# ---------------------------------------------------------------------------- PI
def pi_plan(rig, seat, task, ctx):
    """Plan campaign k from everything the lab knows: champion, exploratory screen, evidence ledger,
    lessons, critic suggestions. Re-testing an inconclusive change is allowed only as a NEW prereg
    (fresh data, typically a larger design); earlier data are never pooled post hoc."""
    menu = {
        k: v
        for k, v in MENU.items()
        if not all(ctx["champion"].get(a) == b for a, b in v[1].items()) and k not in ctx["replicating"]
    }
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
        f"Confirmatory evidence ledger so far:\n{ev}\n\nMeasured treatment SEs (for design choice):\n{vb}\n\n"
        f"Lab lessons:\n"
        + ("\n".join(f"- {lesson}" for lesson in ctx["lessons"]) or "(none yet)")
        + f"\n\nMessages to you:\n{notes}\n\n"
        "Pick up to TWO changes to test confirmatorily this campaign (re-testing an inconclusive one is "
        "allowed as a new prereg on fresh data). Do not pick changes already graded A. If nothing is worth "
        "testing, pick none. Also state one lesson the lab should carry forward. "
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
            MENU[key][0],
            f"# {MENU[key][0]}\n\nChampion: {ctx['champion_desc']}\n\nRationale (PI): {p['rationale']}\n",
        )
        ctx["primary_seed"][sid] = 8000 + 100 * ctx["campaign"] + i
        ctx["replication_seed"][sid] = 8500 + 100 * ctx["campaign"] + i
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
