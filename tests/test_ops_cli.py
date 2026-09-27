import os
from pathlib import Path

from ops.nightshift import main


def test_cli_run_and_build_replay(tmp_path):
    root = str(tmp_path / "run")
    main(["run", "--fake-llm", "--campaigns", "1", "--root", root])
    out = str(tmp_path / "replay.html")
    main(["floor", "build", root, out])
    html = Path(out).read_text()
    assert "Nightshift · lab floor" in html and "/*__RIG_DATA__*/null" not in html
    assert os.path.exists(os.path.join(root, "rig.db"))
