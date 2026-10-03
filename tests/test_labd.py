"""The continuous lab supervisor: runs the lab, pings once per event (stall, data request, crash, goal), stops at the
goal. Offline: fake LLM, synthetic trips, notifications off."""

import json

import pytest

from agents.pi import handler as pi_handler
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


def test_a_pi_that_plans_nothing_is_not_allowed_to_stall_the_lab(spec_dir, tmp_path):
    asked, base = [], pi({"picks": [], "lesson": "nothing is worth testing"})

    def idle(prompt, system=None, tier=None):
        if "pi@" in (system or "") and "Pick up to TWO" in prompt:
            asked.append(prompt)
        return base(prompt, system, tier)

    state, streak = {}, []
    for _ in range(3):
        assert go(spec_dir, tmp_path, idle, state) == "running"
        streak.append(state["idle"])
    assert streak == [1, 0, 1]  # after an idle run the next one must test something, and does
    assert "MUST pick at least one" in asked[1] and asked[2].endswith(pi_handler.STALL_RETRY)  # told, then asked again
    assert "If nothing is worth testing, pick none" in asked[0]  # an empty plan is fine while the lab is not idle


def test_with_nothing_left_to_try_the_lab_asks_the_owner_and_reports_the_stall_daily(spec_dir, tmp_path, monkeypatch):
    from state.knowledge import Knowledge

    monkeypatch.setattr(bj, "MENU", {})  # nothing listed, and the PI proposes no new idea
    idle, state = pi({"picks": [], "lesson": "nothing"}), {}
    for _ in range(3):
        assert go(spec_dir, tmp_path, idle, state) == "running"
    kinds = [a["kind"] for a in alerts(tmp_path)]
    assert state["idle"] == 3 and kinds.count("stalled") == 1  # the same stall, the same day: one ping
    (req,) = Knowledge(str(tmp_path / "kg.db"), load_rigspec("rigs/bikeshare-lab.json")["rig"]).requests("open")
    assert req["what"].startswith("Direction") and req["asks"] == 2  # filed by the circuit breaker, then re-asked
    assert kinds.count("needs you") == 1


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


def test_a_request_asked_inside_the_cooldown_is_pinged_when_it_ends(spec_dir, tmp_path):
    ask = {"what": "Planned station openings", "why": "w", "how": "h", "done": "d"}
    state = {"last_data_ping": labd.time.time() - 3600}  # pinged an hour ago about something else
    go(spec_dir, tmp_path, pi({"picks": [], "lesson": "l", "ask_owner": ask}), state)
    assert not [a for a in alerts(tmp_path) if a["kind"] == "needs you"]  # inside the cooldown
    state["last_data_ping"] -= labd.DATA_PING_EVERY  # a day later; the PI does not ask again while it is open
    go(spec_dir, tmp_path, pi({"picks": [], "lesson": "l"}), state)
    needs = [a for a in alerts(tmp_path) if a["kind"] == "needs you"]
    assert len(needs) == 1 and "Planned station openings" in needs[0]["message"]
    state["last_data_ping"] -= labd.DATA_PING_EVERY  # and it is not pinged again unless asked again
    go(spec_dir, tmp_path, pi({"picks": [], "lesson": "l"}), state)
    assert len([a for a in alerts(tmp_path) if a["kind"] == "needs you"]) == 1


def test_a_failure_after_the_run_is_reported_not_fatal(spec_dir, tmp_path, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("goal check broke")

    monkeypatch.setattr(labd, "goal_status", broken)
    assert go(spec_dir, tmp_path, pi({"picks": [], "lesson": "l"}), {}) == "crashed"
    (a,) = [a for a in alerts(tmp_path) if a["kind"] == "crashed"]
    assert "goal check broke" in a["message"]


def test_the_state_file_is_written_atomically_and_a_corrupt_one_is_set_aside(tmp_path):
    path, al = str(tmp_path / "labd_state.json"), str(tmp_path / "alerts.jsonl")
    labd.save_state(path, {"runs": 3})
    assert labd.load_state(path, al) == {"runs": 3} and not (tmp_path / "labd_state.json.tmp").exists()
    (tmp_path / "labd_state.json").write_text('{"runs": 3, "idl')  # killed mid-write by an older version
    assert labd.load_state(path, al) == {}
    assert (tmp_path / "labd_state.json.corrupt").exists() and alerts(tmp_path)[-1]["kind"] == "crashed"


def test_the_watchdog_restarts_a_process_that_stops_making_progress(tmp_path, monkeypatch):
    import threading

    exited = threading.Event()
    monkeypatch.setattr(labd, "_BEAT", [labd.time.monotonic() - 10])  # last progress 10 s ago
    labd.watchdog(str(tmp_path / "alerts.jsonl"), limit=5, every=0.01, exit=lambda code: exited.set())
    assert exited.wait(2) and alerts(tmp_path)[-1]["kind"] == "hung"
    labd.time.sleep(0.2)  # a watchdog whose exit() did not end the process must still stop: one alert per hang
    assert [a["kind"] for a in alerts(tmp_path)].count("hung") == 1
    assert labd.NOTIFY is False  # tests never raise desktop notifications (tests/conftest.py)


def test_the_heartbeat_wrapper_keeps_the_llms_streaming_signature():
    import inspect

    def llm(prompt, system=None, tier=None, on_progress=None):
        return "ok"

    before = labd._BEAT[0]
    wrapped = labd.beating(llm)
    assert "on_progress" in inspect.signature(wrapped).parameters and wrapped("p") == "ok"
    assert labd._BEAT[0] >= before


def test_a_trickling_stream_cannot_outlive_its_deadline():
    import time as _time

    from harness.llm import read_stream

    lines = (b'data: {"choices": [{"delta": {"content": "x"}}]}' for _ in range(10**6))
    with pytest.raises(TimeoutError):
        read_stream(lines, deadline=_time.monotonic() - 1)


def test_restated_lessons_fold_into_one_and_idle_runs_are_counted(tmp_path):
    from state.knowledge import Knowledge

    kg = Knowledge(str(tmp_path / "kg.db"), "lab")
    r1 = kg.begin_run("r1", "j", started=1.0)
    for k in range(6):
        kg.lesson(r1, k, f"(after campaign {k}) Non-positive exploratory screens remain a hard gate for listed changes "
                         f"variant {k}")  # fmt: skip
    kg.lesson(r1, 7, "Composite features of tight positive results are worth a confirmatory slot")
    ls = kg.lessons(8)
    assert len(ls) == 2 and ls[0].endswith("(stated 6 times)") and ls[1].startswith("Composite")
    assert len(kg.lessons(8, distinct=False)) == 7
    assert kg.runs_without_tests() == 1  # r1 tested nothing
    kg.test(r1, 1, "S1", change="x", change_desc="x", treatment={"a": 1}, comparator={}, comparator_desc="b",
            judge="j", data_key="k", design="B", decision=None, grade=None, stage="parked")  # fmt: skip
    r2 = kg.begin_run("r2", "j", started=2.0)
    assert kg.runs_without_tests() == 1 and kg.runs_without_tests(exclude=r2) == 0
