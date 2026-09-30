"""The Progress view and the daily digest: the lab's progress across runs, read from its own records."""

import datetime as dt
import json

from api.progress import build_progress, digest_text
from harness.daemon import run
from harness.fake_llm import fake_llm
from ops import labd


def lab(tmp_path, n=2):
    (tmp_path / "knowledge").mkdir()
    run(
        fake_llm,
        root=str(tmp_path / "runs" / "r1"),
        n_campaigns=n,
        knowledge=str(tmp_path / "knowledge" / "forecast-lab.db"),
    )
    return tmp_path


def test_progress_lists_every_test_with_its_kernel_decision(tmp_path):
    p = build_progress(str(lab(tmp_path)), "forecast-lab")
    assert p["counts"]["tested"] >= 2 and p["counts"]["runs"] == 1
    decided = [i for i in p["ideas"] if i["point"] is not None]
    assert all(i["decision"] in {"supported", "no_effect", "inconclusive", "harmful"} for i in decided)
    assert [i["n"] for i in p["ideas"]] == list(range(1, len(p["ideas"]) + 1))
    assert p["champion"]["promoted"] and "last year" in p["champion"]["desc"]
    assert p["per_day"] and p["per_day"][-1]["tests"] >= 2


def test_the_digest_says_what_the_lab_did_today_and_how_far_the_goal_is(tmp_path):
    root = lab(tmp_path, n=1)
    (root / "knowledge" / "labd_state.json").write_text(
        json.dumps(dict(goal=dict(point=0.04, lo=0.01, hi=0.07, goal=0.15, met=False)))
    )
    text = digest_text(build_progress(str(root), "forecast-lab"))
    assert "run(s)" in text and "idea(s) tested" in text and "Goal: +4.0% of 15%" in text


def test_one_digest_a_day_after_the_digest_hour(tmp_path, monkeypatch):
    monkeypatch.setattr(labd, "NOTIFY", False)
    root = lab(tmp_path, n=1)
    state, alerts = {}, str(root / "knowledge" / "alerts.jsonl")
    morning = dt.datetime(2026, 10, 1, 9, 0)
    evening = morning.replace(hour=22)
    assert labd.maybe_digest(state, alerts, str(root), "forecast-lab", now=morning) is None
    assert labd.maybe_digest(state, alerts, str(root), "forecast-lab", now=evening)
    assert labd.maybe_digest(state, alerts, str(root), "forecast-lab", now=evening) is None
    assert (root / "knowledge" / "digest-2026-10-01.md").exists()
