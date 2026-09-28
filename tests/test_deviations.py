"""ROADMAP item 3: any change to a locked prereg field is recorded as a deviation and downgrades the grade."""

import dataclasses as dc

import numpy as np
import pytest

import agents
from harness.daemon import load_rigspec, run
from harness.fake_llm import fake_llm
from science import kernel as sk
from state.rig import Rig

SLICE = "C1-S1-last_year_window"


def tamper_before_run(monkeypatch, relock):
    """Move the goalposts between lock and run: lower the SESOI of the first slice's locked prereg."""
    real = agents.HANDLERS["run_experiment"]

    def run_experiment(rig, seat, task, ctx):
        if task["slice"] == SLICE:
            moved = dc.replace(ctx["locked"][SLICE], sesoi=0.001)
            ctx["locked"][SLICE] = moved.lock() if relock else moved
        return real(rig, seat, task, ctx)

    monkeypatch.setitem(agents.HANDLERS, "run_experiment", run_experiment)


def test_rig_records_and_lists_deviations(tmp_path):
    rig = Rig(str(tmp_path), load_rigspec())
    rig.new_slice("S1", "q", "spec")
    rig.record_deviation("S1", "statistician@forecast-lab", "sesoi", 0.01, 0.001, "detected at run")
    [d] = rig.deviations("S1")
    assert (d["field"], d["before"], d["after"]) == ("sesoi", 0.01, 0.001)
    assert rig.deviations("S2") == []


def test_relocked_tampering_is_recorded_and_grades_at_most_c(tmp_path, monkeypatch):
    tamper_before_run(monkeypatch, relock=True)
    rig, ctx, _ = run(fake_llm, root=str(tmp_path / "run"), n_campaigns=1)
    devs = rig.deviations(SLICE)
    assert [(d["field"], d["before"], d["after"]) for d in devs] == [("sesoi", 0.01, 0.001)]
    assert ctx["locked"][SLICE].verify()  # the digest alone cannot see a re-lock; the audit does
    [ev] = [e for e in ctx["evidence"] if e["slice"] == SLICE]
    assert ev["grade"].startswith(("C", "D")), ev["grade"]
    assert not ctx["champion_history"]


def test_silent_tampering_is_recorded_and_the_run_is_refused(tmp_path, monkeypatch):
    tamper_before_run(monkeypatch, relock=False)
    rig, ctx, _ = run(fake_llm, root=str(tmp_path / "run"), n_campaigns=1)
    assert [d["field"] for d in rig.deviations(SLICE)] == ["sesoi"]
    assert rig.stage(SLICE) == "locked"
    refused = rig.db.execute(
        "SELECT note FROM slice_events WHERE slice=? AND to_stage='run' AND ok=0 AND frm='locked'", (SLICE,)
    ).fetchall()
    assert refused and "digest_matches" in refused[0][0]
    with pytest.raises(AssertionError):
        sk.run_test(ctx["locked"][SLICE], lambda g: None, np.random.default_rng(0))


def test_untouched_run_has_no_deviations(tmp_path):
    rig, ctx, _ = run(fake_llm, root=str(tmp_path / "run"), n_campaigns=1)
    assert all(rig.deviations(sid) == [] for sid in ctx["locked"])
