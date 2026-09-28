"""Every LLM call a run makes is recorded (start + end) for the lab floor; failures are recorded too."""

import json

import pytest

from harness.daemon import run
from harness.fake_llm import fake_llm
from harness.llm import recording_llm


def test_a_run_records_every_llm_call_with_its_seat(tmp_path):
    root = tmp_path / "run"
    run(fake_llm, root=str(root), n_campaigns=1)
    recs = [json.loads(line) for line in (root / "llm_calls.jsonl").read_text().splitlines()]
    starts = {r["call"] for r in recs if r["event"] == "start"}
    ends = [r for r in recs if r["event"] == "end"]
    assert starts and starts == {r["call"] for r in ends}
    assert {r["seat"].split("@")[0] for r in ends} >= {"pi", "methodologist", "critic", "experimenter"}
    assert all(r["prompt"] and r["reply"] and r["s"] >= 0 for r in ends)


def test_a_failed_call_is_recorded_and_still_raises(tmp_path):
    def broken(prompt, system=None, tier=None):
        raise TimeoutError("endpoint down")

    llm = recording_llm(broken, str(tmp_path / "calls.jsonl"))
    with pytest.raises(TimeoutError):
        llm("p", system="You are pi@lab, the pi", tier="reasoning")
    start, end = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert (start["seat"], end["event"], end["error"]) == ("pi@lab", "end", "TimeoutError: endpoint down")


def test_the_models_separate_reasoning_is_recorded_but_seats_get_plain_text(tmp_path):
    from harness.llm import Reply

    llm = recording_llm(lambda p, system=None, tier=None: Reply('{"ok": true}', reasoning="thinking..."),
                        str(tmp_path / "calls.jsonl"))  # fmt: skip
    out = llm("p", system="You are critic@lab, the critic", tier="reasoning")
    assert out == '{"ok": true}' and isinstance(out, str)
    end = json.loads((tmp_path / "calls.jsonl").read_text().splitlines()[-1])
    assert end["reasoning"] == "thinking..." and end["seat"] == "critic@lab"
