"""A seat whose LLM returns nothing usable: the task is retried, and a slice that still cannot finish is recorded as
stalled, never silently orphaned."""

import json

from harness.daemon import run
from harness.fake_llm import fake_llm
from state.knowledge import Knowledge


def empty_critic(n):
    left = [n]

    def llm(prompt, system=None, tier=None):
        if "critic@" in (system or "") and left[0] > 0:
            left[0] -= 1
            return ""  # a reasoning model that spent its whole budget thinking
        return fake_llm(prompt, system, tier)

    return llm


def test_an_empty_reply_is_retried_and_the_slice_finishes(tmp_path):
    rig, ctx, transcript = run(empty_critic(2), root=str(tmp_path / "r"), n_campaigns=1)
    assert any(not t["ok"] and "no JSON" in t["error"] for t in transcript)
    assert all(st in ("written", "parked") for _, st in rig.db.execute("SELECT id, stage FROM slices"))
    assert json.loads((tmp_path / "r" / "ledger.json").read_text())["campaigns"][0]["stalled"] == []


def test_a_slice_that_cannot_finish_is_recorded_as_stalled(tmp_path):
    kg_path = str(tmp_path / "kg.db")
    rig, ctx, _ = run(empty_critic(10**6), root=str(tmp_path / "r"), n_campaigns=1, knowledge=kg_path)
    stalled = json.loads((tmp_path / "r" / "ledger.json").read_text())["campaigns"][0]["stalled"]
    assert stalled and all(rig.stage(s) == "design_review" for s in stalled)
    reviews = rig.db.execute(
        "SELECT count(*) FROM tasks WHERE kind='review_design' AND slice=?", (stalled[0],)
    ).fetchone()[0]
    assert reviews == 3  # the first try and two retries
    recorded = {t["slice"]: t for t in Knowledge(kg_path, "forecast-lab").tests()}
    assert recorded[stalled[0]]["stage"] == "design_review" and "stalled" in recorded[stalled[0]]["reason"]
