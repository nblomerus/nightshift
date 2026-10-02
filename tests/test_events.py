"""ROADMAP 8g: street events from CDOT permits, known from their processed date (docs/specs/bikeshare-events.md).
Offline: synthetic trips with planted events, permits served through a stub Socrata API."""

import datetime as dt
import gzip
import json

import numpy as np
import pandas as pd
import pytest

from judges import bikeshare as bj
from ops import bikeshare_ingest as ing
from ops import events_ingest as ev
from science import kernel as sk
from tests.fixtures.bikeshare.synth import permit_rows, street_events, stub_get, stub_socrata, trip_zips

N_STATIONS = 20


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    base = tmp_path_factory.mktemp("events")
    events = street_events(n_stations=N_STATIONS)
    ing.ingest("chi", str(base / "bikeshare" / "chi"), get=stub_get(trip_zips(n_stations=N_STATIONS, events=events)),
               log=lambda *_: None)  # fmt: skip
    ev.ingest(
        "chi",
        str(base / "events" / "chi"),
        get=stub_socrata(permit_rows(events)),
        log=lambda *_: None,
        today=dt.date(2021, 1, 1),
    )  # fmt: skip  (older than every origin: the backtest snapshot)
    bj.configure(dict(root=str(base / "bikeshare" / "chi")))
    yield base, events
    bj.CONFIG["events_root"] = None


def test_the_ingest_keeps_a_dated_snapshot_without_status_and_drops_undatable_permits(lab, monkeypatch):
    base, events = lab
    root = base / "events" / "chi"
    man = json.loads((root / "manifest.json").read_text())["snapshots"]
    ((name, snap),) = man.items()
    assert name == "permits-20210101.csv.gz" and snap["rows"] == len(events) and snap["dropped"] == 2
    with gzip.open(root / name, "rt") as f:
        cols = pd.read_csv(f).columns
    assert "closure" in cols and not any("status" in c or "milestone" in c for c in cols)  # never read: not kept
    calls = []
    ev.ingest("chi", str(root), get=lambda u: calls.append(u), log=lambda *_: None, today=dt.date(2021, 1, 1))
    assert calls == []  # today's snapshot exists
    assert ev.due(str(root), today=dt.date(2021, 1, 29)) and not ev.due(str(root), today=dt.date(2021, 1, 20))
    monkeypatch.setattr(ev, "PAGE", 7)  # paging: every row arrives however small the pages are
    assert len(ev.fetch_permits("chi", stub_socrata(permit_rows(events)))) == len(events) + 2


def test_an_event_counts_only_once_its_permit_is_processed_and_within_400_m():
    day = dt.date(2024, 7, 10)
    events = pd.DataFrame([dict(processed=dt.date(2024, 5, 1), start=day, end=day, lat=41.9, lon=-87.6)])
    lat = np.array([41.9 + 399 / 111_320, 41.9 + 401 / 111_320])
    lon = np.array([-87.6, -87.6])
    n = bj.event_counts(lat, lon, [day, day + dt.timedelta(1)], events, known_before=dt.date(2024, 5, 2))
    assert n.tolist() == [[1, 0], [0, 0]]  # 399 m on the day: yes; 401 m, or the next day: no
    assert not bj.event_counts(lat, lon, [day], events, known_before=dt.date(2024, 5, 1)).any()  # processed that day
    assert bj.event_counts(lat, lon, [day], events, known_before=dt.date(2024, 4, 1), peek=True).any()


def test_the_menu_offers_events_only_with_data_and_the_champion_is_unchanged(lab, tmp_path):
    assert "street_events" in bj.MENU and "events" not in bj.BASELINE
    any(p.endswith("manifest.json") and "events" in p for p in bj.FILES) or pytest.fail("events not in the digest")
    root = bj.CONFIG["root"]
    try:
        bj.configure(dict(root=root, events_root=str(tmp_path / "none")))
        assert "street_events" not in bj.MENU
    finally:
        bj.configure(dict(root=root, events_root=None))
    assert "street_events" in bj.MENU


def test_the_leak_canary_flags_events_processed_after_the_origin(lab):
    cache = {}
    assert not bj.leak_canary(dict(bj.BASELINE, events=True), "A", "pilot", cache)
    assert bj.leak_canary(dict(bj.BASELINE, events_peek=True), "A", "pilot", cache)


def test_a_prospective_origin_reads_only_snapshots_taken_before_it(lab):
    base, events = lab
    root = base / "events" / "chi"
    later = [dict(e, lat=e["lat"] + 1.0) for e in events]  # a revised table: every event moved far away
    ev.ingest("chi", str(root), get=stub_socrata(permit_rows(later, junk=False)), log=lambda *_: None,
              today=dt.date(2025, 6, 1))  # fmt: skip
    try:
        old, new = bj.load_events("2025-05-15T00:00:00Z"), bj.load_events("2025-07-01T00:00:00Z")
        assert old["lat"].max() < 42.0 and new["lat"].min() > 42.0
    finally:
        man = json.loads((root / "manifest.json").read_text())
        del man["snapshots"]["permits-20250601.csv.gz"]
        (root / "manifest.json").write_text(json.dumps(man))


def test_the_planted_event_effect_is_supported(lab):
    cache, rng = {}, np.random.default_rng(0)
    pre = sk.Preregistration(hid="e", statement="e", estimand="e", treatment=dict(bj.BASELINE, events=True),
                             comparator=bj.BASELINE, primary_metric="WAPE", unit="station", sesoi=0.02,
                             n_boot=300).lock()  # fmt: skip
    res = sk.run_test(pre, lambda g: bj.evaluate(g, "B", "confirmation", cache), rng)
    assert res["decision"] == "supported", res


def test_the_supervisor_takes_a_snapshot_a_month(tmp_path, monkeypatch):
    from ops import labd

    root = tmp_path / "bikeshare" / "chi"
    root.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({"months": {}}))
    monkeypatch.setattr(ing, "ingest", lambda *a, **k: {"months": {}})  # offline: no trip download
    taken = []
    monkeypatch.setattr(ev, "ingest", lambda system, r, **k: taken.append((system, r)))
    labd.refresh_data({"root": str(root)}, "chi", log=lambda *_: None)
    assert taken == [("chi", str(tmp_path / "events" / "chi"))]
    monkeypatch.setattr(ev, "due", lambda r: False)
    labd.refresh_data({"root": str(root)}, "chi", log=lambda *_: None)
    assert len(taken) == 1
