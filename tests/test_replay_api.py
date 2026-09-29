"""The lab floor's replay: one ordered list of beats built from a run's own records, served over HTTP."""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from api.floor import Handler
from api.replay import build_replay, list_runs
from harness.daemon import run
from harness.fake_llm import fake_llm


@pytest.fixture(scope="module")
def run_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("runs") / "demo"
    run(fake_llm, root=str(root), n_campaigns=2)
    return root


def test_beats_are_one_ordered_sequence_from_the_runs_records(run_root):
    rep = build_replay(str(run_root))
    beats = rep["beats"]
    assert beats and [b["at"] for b in beats] == sorted(b["at"] for b in beats)
    assert [b["ts"] for b in beats] == sorted(b["ts"] for b in beats)
    kinds = {b["kind"] for b in beats}
    assert {"think", "queue", "compute", "lock", "refuse"} <= kinds
    thinks = [b for b in beats if b["kind"] == "think"]
    assert all(str(b["call"]) in {str(k) for k in rep["calls"]} for b in thinks)
    assert {b["actor"] for b in thinks} >= {"pi", "methodologist", "critic", "experimenter"}
    plan_tasks = {b["task_id"] for b in thinks if b["task"] == "plan"}
    assert max(b["campaign"] for b in beats) == len(plan_tasks) == 2  # a retried plan call is not a new campaign
    assert rep["total"] == pytest.approx(beats[-1]["at"] + beats[-1]["dur"])


def test_experiments_carry_their_per_month_results(run_root):
    rep = build_replay(str(run_root))
    runs = [s for s in rep["slices"] if s["run"]]
    assert runs
    s = runs[0]
    assert len(s["run"]["rel"]) == len(s["locked"]["months"]) and s["decision"]["decision"]
    assert any(b["kind"] == "compute" and b["task"] == "run_experiment" and b["slice"] == s["id"] for b in rep["beats"])


def test_a_run_without_a_call_log_still_replays(run_root, tmp_path):
    import shutil

    old = tmp_path / "old"
    shutil.copytree(run_root, old)
    (old / "llm_calls.jsonl").unlink()
    rep = build_replay(str(old))
    assert rep["beats"] and not any(b["kind"] == "think" for b in rep["beats"])


def test_http_serves_runs_and_replays_and_refuses_paths(run_root):
    Handler.root = str(run_root)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        runs = json.load(urllib.request.urlopen(f"{base}/api/runs"))
        assert runs[0]["name"] == "demo" and runs[0]["recorded"]
        rep = json.load(urllib.request.urlopen(f"{base}/api/replay?run=demo"))
        assert rep["beats"]
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{base}/api/replay?run=../../etc")
        assert e.value.code == 404
        with urllib.request.urlopen(f"{base}/api/events?run=demo", timeout=10) as r:
            assert r.headers["Content-Type"] == "text/event-stream"
            assert r.readline().startswith(b"event: replay")
    finally:
        srv.shutdown()


def test_list_runs_marks_recorded_runs(run_root):
    assert list_runs(str(run_root.parent))[0]["recorded"] is True
