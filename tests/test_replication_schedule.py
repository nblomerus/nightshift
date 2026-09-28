"""ROADMAP item 2: a supported grade-B result tested against the current champion gets one more replication
(fresh seed, same locked prereg) at the start of the next campaign; attempts are capped by a guard."""

import json

import pytest

from agents.common import REPLICATION_CAP
from agents.statistician.handler import replication_checks
from harness.daemon import run
from harness.fake_llm import fake_llm
from judges.forecast_lab import MENU
from state.rig import GuardError

SLICE = "C1-S1-last_year_window"


def failing_replicator(n_failures):
    """The fake LLM, except the replicator misreads last_year_window as another change `n_failures` times."""
    left = [n_failures]

    def llm(prompt, system=None, tier=None):
        hypothesis = prompt.split("Statement:")[1].split(". ")[0] if "Statement:" in prompt else ""
        if "replicator@" in (system or "") and MENU["last_year_window"][0] in hypothesis and left[0] > 0:
            left[0] -= 1
            return json.dumps({"key": "strong_ridge", "reasoning": "misread"})
        return fake_llm(prompt, system, tier)

    return llm


def grades(ctx, sid):
    return [(e["campaign"], e["grade"]) for e in ctx["evidence"] if e["slice"] == sid]


def test_grade_b_gets_one_extra_replication_and_is_promoted_when_it_succeeds(tmp_path):
    rig, ctx, _ = run(failing_replicator(1), root=str(tmp_path / "run"), n_campaigns=2)
    assert grades(ctx, SLICE) == [(1, "B: supported, awaiting replication"), (2, "A: replicated")]
    attempts = rig.read_proof(SLICE, "replications.json")
    assert [a["attempt"] for a in attempts] == [1, 2]
    seeds = [a["seed"] for a in attempts]
    assert len(set(seeds)) == 2 and ctx["primary_seed"][SLICE] not in seeds
    assert all(pre.verify() for pre in ctx["locked"].values())
    assert ctx["champion_history"][0]["campaign"] == 2
    assert ctx["champion_history"][0]["promoted"] == "last_year_window"
    # the extra replication came before new hypotheses: the PI did not re-test the same change
    assert not any(sid.startswith("C2-") and sid.endswith("last_year_window") for sid in ctx["locked"])


def test_failed_second_replication_does_not_promote_and_the_cap_is_a_guard(tmp_path):
    rig, ctx, _ = run(failing_replicator(2), root=str(tmp_path / "run"), n_campaigns=2)
    assert grades(ctx, SLICE) == [(c, "B: supported, awaiting replication") for c in (1, 2)]
    assert "last_year_window" not in [h["promoted"] for h in ctx["champion_history"]]
    assert len(rig.read_proof(SLICE, "replications.json")) == REPLICATION_CAP

    checks = replication_checks(rig, SLICE, ctx)
    assert checks["under_replication_cap"] is False
    with pytest.raises(GuardError, match="under_replication_cap"):
        rig.advance(rig.seat_for("statistician"), SLICE, "replication_queued", checks=checks)
    assert rig.stage(SLICE) == "written"
    refused = rig.db.execute(
        "SELECT count(*) FROM slice_events WHERE slice=? AND to_stage='replication_queued' AND ok=0", (SLICE,)
    ).fetchone()[0]
    assert refused >= 1  # refusals are logged, not swallowed


def test_only_the_statistician_may_queue_a_replication(tmp_path):
    rig, ctx, _ = run(failing_replicator(1), root=str(tmp_path / "run"), n_campaigns=1)
    with pytest.raises(GuardError, match="may not move"):
        rig.advance(rig.seat_for("pi"), SLICE, "replication_queued", checks=replication_checks(rig, SLICE, ctx))
