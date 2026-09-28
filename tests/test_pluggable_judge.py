"""ROADMAP 8b: the rigspec names the judge; the lab reaches data and treatments only through it."""

import pytest

from harness.daemon import load_rigspec, run
from harness.fake_llm import fake_llm

# Recorded from the forecast lab before the refactor (fake LLM, 3 campaigns): the refactor must not change them.
GOLDEN_EVIDENCE = [
    ("C1-S1-last_year_window", "supported", "A: replicated", 0.111978),
    ("C2-S1-promo_feature", "supported", "A: replicated", 0.022097),
]
GOLDEN_CHAMPIONS = [(1, "last_year_window", "C1-S1-last_year_window"), (2, "promo_feature", "C2-S1-promo_feature")]
GOLDEN_STAGES = [
    ("C1-S1-last_year_window", "written"),
    ("C1-S2-log_target", "parked"),
    ("C2-S1-promo_feature", "written"),
    ("C2-S2-log_target", "parked"),
    ("C3-S1-log_target", "parked"),
]


def test_forecast_lab_is_unchanged_by_the_refactor(tmp_path):
    rig, ctx, _ = run(fake_llm, root=str(tmp_path / "run"), n_campaigns=3)
    assert [(e["slice"], e["decision"], e["grade"], round(e["point"], 6)) for e in ctx["evidence"]] == GOLDEN_EVIDENCE
    assert [(h["campaign"], h["promoted"], h["evidence"]) for h in ctx["champion_history"]] == GOLDEN_CHAMPIONS
    assert sorted(rig.db.execute("SELECT id, stage FROM slices")) == GOLDEN_STAGES


def test_rigspec_names_the_judge():
    assert load_rigspec()["judge"] == "judges.forecast_lab"


@pytest.mark.parametrize("judge", ["judges.no_such_judge", None])
def test_a_rigspec_without_a_loadable_judge_is_refused_at_start(tmp_path, judge):
    spec = load_rigspec()
    if judge is None:
        del spec["judge"]
    else:
        spec["judge"] = judge
    path = tmp_path / "spec.json"
    path.write_text(__import__("json").dumps(spec))
    with pytest.raises(ValueError, match="judge"):
        run(fake_llm, root=str(tmp_path / "run"), n_campaigns=1, rigspec=str(path))
    assert not (tmp_path / "run").exists()  # refused before anything was written
