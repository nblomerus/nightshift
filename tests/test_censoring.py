"""ROADMAP 8d: GBFS snapshots -> station-day censoring; the judge scores only uncensored days in masked months."""

import json
import os
import time

import numpy as np
import pytest

from harness.daemon import load_rigspec
from judges import bikeshare as bj
from ops import bikeshare_ingest as ing
from ops import gbfs_reduce as gr
from state.rig import GuardError, Rig
from tests.fixtures.bikeshare.synth import expected_pickups, gbfs_day, month_dates, stub_get, trip_zips

NAMES = expected_pickups(n_stations=20)[0]


def test_reduce_day_counts_empty_minutes_and_coverage(tmp_path):
    gbfs_day(str(tmp_path), "2026-10-01", {"a": "A St", "b": "B St", "c": "C St"},
             empty_polls={"a": 13}, missing_polls={"b": 58})  # fmt: skip
    info = gr.station_names(str(tmp_path), "2026-10-01")
    out = gr.reduce_day(str(tmp_path / "2026-10-01.csv.gz"), info).set_index("station")
    assert out.loc["A St", "empty_minutes"] == 65 and out.loc["A St", "coverage"] == 1.0
    assert out.loc["B St", "coverage"] == pytest.approx(230 / 288)
    assert out.loc["C St", "empty_minutes"] == 0


def test_reduce_all_skips_a_corrupted_day_and_keeps_the_rest(tmp_path):
    stations = {"a": "A St", "b": "B St"}
    gbfs_day(str(tmp_path), "2026-10-01", stations)
    gbfs_day(str(tmp_path), "2026-10-03", stations)
    (tmp_path / "2026-10-02.csv.gz").write_bytes(b"not actually gzip")  # the collector was killed mid-write
    out = tmp_path / "out" / "censor_day.csv.gz"
    table, skipped = gr.reduce_all(str(tmp_path), str(out))
    assert set(table["date"]) == {"2026-10-01", "2026-10-03"}  # the good days still build the table
    assert len(skipped) == 1 and "2026-10-02" in skipped[0][0] and skipped[0][1]


def test_reduce_all_does_not_rewrite_an_identical_table(tmp_path):
    gbfs_day(str(tmp_path), "2026-10-01", {"a": "A St"})
    out = tmp_path / "censor_day.csv.gz"
    gr.reduce_all(str(tmp_path), str(out))
    mtime = out.stat().st_mtime
    time.sleep(0.05)
    gr.reduce_all(str(tmp_path), str(out))  # nothing in the source changed
    assert out.stat().st_mtime == mtime  # so the file (and its mtime) stays untouched


@pytest.fixture(scope="module")
def masked_root(tmp_path_factory):
    """The synthetic system, with snapshots for every day of one confirmation month: station 0 is empty for 70
    minutes on day 1, station 1 is seen by only 80 % of polls on day 2, station 2 never appears on day 3."""
    root = tmp_path_factory.mktemp("censor") / "chi"
    ing.ingest("chi", str(root), get=stub_get(trip_zips()), log=lambda *_: None)
    gbfs = tmp_path_factory.mktemp("gbfs")
    ids = {f"CHI{i:05d}": n for i, n in enumerate(NAMES)}
    for d in month_dates("202507"):
        present = {s: n for s, n in ids.items() if not (d.day == 3 and s == "CHI00002")}
        gbfs_day(str(gbfs), d.isoformat(), present,
                 empty_polls={"CHI00000": 14} if d.day == 1 else {},
                 missing_polls={"CHI00001": 58} if d.day == 2 else {})  # fmt: skip
    gr.reduce_all(str(gbfs), str(root / "censor_day.csv.gz"))
    bj.configure(dict(root=str(root)))
    return root


def test_planted_stockouts_and_gaps_are_censored(masked_root):
    panel = bj.load_panel()
    day = {d.isoformat(): i for i, d in enumerate(panel["days"])}
    s = {n: i for i, n in enumerate(panel["stations"])}
    C = panel["C"]
    assert C[s[NAMES[0]], day["2025-07-01"]] == bj.CENSORED  # empty 70 minutes
    assert C[s[NAMES[1]], day["2025-07-02"]] == bj.CENSORED  # 80 % coverage: unknown
    assert C[s[NAMES[2]], day["2025-07-03"]] == bj.CENSORED  # not seen at all that day: unknown
    assert C[s[NAMES[3]], day["2025-07-01"]] == bj.OK
    assert bj.masked(panel, "202507") and not bj.masked(panel, "202502")


