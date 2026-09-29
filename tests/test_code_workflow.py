"""ROADMAP 5c: the PI proposes a new idea, the experimenter writes it as code that must pass the judge's checks and the
critic's review, the prereg locks the exact code, and the replicator writes its own code from the text alone."""

import hashlib
import inspect
import json

import pytest

from agents.statistician.handler import promote_champion
from harness.daemon import load_rigspec, make_ctx, run
from harness.fake_llm import WEEKEND_CODE, WEEKEND_IDEA, make_fake_llm
from judges import bikeshare as bj
from ops import bikeshare_ingest as ing
from state.knowledge import Knowledge
from tests.fixtures.bikeshare.synth import stub_get, trip_zips

NOISY = (
    "```python\nimport numpy as np\ndef features(view):\n"
    "    return np.random.default_rng().normal(size=int(view['n_rows']))\n```"
)
SID = "C1-S1-code_weekend_profile"


@pytest.fixture(scope="module")
def spec_path(tmp_path_factory):
    d = tmp_path_factory.mktemp("codewf")
    ing.ingest("chi", str(d / "chi"), get=stub_get(trip_zips()), log=lambda *_: None)
    spec = load_rigspec("rigs/bikeshare-lab.json")
    spec["judge_config"] = dict(root=str(d / "chi"))
    spec["decision_standards"]["power_min"] = 0.0  # the synthetic effect is small: let the workflow reach lock
    (d / "spec.json").write_text(json.dumps(spec))
    return str(d / "spec.json")


def llm(experimenter=(), replicator=(), idea=WEEKEND_IDEA):
    """The fake LLM, except: the PI proposes only the new idea, and the experimenter's / replicator's successive
    code replies can be scripted (then fall back to the fake's working code)."""
    base = make_fake_llm(bj.MENU)
    ex, rp = list(experimenter), list(replicator)

    def f(prompt, system=None, tier=None):
        who = (system or "").split(",")[0]
        if "pi@" in who and "Pick up to TWO" in prompt:
            return json.dumps({"picks": [idea], "lesson": "try a new idea"})
        if "experimenter@" in who and "as code" in prompt and ex:
            return ex.pop(0)
        if "replicator@" in who and "as code" in prompt and rp:
            return rp.pop(0)
        return base(prompt, system, tier)

    return f


def test_a_new_idea_is_written_checked_reviewed_and_locked_as_code(spec_path, tmp_path):
    rig, ctx, _ = run(
        llm(), root=str(tmp_path / "r"), n_campaigns=1, rigspec=spec_path, knowledge=str(tmp_path / "kg.db")
    )
    assert rig.stage(SID) in {"written", "parked"}
    pre = ctx["locked"][SID]
    [item] = pre.treatment["code"]
    assert item["name"] == "weekend_profile" and "def features(view)" in item["source"]
    assert pre.verify() and "seat-written feature 'weekend_profile'" in pre.statement
    assert (
        rig.read_proof(SID, "code_check_a0.json")["ok"]
        and rig.read_proof(SID, "code_review_a0.json")["verdict"] == "approve"
    )
    assert ctx["code"][SID]["sha"] == hashlib.sha256(item["source"].encode()).hexdigest()
    tests = Knowledge(str(tmp_path / "kg.db"), "bikeshare-lab").tests()
    assert [t["change"] for t in tests] == ["code:weekend_profile"]


def test_code_that_fails_the_checks_is_rewritten_with_the_reason(spec_path, tmp_path):
    rig, ctx, _ = run(llm(experimenter=[NOISY]), root=str(tmp_path / "r"), n_campaigns=1, rigspec=spec_path)
    assert rig.read_proof(SID, "code_check_a0.json")["error"] == "different output on a second run"
    assert rig.read_proof(SID, "code_check_a1.json")["ok"]
    assert SID in ctx["locked"]


def test_code_that_never_passes_is_never_locked(spec_path, tmp_path):
    rig, ctx, _ = run(llm(experimenter=[NOISY] * 20), root=str(tmp_path / "r"), n_campaigns=1, rigspec=spec_path)
    assert SID not in ctx["locked"] and rig.stage(SID) == "parked"
    refused = rig.db.execute(
        "SELECT count(*) FROM slice_events WHERE slice=? AND note LIKE 'not implementable%'", (SID,)
    ).fetchone()[0]
    assert refused >= 1


def test_a_replication_needs_the_replicators_own_code_to_pass(spec_path, tmp_path, monkeypatch):
    import agents.statistician.handler as st

    real = st.sk.decide

    def primary_supported(est, sesoi):  # only the primary analysis; controls and the replication decide for real
        return "supported" if inspect.stack()[1].function == "statistician_analyse" else real(est, sesoi)

    monkeypatch.setattr(st.sk, "decide", primary_supported)
    rig, ctx, _ = run(llm(replicator=[NOISY]), root=str(tmp_path / "r"), n_campaigns=1, rigspec=spec_path)
    rep = rig.read_proof(SID, "replication.json")
    assert rep["reimplemented_as"] == "independent code" and not rep["code_check"]["ok"]
    assert (
        rig.db.execute(
            "SELECT count(*) FROM slice_events WHERE slice=? AND to_stage='not_replicated' AND ok=1", (SID,)
        ).fetchone()[0]
        == 1
    )


def test_promotion_carries_the_exact_tested_code_forward(spec_path):
    ctx = make_ctx(None, bj)
    source = WEEKEND_CODE.split("```python\n")[1].split("```")[0]
    treatment = dict(bj.BASELINE, code=[dict(name="weekend_profile", source=source)])

    class Pre:
        pass

    pre = Pre()
    pre.treatment = treatment
    ctx.update(campaign=1, locked={SID: pre}, judge=bj)
    ctx["evidence"] = [
        dict(
            campaign=1,
            slice=SID,
            key="code:weekend_profile",
            grade="A: replicated",
            champion=ctx["champion_desc"],
            point=0.05,
        )
    ]

    class Rig:
        pass

    assert promote_champion(Rig(), ctx) == "code:weekend_profile"
    assert ctx["champion"]["code"][0]["source"] == source and "weekend_profile" in ctx["champion_desc"]


def test_an_idea_already_decided_against_this_champion_is_not_proposed_again(spec_path, tmp_path):
    kg = str(tmp_path / "kg.db")
    run(llm(), root=str(tmp_path / "r1"), n_campaigns=1, rigspec=spec_path, knowledge=kg)
    rig, ctx, _ = run(llm(), root=str(tmp_path / "r2"), n_campaigns=1, rigspec=spec_path, knowledge=kg)
    decided = [t for t in Knowledge(kg, "bikeshare-lab").tests() if t["decision"]]
    if decided:  # the first run decided it: the second may not test it again
        assert not rig.db.execute("SELECT count(*) FROM slices").fetchone()[0]
