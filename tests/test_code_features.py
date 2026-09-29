"""ROADMAP 5b: seat-written features run in the judge's sandbox on point-in-time views; a code rewrite of a menu
change reproduces the menu result, and code that is nondeterministic, constant or forbidden is caught before lock."""

import json

import numpy as np
import pytest

from agents.common import describe_config
from judges import bikeshare as bj
from ops import bikeshare_ingest as ing
from tests.fixtures.bikeshare.synth import stub_get, trip_zips

HOLIDAYS_AS_CODE = """
import datetime as dt
import numpy as np

def _nth(year, month, weekday, n):
    days = [dt.date(year, month, d) for d in range(1, 32) if _valid(year, month, d)]
    return [d for d in days if d.weekday() == weekday][n]

def _valid(y, m, d):
    try:
        dt.date(y, m, d)
        return True
    except ValueError:
        return False

def _holidays(y):
    fixed = [dt.date(y, m, d) for m, d in ((1, 1), (6, 19), (7, 4), (11, 11), (12, 25))]
    rules = [(1, 0, 2), (2, 0, 2), (5, 0, -1), (9, 0, 0), (10, 0, 1), (11, 3, 3)]
    return set(fixed + [_nth(y, m, wd, n) for m, wd, n in rules])

def features(view):
    dates = [dt.date.fromordinal(int(o)) for o in view["target_dates"]]
    hols = _holidays(dates[0].year)
    hol = np.array([d in hols for d in dates], float)
    adj = np.array([any(d + dt.timedelta(k) in hols for k in (-1, 1)) for d in dates], float)
    s = int(view["n_stations"])
    return np.column_stack([np.tile(hol, s), np.tile(adj, s)])
"""


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    r = tmp_path_factory.mktemp("code") / "chi"
    ing.ingest("chi", str(r), get=stub_get(trip_zips()), log=lambda *_: None)
    bj.configure(dict(root=str(r)))
    return r


def code(name, source):
    return dict(bj.BASELINE, code=[dict(name=name, source=source)])


def test_a_code_rewrite_of_a_menu_change_reproduces_its_result(root):
    cache = {}
    menu = bj.evaluate(dict(bj.BASELINE, holidays=True), "A", "confirmation", cache)
    written = bj.evaluate(code("holidays", HOLIDAYS_AS_CODE), "A", "confirmation", cache)
    assert written["origins"] == menu["origins"]
    assert np.allclose(written["abs_err"], menu["abs_err"], rtol=1e-6, atol=1e-6)


def test_code_features_cannot_leak(root):
    assert not bj.leak_canary(code("holidays", HOLIDAYS_AS_CODE), "A", "pilot", {})


def test_checks_pass_good_code_and_catch_bad_code(root):
    assert bj.check_code(HOLIDAYS_AS_CODE)["ok"]
    noisy = (
        "import numpy as np\ndef features(view):\n    return np.random.default_rng().normal(size=int(view['n_rows']))\n"
    )
    assert bj.check_code(noisy)["error"] == "different output on a second run"
    constant = "import numpy as np\ndef features(view):\n    return np.ones(int(view['n_rows']))\n"
    assert "constant" in bj.check_code(constant)["error"]
    path = str(root / "manifest.json")
    snoop = (
        f"import numpy as np\ndef features(view):\n    open({path!r}).read()\n    return np.ones(int(view['n_rows']))\n"
    )
    assert "sandbox" in bj.check_code(snoop)["error"]


def test_code_is_described_by_name_and_hash(root):
    text = describe_config(bj, code("holiday flags", HOLIDAYS_AS_CODE))
    assert text.startswith(bj.BASELINE_DESC) and "seat-written feature 'holiday flags' (code sha " in text


def test_the_evaluation_key_follows_the_data_not_the_judge_code(root):
    before = bj.evaluation_key()
    manifest = root / "manifest.json"
    m = json.loads(manifest.read_text())
    m["touched"] = True
    manifest.write_text(json.dumps(m))
    try:
        assert bj.evaluation_key() != before
    finally:
        m.pop("touched")
        manifest.write_text(json.dumps(m, indent=1, sort_keys=True))