def test_masking_removes_the_same_station_days_from_both_arms(masked_root):
    cache, panel = {}, bj.load_panel()
    base = bj.evaluate(bj.BASELINE, "A", "confirmation", cache)
    other = bj.evaluate(dict(bj.BASELINE, station_dow=True), "A", "confirmation", cache)
    assert np.array_equal(base["actual"], other["actual"])  # the pair stays paired
    j = base["origins"].index("202507")
    assert base["masked"][j] and base["censor_rate"][j] > 0
    days = [i for i, d in enumerate(panel["days"]) if d.strftime("%Y%m") == "202507"]
    s0 = panel["stations"].index(NAMES[0])
    assert base["actual"][s0, j] == panel["Y"][s0, days].sum() - panel["Y"][s0, days[0]]


def test_a_latent_demand_treatment_needs_every_scored_month_masked(masked_root):
    censor = dict(bj.BASELINE, censor=True)
    assert bj.design_checks(bj.BASELINE, "A", "confirmation") == {"censor_mask_available": True}
    assert bj.design_checks(censor, "A", "confirmation") == {"censor_mask_available": False}
    assert not bj.leak_canary(censor, "A", "pilot", {})


def test_rig_refuses_to_pass_controls_without_the_mask(tmp_path):
    spec = load_rigspec("rigs/bikeshare-lab.json")
    rig = Rig(str(tmp_path), spec)
    rig.new_slice("S1", "q", "spec")
    path = [("pi", "hypothesis"), ("methodologist", "prereg_draft"), ("methodologist", "design_review"),
            ("critic", "approved_design")]  # fmt: skip
    for seat, to in path:
        rig.advance(rig.seat_for(seat), "S1", to, checks={"prereg_fields": True})
    rig.advance(rig.seat_for("experimenter"), "S1", "implementation_checked",
                checks={"implementable_exactly": True, "statement_from_config": True, "code_checked": True})  # fmt: skip
    ok = {"p_decisive>=0.8": True, "controls_admissible": True}
    with pytest.raises(GuardError, match="censor_mask_available"):
        rig.advance(rig.seat_for("statistician"), "S1", "controls_passed", checks=dict(ok, censor_mask_available=False))
    assert json.loads(json.dumps(spec["decision_standards"]["censoring"]))["empty_minutes"] == 60


def _one_station_root(tmp_path, name):
    """A minimal ingested system (3 months, 1 station) plus a GBFS collector directory, for load_panel cache tests."""
    root = tmp_path / name
    zips = trip_zips(first="202102", last="202104", n_stations=1)
    ing.ingest("chi", str(root), get=stub_get(zips), log=lambda *_: None)
    return root, tmp_path / f"{name}-gbfs"


def test_load_panel_caches_on_censor_content_not_mtime(tmp_path):
    root, gbfs = _one_station_root(tmp_path, "cache")
    station = {"CHI00000": expected_pickups(n_stations=1)[0][0]}
    gbfs_day(str(gbfs), "2025-07-01", station)
    censor = root / "censor_day.csv.gz"
    gr.reduce_all(str(gbfs), str(censor))
    bj.configure(dict(root=str(root)))
    panel1 = bj.load_panel()

    os.utime(censor, (time.time() + 10_000, time.time() + 10_000))  # a refresh_data-style rewrite: mtime moves
    panel2 = bj.load_panel()
    assert panel2 is panel1  # content didn't change, so this must be the same cached panel, not a new one

    gbfs_day(str(gbfs), "2025-07-02", station)  # a real change: a new day is now covered
    gr.reduce_all(str(gbfs), str(censor))
    panel3 = bj.load_panel()
    assert panel3 is not panel1  # content changed, so a fresh panel is expected


def test_load_panel_cache_stays_bounded_across_reconfigurations(tmp_path):
    for i in range(bj._PANELS_MAX + 3):
        root, _ = _one_station_root(tmp_path, f"bound{i}")
        bj.configure(dict(root=str(root)))
        assert len(bj._PANELS) <= bj._PANELS_MAX
