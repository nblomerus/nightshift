"""ROADMAP item 4: the judge's SHA-256 is locked into the prereg and stamped on every result; a judge edited
after lock makes the rig refuse `run` / `analysed` with a logged refusal."""

import shutil

import pytest

import agents
import agents.common as common
from harness.daemon import run
from harness.fake_llm import fake_llm
from judges import forecast as fh
from judges import forecast_lab

SLICE = "C1-S1-last_year_window"


@pytest.fixture
def judge_copy(tmp_path, monkeypatch):
    """Point the digest at a copy of the judge, so a test can edit it without touching judges/."""
    path = tmp_path / "forecast.py"
    shutil.copy(fh.__file__, path)
    monkeypatch.setattr(forecast_lab, "FILES", (str(path), forecast_lab.__file__))
    return path


def edit_judge_before(monkeypatch, kind, path):
    real = agents.HANDLERS[kind]

    def handler(rig, seat, task, ctx):
        if task["slice"] == SLICE:
            path.write_text(path.read_text() + "\n# edited after lock\n")
        return real(rig, seat, task, ctx)

    monkeypatch.setitem(agents.HANDLERS, kind, handler)


def refusals(rig, frm, to):
    q = "SELECT note FROM slice_events WHERE slice=? AND frm=? AND to_stage=? AND ok=0"
    return [n for (n,) in rig.db.execute(q, (SLICE, frm, to))]


def test_judge_edited_between_lock_and_run_is_refused(tmp_path, monkeypatch, judge_copy):
    edit_judge_before(monkeypatch, "run_experiment", judge_copy)
    rig, ctx, _ = run(fake_llm, root=str(tmp_path / "run"), n_campaigns=1)
    assert rig.stage(SLICE) == "locked"
    [note] = refusals(rig, "locked", "run")
    assert "judge_unchanged" in note
    assert rig.read_proof(SLICE, "run_result.json") is None  # the edited judge never ran


def test_judge_edited_between_run_and_analysis_is_refused(tmp_path, monkeypatch, judge_copy):
    edit_judge_before(monkeypatch, "analyse", judge_copy)
    rig, ctx, _ = run(fake_llm, root=str(tmp_path / "run"), n_campaigns=1)
    assert rig.stage(SLICE) == "run"
    [note] = refusals(rig, "run", "analysed")
    assert "judge_unchanged" in note
    assert rig.read_proof(SLICE, "decision.json") is None


def test_judge_digest_is_locked_and_stamped_on_every_result(tmp_path):
    rig, ctx, _ = run(fake_llm, root=str(tmp_path / "run"), n_campaigns=1)
    digest = common.judge_digest(forecast_lab)
    assert ctx["locked"] and all(pre.judge_digest == digest for pre in ctx["locked"].values())
    for sid in ctx["locked"]:
        assert rig.read_proof(sid, "prereg_locked.json")["body"]["judge_digest"] == digest
        for name in ("run_result.json", "decision.json", "replication.json"):
            proof = rig.read_proof(sid, name)
            if proof is not None:
                assert proof["judge_digest"] == digest, (sid, name)
