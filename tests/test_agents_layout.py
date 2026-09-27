import agents
from harness.daemon import load_rigspec


def test_every_queue_kind_has_a_handler_and_every_role_a_seat():
    roles = {v["role"] for v in load_rigspec()["seats"].values()}
    assert {"pi", "methodologist", "critic", "statistician", "experimenter", "replicator", "writer"} <= roles
    assert set(agents.HANDLERS) == {
        "plan",
        "draft_prereg",
        "review_design",
        "check_implementation",
        "power_controls",
        "run_experiment",
        "analyse",
        "replicate",
        "write",
    }


def test_statistician_is_code_only():
    assert load_rigspec()["seats"]["statistician@forecast-lab"]["kind"] == "code"
