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


def test_a_request_to_the_owner_pings_once_a_day_however_it_is_worded(spec_dir, tmp_path):
    state = {}
    ask = {"what": "A public events calendar for Chicago", "why": "events move pickups", "how": "city open data",
           "done": "a CSV under data/events"}  # fmt: skip
    first = pi({"picks": [], "lesson": "l", "ask_owner": ask})
    go(spec_dir, tmp_path, first, state)
    go(spec_dir, tmp_path, pi({"picks": [], "lesson": "l", "needs_external_data": "Events"}), state)  # older key
    needs = [a for a in alerts(tmp_path) if a["kind"] == "needs you"]
    assert len(needs) == 1 and "events calendar" in needs[0]["message"] and "mailbox" in needs[0]["message"]


def test_the_pi_is_told_what_data_it_cannot_get(spec_dir, tmp_path):
    prompts, base = [], pi({"picks": [], "lesson": "l"})

    def llm(prompt, system=None, tier=None):
        prompts.append(prompt)
        return base(prompt, system, tier)

    go(spec_dir, tmp_path, llm, {})
    plan = next(p for p in prompts if "Pick up to TWO" in p)
    assert "Weather is out of scope" in plan and "ask_owner" in plan and "weather forecasts, an events" not in plan


def test_a_crash_pings_and_the_supervisor_carries_on(spec_dir, tmp_path):
    def broken(prompt, system=None, tier=None):
        raise ConnectionError("endpoint down")

    state = {}
    assert go(spec_dir, tmp_path, broken, state) == "crashed"
    assert go(spec_dir, tmp_path, broken, state) == "crashed"  # the same outage an hour later: no second ping today
    assert [a["kind"] for a in alerts(tmp_path)] == ["crashed"]
    assert any(k.startswith(f"crash:{labd.dt.date.today()}:") for k in state["seen"])


def test_the_wait_follows_the_wall_clock_when_the_mac_sleeps(monkeypatch):
    clock, naps = [1000.0], []

    def nap(s):
        naps.append(s)
        clock[0] += s if len(naps) > 1 else 5000.0  # the first nap spans a lid closed for 5000 s

    monkeypatch.setattr(labd.time, "time", lambda: clock[0])
    monkeypatch.setattr(labd.time, "sleep", nap)
    labd.wait_until(1000.0 + 3600)
    assert len(naps) == 1 and naps[0] == 60.0  # woke past the target: the next run starts at once


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
    assert "open with the owner" in brief and "Daily weather forecasts" in brief


def test_the_owners_reply_reaches_the_pis_brief(tmp_path):
    from ops import nightshift
    from state.knowledge import Knowledge

    kg_path = str(tmp_path / "kg.db")
    nightshift.main(["reply", "No events calendar exists; keep going", "--rigspec", "rigs/bikeshare-lab.json",
                     "--knowledge", kg_path])  # fmt: skip
    brief = Knowledge(kg_path, load_rigspec("rigs/bikeshare-lab.json")["rig"]).brief(bj.BASELINE, "base", [])
    assert "Replies from the owner" in brief and "No events calendar exists" in brief
    assert "Replies from the owner" not in Knowledge(kg_path, "another-rig").brief(bj.BASELINE, "base", [])


def test_an_empty_reply_is_refused(tmp_path):
    from ops import nightshift

    with pytest.raises(SystemExit):
        nightshift.main(["reply", "  ", "--knowledge", str(tmp_path / "kg.db")])


def test_a_request_is_a_brief_that_stays_open_until_the_owner_answers_it(tmp_path):
    from ops import nightshift
    from state.knowledge import Knowledge

    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    run_id = kg.begin_run("r", "j")
    ask = dict(what="An events calendar", why="events move pickups", how="city open data", done="a CSV in data/")
    rid = kg.request(run_id, 1, ask)
    assert kg.request(run_id, 2, dict(ask, why="asked again")) == rid  # the same ask counts, it is not a new one
    (r,) = kg.requests("open")
    assert (r["asks"], r["how"], r["done"]) == (2, "city open data", "a CSV in data/")
    assert r["id"] in nightshift.request_text(r) and "Done: a CSV in data/" in nightshift.request_text(r)
    kg.reply("None exists for Chicago; drop it", rid)
    assert kg.requests("open") == [] and kg.requests("answered")[0]["reply"].startswith("None exists")
    brief = kg.brief(bj.BASELINE, "base", [])
    assert "open with the owner" not in brief and '(to "An events calendar")' in brief
    with pytest.raises(KeyError):
        kg.reply("hello", "request:nope")


def test_the_cli_lists_requests_and_refuses_an_unknown_one(tmp_path, capsys):
    from ops import nightshift
    from state.knowledge import Knowledge

    kg_path, spec = str(tmp_path / "kg.db"), "rigs/bikeshare-lab.json"
    kg = Knowledge(kg_path, load_rigspec(spec)["rig"])
    kg.request(kg.begin_run("r", "j"), 1, {"what": "An events calendar", "how": "city open data"})
    nightshift.main(["requests", "--rigspec", spec, "--knowledge", kg_path])
    out = capsys.readouterr().out
    assert "[open]" in out and "What: An events calendar" in out and "How: city open data" in out
    with pytest.raises(SystemExit):
        nightshift.main(["reply", "x", "--request", "request:nope", "--rigspec", spec, "--knowledge", kg_path])
