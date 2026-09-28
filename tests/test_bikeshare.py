"""ROADMAP 8c: trip ingest and the bike-share judge, on synthetic trips in the operator's schema (offline)."""

import json

import numpy as np
import pytest

from harness.daemon import load_rigspec, run
from harness.fake_llm import make_fake_llm
from judges import bikeshare as bj
from ops import bikeshare_ingest as ing
from science import kernel as sk
from tests.fixtures.bikeshare.synth import stub_get, trip_zips

N_STATIONS = 20


@pytest.fixture(scope="module")
def data_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("bikeshare") / "chi"
    ing.ingest("chi", str(root), get=stub_get(trip_zips(n_stations=N_STATIONS)), log=lambda *_: None)
    bj.configure(dict(root=str(root)))
    return root


def test_ingest_keys_stations_by_name_and_drops_dockless_trips(data_root):
    manifest = json.loads((data_root / "manifest.json").read_text())["months"]
    assert min(manifest) == "202102" and max(manifest) == "202508"
    m = manifest["202506"]  # the month the operator replaced every station id
    assert m["stations"] == N_STATIONS and m["docked_trips"] < m["trips"]
    panel = bj.load_panel()
    assert len(panel["stations"]) == N_STATIONS  # names link histories across the id switch
    assert panel["published"]["202508"].startswith("2025-09")


def test_ingest_skips_months_already_ingested(data_root):
    seen = []
    ing.ingest("chi", str(data_root), get=stub_get(trip_zips(n_stations=N_STATIONS)), log=seen.append)
    assert seen == []


def test_roles_are_disjoint_and_rotate_through_the_calendar():
    months = [bj.month_add("202201", k) for k in range(60)]
    by_role = {r: [m for m in months if bj.role(m) == r] for r in bj.ROLES}
    assert sum(len(v) for v in by_role.values()) == len(months)  # every month has exactly one role
    for r, ms in by_role.items():
        assert {m[4:] for m in ms} == {f"{k:02d}" for k in range(1, 13)}, r  # every season, by 2026
    assert bj.role("202112") is None
    assert bj.data_keys("primary") != bj.data_keys("replication")
    assert bj.data_keys("extra_replication") == ()  # no fresh months: finite data


def test_point_in_time_view_gives_the_same_forecast(data_root):
    full = bj.load_panel()
    month = bj.DESIGNS["B"]["origins"][-1]
    as_of, _, _ = bj.origin(full, month)
    pit = bj.load_panel(as_of=as_of)  # only the files published by as_of
    assert month not in pit["published"] and bj.month_add(month, -1) not in pit["published"]
    for g in (bj.BASELINE, dict(bj.BASELINE, yoy=True, neighbours=True, trend=True, holidays=True)):
        u1, _, p1 = bj.predict_month(full, full["Y"], month, g)
        u2, _, p2 = bj.predict_month(pit, pit["Y"], month, g)
        a = dict(zip([full["stations"][i] for i in u1], p1, strict=True))
        b = dict(zip([pit["stations"][i] for i in u2], p2, strict=True))
        assert a.keys() == b.keys()
        assert all(np.allclose(a[k], b[k]) for k in a)


def test_leak_canary_flags_a_peek_at_the_target_month_and_nothing_on_the_menu(data_root):
    cache = {}
    assert bj.leak_canary(dict(bj.BASELINE, peek=True), "A", "pilot", cache)
    assert not bj.leak_canary(bj.BASELINE, "A", "pilot", cache)
    for key, (_, change) in bj.MENU.items():
        assert not bj.leak_canary(dict(bj.BASELINE, **change), "A", "pilot", cache), key


def test_positive_control_is_supported_and_the_placebo_is_not(data_root):
    cache, rng = {}, np.random.default_rng(0)

    def locked(t, c=bj.BASELINE):
        return sk.Preregistration(hid="c", statement="c", estimand="e", treatment=t, comparator=c,
                                  primary_metric="WAPE", unit="station", sesoi=0.02, n_boot=300).lock()  # fmt: skip

    def arm(g):
        return bj.evaluate(g, "B", "confirmation", cache)

    assert sk.run_test(locked(bj.POSITIVE_CONTROL, bj.POSITIVE_CONTROL_COMPARATOR), arm, rng)["decision"] == "supported"
    assert sk.run_test(locked(bj.PLACEBO), arm, rng)["decision"] != "supported"


def test_bikeshare_lab_runs_end_to_end_offline(data_root, tmp_path):
    spec = load_rigspec("rigs/bikeshare-lab.json")
    spec["judge_config"] = dict(root=str(data_root))
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec))
    rig, ctx, _ = run(make_fake_llm(bj.MENU), root=str(tmp_path / "run"), n_campaigns=1, rigspec=str(path))
    stages = dict(rig.db.execute("SELECT id, stage FROM slices"))
    assert stages and all(s in {"written", "parked"} for s in stages.values()), stages
    # monthly origins limit power (spec §5): a slice that parks does so for power, never for anything else
    for sid, st in stages.items():
        notes = [n for (n,) in rig.db.execute("SELECT note FROM slice_events WHERE slice=? AND ok=1", (sid,))]
        assert st == "written" or "underpowered at largest design" in notes, (sid, notes)
    for sid, pre in ctx["locked"].items():
        assert pre.verify() and pre.design["origins"] == bj.DESIGNS[pre.design["name"]]["origins"], sid
        assert pre.judge_digest  # judge code and data manifest are locked in
