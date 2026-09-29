"""ROADMAP 5a: seat-written code runs sandboxed: no network, no subprocesses, no files outside its scratch directory,
bounded time; outputs are checked for shape and finiteness."""

import pathlib

import numpy as np
import pytest

from judges.sandbox import SandboxError, run_plugin

VIEW = dict(n_rows=np.array(6), hist=np.arange(12, dtype=float).reshape(3, 4))

GOOD = """
import numpy as np
def features(view):
    return np.repeat(view["hist"].mean(1), 2)
"""


def test_a_plain_plugin_runs_and_returns_its_features():
    [out] = run_plugin(GOOD, [VIEW])
    assert out.shape == (6, 1) and np.allclose(out[:, 0], [1.5, 1.5, 5.5, 5.5, 9.5, 9.5])


def test_several_views_in_one_process():
    outs = run_plugin(GOOD, [VIEW, dict(VIEW, hist=VIEW["hist"] * 2)])
    assert np.allclose(outs[1], outs[0] * 2)


@pytest.mark.parametrize(
    "body",
    [
        "import socket\n    socket.create_connection(('example.com', 80))",
        "import urllib.request\n    urllib.request.urlopen('http://example.com')",
        "import subprocess\n    subprocess.run(['ls'])",
        "import os\n    os.system('ls')",
        "open('/etc/passwd').read()",
        "open('../escape.txt', 'w').write('x')",
        f"open({str(pathlib.Path(__file__).resolve().parents[1] / 'rigs' / 'bikeshare-lab.json')!r}).read()",  # the repo
    ],
)
def test_forbidden_things_are_refused(body):
    src = f"import numpy as np\ndef features(view):\n    {body}\n    return np.zeros(6)\n"
    with pytest.raises(SandboxError, match="sandbox|not allowed|Operation not permitted|denied"):
        run_plugin(src, [VIEW])


def test_scratch_files_are_allowed():
    src = "import numpy as np\ndef features(view):\n    open('tmp.txt', 'w').write('ok')\n    return np.zeros(6)\n"
    assert run_plugin(src, [VIEW])[0].shape == (6, 1)


def test_a_slow_plugin_is_stopped():
    src = "import time\ndef features(view):\n    time.sleep(30)\n"
    with pytest.raises(SandboxError, match="timed out"):
        run_plugin(src, [VIEW], timeout=2)


@pytest.mark.parametrize(
    ("src", "match"),
    [
        ("import numpy as np\ndef features(view):\n    return np.zeros(5)\n", "rows=6"),
        ("import numpy as np\ndef features(view):\n    return np.full(6, np.nan)\n", "NaN"),
        ("import numpy as np\ndef features(view):\n    return np.zeros((6, 20))\n", "k<=8"),
        ("def feature(view):\n    return 1\n", "no features"),
        ("def features(view):\n    raise ValueError('boom')\n", "boom"),
    ],
)
def test_unusable_output_is_refused(src, match):
    with pytest.raises(SandboxError, match=match):
        run_plugin(src, [VIEW])
