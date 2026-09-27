import pytest

from harness.daemon import load_rigspec
from state.rig import GuardError, Rig


@pytest.fixture
def rig(tmp_path):
    r = Rig(str(tmp_path), load_rigspec())
    r.new_slice("S1", "t", "# t")
    return r


def test_send_never_changes_state(rig):
    rig.send("critic@forecast-lab", "methodologist@forecast-lab", "objection", "S1")
    assert rig.stage("S1") == "question"
    assert rig.pending("methodologist@forecast-lab") == []
    assert rig.inbox("methodologist@forecast-lab")[0]["body"] == "objection"


def test_queue_claim_is_owner_only(rig):
    tid = rig.queue("pi@forecast-lab", "methodologist@forecast-lab", "draft_prereg", "S1", {})
    with pytest.raises(GuardError):
        rig.claim("critic@forecast-lab", tid)
    rig.claim("methodologist@forecast-lab", tid)
    rig.complete("methodologist@forecast-lab", tid, {})
    with pytest.raises(GuardError):
        rig.complete("methodologist@forecast-lab", tid, {})  # already done


def test_workflow_refuses_missing_edge_wrong_role_and_unmet_guard(rig):
    with pytest.raises(GuardError, match="no edge"):
        rig.advance("experimenter@forecast-lab", "S1", "run")
    with pytest.raises(GuardError, match="may not"):
        rig.advance("critic@forecast-lab", "S1", "hypothesis")
    rig.advance("pi@forecast-lab", "S1", "hypothesis")
    with pytest.raises(GuardError, match="unmet guards"):
        rig.advance("methodologist@forecast-lab", "S1", "prereg_draft", checks={"prereg_fields": False})
    refused = rig.db.execute("SELECT count(*) FROM slice_events WHERE ok=0").fetchone()[0]
    assert refused == 3  # refusals are recorded, not silent


def test_supported_result_cannot_be_written_without_replication(rig):
    rig.db.execute("UPDATE slices SET stage='analysed' WHERE id='S1'")
    with pytest.raises(GuardError):
        rig.advance("writer@forecast-lab", "S1", "written", checks={"decision_not_supported": False})
