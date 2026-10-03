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


def test_every_deterministic_terminal_park_is_a_repeat_but_a_recoverable_one_is_not(tmp_path):
    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run_id = kg.begin_run("r", "judge-1")
    record = dict(change_desc="x", comparator=BASE, comparator_desc="base", judge="judge-1", data_key="confirmation",
                  design="B", decision=None, grade=None, stage="parked")  # fmt: skip
    # Each is a park whose cause is a function only of the treatment/data (true repeat), except the last: a stalled
    # slice (a handler that crashed) is random/recoverable, so re-offering it is not reproducing a known answer.
    cases = [
        ("underpowered", "underpowered at largest design", True),
        ("design", "design check failed: ['censor_fresh']", True),
        ("leak", "leak canary fired", True),
        ("revcap", "revision cap reached; last objection: x", False),  # LLM review rounds: once may be bad luck
        ("stalled", "stalled at run: experimenter failed (ConnectionError)", False),
    ]
    for i, (name, reason, _) in enumerate(cases):
        kg.test(run_id, 1, f"C1-S{i + 1}-{name}", change=name, treatment=dict(BASE, holidays=i), reason=reason, **record)
    for i, (name, _reason, repeat) in enumerate(cases):
        assert kg.is_repeat(dict(BASE, holidays=i), BASE, "judge-1", "confirmation") is repeat, name
    assert not kg.is_repeat(dict(BASE, holidays=0), BASE, "judge-2", "confirmation")  # new data: a repeat may differ
    kg.test(run_id, 2, "C2-S1-revcap", change="revcap", treatment=dict(BASE, holidays=3),
            reason="revision cap reached; last objection: y", **record)  # fmt: skip
    assert kg.is_repeat(dict(BASE, holidays=3), BASE, "judge-1", "confirmation")  # the second cap settles it


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


def test_regrade_rewrites_b_grades_from_the_replication_proof(tmp_path):
    import json

    from harness.knowledge_import import regrade
    from judges.forecast_lab import BASELINE
    from state.knowledge import Knowledge

    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run = kg.begin_run("r1", "j")
    common = dict(change_desc="x", treatment=dict(BASELINE, a=1), comparator=BASELINE, comparator_desc="base",
                  judge="j", data_key="k", design="B", stage="written")  # fmt: skip
    for sid, dec, grade, rep in (("S1", "supported", "B: supported, awaiting replication", "no_effect"),
                                 ("S2", "no_effect", "B: negative result, awaiting replication", "no_effect"),
                                 ("S3", "supported", "C: deviated from prereg (exploratory)", "supported")):  # fmt: skip
        kg.test(run, 1, sid, change=sid, decision=dict(decision=dec, point=0.1, lo=0.0, hi=0.2), grade=grade, **common)
        proof = tmp_path / "runs" / "r1" / "slices" / sid / "proof"
        proof.mkdir(parents=True)
        (proof / "replication.json").write_text(json.dumps({"decision": rep, "same_treatment": True}))
    changed = regrade(kg, str(tmp_path / "runs"))
    assert sorted(changed.values()) == ["A: negative result, replicated", "B: supported, not replicated"]
    assert {t["grade"] for t in kg.tests()} >= {"C: deviated from prereg (exploratory)"}  # C is left alone
    assert regrade(kg, str(tmp_path / "runs")) == {}  # idempotent


def test_a_lesson_with_no_real_words_never_swallows_real_ones(tmp_path):
    """ROADMAP item 5a: a content-free lesson ('N/A') used to swallow every real lesson into itself when it was
    the newest (processed first); it must now keep its own slot and never fold, or be folded into, another."""
    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    r1 = kg.begin_run("r1", "j", started=1.0)
    kg.lesson(r1, 1, "Non-positive exploratory screens remain a hard gate for listed changes")
    kg.lesson(r1, 2, "Composite features of tight positive results are worth a confirmatory slot")
    kg.lesson(r1, 3, "The champion's last 28 day feature still dominates every variant tried so far")
    kg.lesson(r1, 4, "N/A")  # newest (processed first): a content-free reply with no real words at all
    ls = kg.lessons(8)
    assert len(ls) == 4  # all three real lessons kept, the degenerate one in its own slot, nothing swallowed
    assert not any("stated" in x for x in ls)  # none of them got folded into anything
    assert any(x == "N/A" for x in ls)
    assert any("hard gate" in x for x in ls)
    assert any("Composite" in x for x in ls)
    assert any("dominates every variant" in x for x in ls)


def test_runs_without_progress_ignores_a_stalled_test_node(tmp_path):
    """ROADMAP item 4: a slice that stalled mid-workflow (a handler kept failing on it) never reached 'written'
    or 'parked', so it must not count as progress the way runs_without_tests (any test node) wrongly did."""
    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    r1 = kg.begin_run("r1", "j", started=1.0)
    kg.test(r1, 1, "S1", change="x", change_desc="x", treatment={"a": 1}, comparator={}, comparator_desc="b",
            judge="j", data_key="k", design="B", decision=None, grade=None, stage="design_review",
            reason="stalled at design_review: methodologist_draft failed (ConnectionError)")  # fmt: skip
    kg.begin_run("r2", "j", started=2.0)
    assert kg.runs_without_tests() == 1  # r1 "tested" something (a test node exists), even though it never finished
    assert kg.runs_without_progress() == 2  # neither run ever produced real progress


def test_a_request_asked_again_after_being_answered_reopens(tmp_path):
    """ROADMAP item 5c: the circuit breaker's owner request could only ever be answered once; a later recurrence
    of the same condition must reopen it, not leave it stuck 'answered' forever."""
    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run_id = kg.begin_run("r", "j")
    ask = dict(what="An events calendar", why="w", how="h", done="d")
    rid = kg.request(run_id, 1, ask)
    kg.reply("None exists", rid)
    assert kg.requests("open") == [] and kg.requests("answered")[0]["id"] == rid
    again = kg.request(run_id, 2, ask)
    assert again == rid  # the same condition, not a new request
    (r,) = kg.requests("open")
    assert r["id"] == rid  # reopened, not stuck "answered" forever


def test_the_brief_folds_old_tests_so_it_stays_bounded_at_live_scale(tmp_path):
    """ROADMAP item 2: the 'tested against THIS champion' section is unbounded today. At something like the live
    lab's scale (100+ tests, ~100 change keys, one champion, never promoted) it must stay bounded, and no change
    may disappear: every distinct change still appears, in the recent lines or the folded summary."""
    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run_id = kg.begin_run("r", "j")
    decisions = ["no_effect", "inconclusive", "supported", "harmful"]
    n = 113
    for i in range(n):
        change, dec = f"idea_{i % 100}", decisions[i % len(decisions)]
        kg.test(run_id, 1, f"S{i:03d}", change=change, change_desc=change, treatment=dict(BASE, holidays=i),
                comparator=BASE, comparator_desc="base", judge="j", data_key=f"k{i}", design="B",
                decision=dict(decision=dec, point=0.01, lo=-0.01, hi=0.03), grade="C", stage="written")  # fmt: skip
    brief = kg.brief(BASE, "base", [])
    assert brief.count("Tested against THIS champion") == 1
    assert len(brief) < 8000  # unbounded growth at this scale reaches ~22,000 chars for this section alone
    for i in range(100):
        assert f"idea_{i}" in brief  # folded, never dropped
