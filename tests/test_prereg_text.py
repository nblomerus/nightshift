"""ROADMAP item 1: the prereg's arm text and decision clause come from the machine config and the fixed
decision standards, never from LLM free text."""

import pytest

from agents.common import MENU, decision_clause, describe_config, prereg_statement
from harness.daemon import load_rigspec, run
from harness.fake_llm import fake_llm
from judges import forecast as fh
from state.rig import GuardError, Rig


def test_describe_config_names_every_component_of_the_config():
    champ = dict(fh.BASELINE, **MENU["last_year_window"][1], **MENU["promo_feature"][1])
    text = describe_config(champ)
    assert MENU["last_year_window"][0].lower() in text and MENU["promo_feature"][0].lower() in text
    assert MENU["log_target"][0].lower() not in text


def test_describe_config_refuses_a_config_it_cannot_describe():
    with pytest.raises(ValueError):
        describe_config(dict(fh.BASELINE, lags=(1, 2)))


@pytest.mark.parametrize(("sesoi", "target"), [(0.01, 0.025), (0.02, 0.05), (0.005, 0.01), (0.03, 0.03)])
def test_decision_clause_cites_sesoi_and_never_the_target_effect(sesoi, target):
    std = dict(sesoi=sesoi, target_effect=target)
    clause = decision_clause(std, alpha=0.025)
    assert f"{sesoi:.1%}" in clause
    assert "target" not in clause.lower()
    if target != sesoi:
        assert f"{target:.1%}" not in clause


def test_statement_names_both_arms_from_config():
    champ = dict(fh.BASELINE, **MENU["last_year_window"][1])
    s = prereg_statement(champ, "promo_feature", dict(sesoi=0.01, target_effect=0.025), 0.05)
    assert s.startswith(f"Hypothesis: the change '{MENU['promo_feature'][0]}' reduces next-4-week WAPE")
    assert f"Comparator (current champion): {describe_config(champ)}." in s
    assert f"Treatment: {describe_config(dict(champ, **MENU['promo_feature'][1]))}." in s


def test_rig_refuses_implementation_check_without_config_statement(tmp_path):
    rig = Rig(str(tmp_path), load_rigspec())
    rig.new_slice("S1", "q", "spec")
    for seat, to in [
        ("pi", "hypothesis"),
        ("methodologist", "prereg_draft"),
        ("methodologist", "design_review"),
        ("critic", "approved_design"),
    ]:
        rig.advance(rig.seat_for(seat), "S1", to, checks={"prereg_fields": True})
    with pytest.raises(GuardError):
        rig.advance(
            rig.seat_for("experimenter"),
            "S1",
            "implementation_checked",
            checks={"implementable_exactly": True, "statement_from_config": False},
        )
    assert rig.stage("S1") == "approved_design"


def test_after_promotion_the_next_prereg_names_the_new_champion(tmp_path):
    rig, ctx, _ = run(fake_llm, root=str(tmp_path / "run"), n_campaigns=2)
    assert ctx["champion_history"], "the fake run should promote in campaign 1"
    new_champ = ctx["champion_history"][0]["to"]
    c2 = [sid for sid in ctx["locked"] if sid.startswith("C2-")]
    assert c2
    for sid in c2:
        assert new_champ in ctx["locked"][sid].statement
    # the fake experimenter refuses any statement that does not name the current champion: none were refused
    stale = rig.db.execute("SELECT slice FROM slice_events WHERE note LIKE 'not implementable%'").fetchall()
    assert stale == []
    parked = [sid for sid, st in rig.db.execute("SELECT id, stage FROM slices") if st == "parked"]
    for sid in parked:
        notes = [n for (n,) in rig.db.execute("SELECT note FROM slice_events WHERE slice = ?", (sid,))]
        assert "underpowered at largest design" in notes or "leak canary fired" in notes, (sid, notes)
