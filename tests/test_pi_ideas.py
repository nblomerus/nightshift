"""ROADMAP items 7 and 11: a code idea's identity in the knowledge graph is its CONTENT, not a 40-char name
slug, and the PI is told to bundle its own already-measured real effects into one idea."""

import json

from agents.pi.handler import pi_plan, take_picks
from harness.daemon import make_ctx
from state.knowledge import Knowledge
from state.rig import Rig

CHAMPION = {"baseline": True}
# Slugifies to more than 40 characters, so two different ideas written under it collide once truncated.
LONG_NAME = "a_very_long_shared_feature_name_that_keeps_going_and_going"


def new_ctx():
    return {"champion": CHAMPION, "ideas": {}}


def test_two_ideas_with_the_same_long_name_but_different_text_both_proceed(tmp_path):
    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run_id = kg.begin_run("r", "j")
    first_idea = "Use each station's trailing 7-day mean pickups as a feature."
    ctx1 = new_ctx()
    picks1, dropped1 = take_picks({"picks": [{"key": "new", "name": LONG_NAME, "idea": first_idea}]}, {}, True, kg, ctx1)
    assert not dropped1 and len(picks1) == 1
    key1 = picks1[0]["key"]
    # Record it as decided against this champion, with its idea fingerprint, the way record_campaign would.
    kg.test(run_id, 1, "C1-S1-x", change=key1, change_desc="x", treatment=dict(CHAMPION, code=[]), comparator=CHAMPION,
            comparator_desc="c", judge="j", data_key="k", design="B",
            decision=dict(decision="no_effect", point=0.0, lo=-0.01, hi=0.01), grade="C", stage="written",
            idea_fp=ctx1["ideas"][key1]["idea_fp"])  # fmt: skip

    # A different idea, slugified to the exact same name, is a different hypothesis: it must not be dropped.
    second_idea = "Use the station's distance to the nearest rail stop as a feature."
    ctx2 = new_ctx()
    picks2, dropped2 = take_picks({"picks": [{"key": "new", "name": LONG_NAME, "idea": second_idea}]}, {}, True, kg, ctx2)
    assert not dropped2 and len(picks2) == 1
    assert picks2[0]["key"] != key1  # disambiguated by content, not collided with the first idea's key

    # The SAME idea text under the same name is still recognised as a genuine repeat and dropped.
    ctx3 = new_ctx()
    picks3, dropped3 = take_picks({"picks": [{"key": "new", "name": LONG_NAME, "idea": first_idea}]}, {}, True, kg, ctx3)
    assert not picks3 and dropped3 and "already decided" in dropped3[0]


def test_a_code_idea_that_hit_the_revision_cap_is_not_retried_under_the_same_name(tmp_path):
    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run_id = kg.begin_run("r", "j")
    idea = "Use the station's trailing 14-day pickup trend as a feature."
    ctx1 = new_ctx()
    picks1, _ = take_picks({"picks": [{"key": "new", "name": "trailing_trend", "idea": idea}]}, {}, True, kg, ctx1)
    key = picks1[0]["key"]
    kg.test(run_id, 1, "C1-S1-x", change=key, change_desc="x", treatment=dict(CHAMPION, code=[]), comparator=CHAMPION,
            comparator_desc="c", judge="j", data_key="k", design="B", decision=None, grade=None, stage="parked",
            reason="revision cap reached; last objection: needs a cleaner draft",
            idea_fp=ctx1["ideas"][key]["idea_fp"])  # fmt: skip

    ctx2 = new_ctx()
    picks2, dropped2 = take_picks({"picks": [{"key": "new", "name": "trailing_trend", "idea": idea}]}, {}, True, kg, ctx2)
    assert not picks2 and dropped2 and "already decided" in dropped2[0]


def test_a_stalled_code_idea_is_not_treated_as_a_repeat(tmp_path):
    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run_id = kg.begin_run("r", "j")
    idea = "Use the count of nearby subway entrances as a feature."
    ctx1 = new_ctx()
    picks1, _ = take_picks({"picks": [{"key": "new", "name": "subway_entrances", "idea": idea}]}, {}, True, kg, ctx1)
    key = picks1[0]["key"]
    kg.test(run_id, 1, "C1-S1-x", change=key, change_desc="x", treatment=dict(CHAMPION, code=[]), comparator=CHAMPION,
            comparator_desc="c", judge="j", data_key="k", design="B", decision=None, grade=None, stage="design_review",
            reason="stalled at design_review: methodologist_draft failed (ConnectionError)",
            idea_fp=ctx1["ideas"][key]["idea_fp"])  # fmt: skip

    ctx2 = new_ctx()
    picks2, dropped2 = take_picks({"picks": [{"key": "new", "name": "subway_entrances", "idea": idea}]}, {}, True, kg, ctx2)
    assert picks2 and not dropped2  # a crash, not a deterministic cause: worth trying again


def test_the_pi_prompt_names_the_bundling_move_when_new_ideas_are_allowed(tmp_path, monkeypatch):
    from judges import forecast_lab

    monkeypatch.setattr(forecast_lab, "check_code", lambda *a, **k: None, raising=False)
    from harness.daemon import load_rigspec

    spec = load_rigspec()
    rig = Rig(str(tmp_path / "rig"), spec)
    seen = []

    def spy(prompt, system=None, tier=None):
        seen.append(prompt)
        return json.dumps({"picks": [], "lesson": "l"})

    ctx = make_ctx(spy, forecast_lab)
    ctx.update(campaign=1, n_campaigns=1)
    pi_plan(rig, rig.seat_for("pi"), {"payload": {}}, ctx)
    assert "BUNDLE" in seen[0] and "already-measured" in seen[0] and "up to 8" in seen[0]
