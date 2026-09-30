"""The continuous lab supervisor: runs the lab, pings once per event (stall, data request, crash, goal), stops at the
goal. Offline: fake LLM, synthetic trips, notifications off."""

import json

import pytest

from harness.daemon import load_rigspec
from harness.fake_llm import make_fake_llm
from judges import bikeshare as bj
from ops import bikeshare_ingest as ing
from ops import labd
from tests.fixtures.bikeshare.synth import stub_get, trip_zips


@pytest.fixture(scope="module")
def spec_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("labd")
    ing.ingest("chi", str(d / "chi"), get=stub_get(trip_zips()), log=lambda *_: None)
    return d


def spec_file(d, tmp_path, goal=0.15):
    spec = load_rigspec("rigs/bikeshare-lab.json")
    spec["judge_config"] = dict(root=str(d / "chi"))
    spec["decision_standards"]["goal"]["relative_wape_reduction"] = goal
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec))
    return str(p)


def pi(reply):
    base = make_fake_llm(bj.MENU)

    def llm(prompt, system=None, tier=None):
        if "pi@" in (system or "") and "Pick up to TWO" in prompt:
            return json.dumps(reply)
        return base(prompt, system, tier)

    return llm


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(labd, "NOTIFY", False)


def alerts(tmp_path):
    p = tmp_path / "alerts.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def go(spec_dir, tmp_path, llm, state, goal=0.15):
    return labd.cycle(llm, spec_file(spec_dir, tmp_path, goal), str(tmp_path / "kg.db"), str(tmp_path / "runs"), 1,
                      state, str(tmp_path / "alerts.jsonl"), max_idle=2, refresh=False, log=lambda *_: None)  # fmt: skip


def test_a_stall_pings_once(spec_dir, tmp_path):
    idle, state = pi({"picks": [], "lesson": "nothing"}), {}
    for _ in range(3):
        assert go(spec_dir, tmp_path, idle, state) == "running"
    stalls = [a for a in alerts(tmp_path) if a["kind"] == "stalled"]
    assert state["idle"] == 3 and len(stalls) == 1


def test_a_data_request_pings_once_a_day_however_it_is_worded(spec_dir, tmp_path):
    state = {}
    first = pi({"picks": [], "lesson": "l", "needs_external_data": "Daily weather forecasts for Chicago"})
    go(spec_dir, tmp_path, first, state)
    go(spec_dir, tmp_path, pi({"picks": [], "lesson": "l", "needs_external_data": "Weather and events"}), state)
    needs = [a for a in alerts(tmp_path) if a["kind"] == "needs data"]
    assert len(needs) == 1 and "weather" in needs[0]["message"]


def test_a_crash_pings_and_the_supervisor_carries_on(spec_dir, tmp_path):
    def broken(prompt, system=None, tier=None):
        raise ConnectionError("endpoint down")

    assert go(spec_dir, tmp_path, broken, {}) == "crashed"
    assert [a["kind"] for a in alerts(tmp_path)] == ["crashed"]


def test_the_lab_stops_at_its_goal(spec_dir, tmp_path):
    idle, state = pi({"picks": [], "lesson": "l"}), {}
    assert go(spec_dir, tmp_path, idle, state, goal=0.15) == "running"  # the baseline does not beat itself by 15%
    assert go(spec_dir, tmp_path, idle, state, goal=-1.0) == "goal"
    assert state["goal"]["met"] and [a["kind"] for a in alerts(tmp_path)][-1] == "goal reached"


def test_the_launchd_job_can_find_pyenv():
    xml = labd.launchd_plist(3600)
    assert ".pyenv/bin" in xml and ".pyenv/shims" in xml and "make labd EVERY=3600" in xml
    assert "<key>SuccessfulExit</key><false/>" in xml  # restarted after a failure, not after reaching the goal


def test_open_requests_are_in_the_pis_brief_so_it_does_not_ask_again(tmp_path):
    from state.knowledge import Knowledge

    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run_id = kg.begin_run("r", "j")
    kg.request(run_id, 1, "Daily weather forecasts for Chicago")
    brief = kg.brief(bj.BASELINE, "base", [])
    assert "already sent to the owner" in brief and "Daily weather forecasts" in brief
