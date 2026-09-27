"""Whole rig, offline, with the deterministic fake LLM: the workflow must reach a terminal stage for every
slice, and the champion may change only through a replicated (grade A) result."""

import json
import os
from pathlib import Path

from api.floor import build_state, build_static
from harness.daemon import run
from harness.fake_llm import fake_llm


def test_one_campaign_end_to_end(tmp_path):
    root = str(tmp_path / "run")
    rig, ctx, transcript = run(fake_llm, root=root, n_campaigns=1)
    stages = dict(rig.db.execute("SELECT id, stage FROM slices").fetchall())
    assert stages and all(s in {"written", "parked"} for s in stages.values()), stages
    for e in ctx["evidence"]:
        assert e["decision"] in {"supported", "harmful", "no_effect", "inconclusive"}
    for h in ctx["champion_history"]:
        ev = next(e for e in ctx["evidence"] if e["slice"] == h["evidence"])
        assert ev["grade"].startswith("A: replicated")
    # every locked prereg still verifies
    for sid, pre in ctx["locked"].items():
        assert pre.verify(), sid
    # the dashboard can read the run
    st = build_state(root)
    assert st["events"] and st["slices"]
    out = build_static(root, str(tmp_path / "replay.html"))
    assert os.path.getsize(out) > 10_000
    assert json.loads(Path(root, "ledger.json").read_text())["campaigns"]
