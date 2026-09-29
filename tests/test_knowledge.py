"""The lab's knowledge graph: memory across runs that the PI plans from, and that never decides anything."""

import json

import agents
from agents.pi.handler import pi_plan
from harness.daemon import load_rigspec, make_ctx, run
from harness.fake_llm import fake_llm
from judges import forecast_lab
from state.knowledge import Knowledge, config_id
from state.rig import Rig

BASE = forecast_lab.BASELINE
YOY = dict(BASE, **forecast_lab.MENU["last_year_window"][1])


def evidence(ctx):
    return [(e["slice"], e["decision"], e["grade"], round(e["point"], 6)) for e in ctx["evidence"]]


def test_the_graph_never_changes_what_the_kernel_decides(tmp_path):
    _, plain, _ = run(fake_llm, root=str(tmp_path / "a"), n_campaigns=1)
    _, with_kg, _ = run(fake_llm, root=str(tmp_path / "b"), n_campaigns=1, knowledge=str(tmp_path / "kg.db"))
    assert evidence(plain) == evidence(with_kg)


def test_knowledge_persists_and_the_next_run_continues_from_its_champion(tmp_path):
    path = str(tmp_path / "kg.db")
    _, first, _ = run(fake_llm, root=str(tmp_path / "r1"), n_campaigns=1, knowledge=path)
    assert first["champion_history"], "the fake run promotes in campaign 1"
    kg = Knowledge(path, "forecast-lab")
    champ, desc = kg.current_champion()
    assert config_id(champ) == config_id(first["champion"]) and desc == first["champion_desc"]
    assert [t["change"] for t in kg.tests(BASE) if t["decision"]] == ["last_year_window"]

    seen = []

    def spy(prompt, system=None, tier=None):
        if "pi@" in (system or "") and "Pick up to TWO" in prompt:
            seen.append(prompt)
        return fake_llm(prompt, system, tier)

    _, second, _ = run(spy, root=str(tmp_path / "r2"), n_campaigns=1, knowledge=path)
    assert all(pre.comparator == first["champion"] for pre in second["locked"].values())
    assert "LAB KNOWLEDGE (2 run(s)" in seen[0]
    assert "promoted in run r1 campaign 1 by last_year_window" in seen[0]


def test_parked_attempts_are_remembered_with_their_reason(tmp_path):
    path = str(tmp_path / "kg.db")
    rig, ctx, _ = run(fake_llm, root=str(tmp_path / "r"), n_campaigns=1, knowledge=path)
    parked = [t for t in Knowledge(path, "forecast-lab").tests() if t["stage"] == "parked"]
    assert parked and all(t["decision"] is None and "underpowered" in t["reason"] for t in parked)


def test_a_repeat_is_the_same_change_champion_judge_and_data(tmp_path):
    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run_id = kg.begin_run("r", "judge-1")
    dec = dict(decision="inconclusive", point=0.05, lo=-0.01, hi=0.11)
    record = dict(change="x", change_desc="x", treatment=YOY, comparator=BASE, comparator_desc="base", judge="judge-1")
    kg.test(run_id, 1, "C1-S1-x", **record, data_key="confirmation", design="B", decision=dec, grade="C", stage="written")
    assert kg.is_repeat(YOY, BASE, "judge-1", "confirmation")
    assert not kg.is_repeat(YOY, BASE, "judge-2", "confirmation")  # new judge or new data manifest
    assert not kg.is_repeat(YOY, BASE, "judge-1", 1_002_000)  # a fresh synthetic panel
    assert not kg.is_repeat(YOY, YOY, "judge-1", "confirmation")  # a different champion
    kg.test(run_id, 1, "C1-S1-x", **record, data_key="confirmation", design="B", decision=dec, grade="C", stage="written")
    assert len(kg.tests()) == 1  # writing the same slice again updates it, never duplicates it


def test_the_pi_is_never_offered_a_repeat_and_is_told_why(tmp_path):
    spec = load_rigspec()
    rig = Rig(str(tmp_path / "rig"), spec)
    kg = Knowledge(str(tmp_path / "kg.db"), spec["rig"])
    seen = []

    def spy(prompt, system=None, tier=None):
        seen.append(prompt)
        return json.dumps({"picks": [{"key": "last_year_window", "rationale": "again"}], "lesson": "l"})

    ctx = make_ctx(spy, forecast_lab)
    ctx.update(campaign=1, n_campaigns=1, knowledge=kg, run_id=kg.begin_run("r", "x"))
    digest = agents.judge_digest(forecast_lab)
    key = forecast_lab.data_keys("primary", 1, 0)[0]
    kg.test(ctx["run_id"], 1, "C0-S1-last_year_window", change="last_year_window", change_desc="yoy", treatment=YOY,
            comparator=BASE, comparator_desc="base", judge=digest, data_key=key, design="A",
            decision=dict(decision="supported", point=0.1, lo=0.05, hi=0.15), grade="B", stage="written")  # fmt: skip
    out = pi_plan(rig, rig.seat_for("pi"), {"payload": {}}, ctx)
    assert out["picks"] == []  # the PI asked for it; it was not on the menu
    menu = seen[0].split("Untested or unsettled changes")[1].split("EXPLORATORY")[0]
    assert "last_year_window" not in menu
    assert "Not available this campaign" in seen[0] and "last_year_window" in seen[0]
    assert config_id(BASE) in {t["champion"] for t in kg.tests()}


def test_a_run_from_before_the_graph_can_be_imported(tmp_path):
    from harness.knowledge_import import import_run

    run(fake_llm, root=str(tmp_path / "old"), n_campaigns=2)  # no knowledge graph
    kg = Knowledge(str(tmp_path / "kg.db"), "forecast-lab")
    n = import_run(kg, str(tmp_path / "old"), forecast_lab)
    assert n["tests"] >= 2 and n["promotions"] == 2 and n["lessons"] >= 1
    champ, desc = kg.current_champion()
    assert "last year" in desc and "promotion weeks" in desc
    assert {t["change"] for t in kg.tests() if t["decision"]} >= {"last_year_window", "promo_feature"}
