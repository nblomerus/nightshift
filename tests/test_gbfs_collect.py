"""ROADMAP 8a: the GBFS collector, offline (the HTTP fetch is stubbed)."""

import csv
import datetime as dt
import gzip
import os
from zoneinfo import ZoneInfo

from ops import gbfs_collect as gc

CHI = ZoneInfo("America/Chicago")


def ts(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=CHI).timestamp()


def stub_fetch(n_stations=3, fail_at=()):
    calls = {"status": 0}

    def fetch(url):
        if url.endswith("station_status.json"):
            calls["status"] += 1
            if calls["status"] in fail_at:
                raise OSError("feed down")
            stations = [
                dict(
                    station_id=f"s{i}",
                    last_reported=1_790_000_000,
                    num_bikes_available=i,
                    num_docks_available=10 - i,
                    is_installed=1,
                    is_renting=1,
                    is_returning=1,
                    vehicle_types_available=[{"vehicle_type_id": "1", "count": i}],
                )
                for i in range(n_stations)
            ]
            return {"data": {"stations": stations}}
        return {"data": {"stations": [{"station_id": "s0", "short_name": "1234.5", "lat": 41.9, "lon": -87.6}]}}

    return fetch


def read(path):
    with gzip.open(path, "rt", newline="") as f:
        return list(csv.DictReader(f))


def clock(times):
    it = iter(times)
    last = [None]

    def now():
        last[0] = next(it, last[0])
        return last[0]

    return now


def test_each_poll_appends_one_row_per_station(tmp_path):
    t = ts(2026, 9, 28, 12)
    gc.run(str(tmp_path), "chi", 300, fetch=stub_fetch(3), now=clock([t, t, t, t + 300, t + 300, t + 300]),
           sleep=lambda s: None, polls=2)  # fmt: skip
    rows = read(tmp_path / "chi" / "2026-09-28.csv.gz")
    assert len(rows) == 6
    assert set(rows[0]) == set(gc.COLUMNS)
    assert rows[0]["station_id"] == "s0" and rows[-1]["num_bikes_available"] == "2"
    assert os.path.exists(tmp_path / "chi" / "station_information" / "2026-09-28.json")


def test_a_failed_fetch_is_logged_and_collection_continues(tmp_path):
    t = ts(2026, 9, 28, 12)
    times = [t, t + 300, t + 300, t + 600, t + 600, t + 600]
    gc.run(str(tmp_path), "chi", 300, fetch=stub_fetch(2, fail_at={2}), now=clock(times), sleep=lambda s: None,
           polls=3)  # fmt: skip
    assert len(read(tmp_path / "chi" / "2026-09-28.csv.gz")) == 4  # polls 1 and 3
    log = (tmp_path / "chi" / "errors.log").read_text()
    assert "OSError: feed down" in log


def test_day_file_rolls_over_at_the_systems_local_midnight(tmp_path):
    before, after = ts(2026, 9, 28, 23, 58), ts(2026, 9, 29, 0, 3)
    gc.run(str(tmp_path), "chi", 300, fetch=stub_fetch(1), now=clock([before, before, before, after, after, after]),
           sleep=lambda s: None, polls=2)  # fmt: skip
    assert len(read(tmp_path / "chi" / "2026-09-28.csv.gz")) == 1
    assert len(read(tmp_path / "chi" / "2026-09-29.csv.gz")) == 1


def test_polls_stay_on_the_grid(tmp_path):
    slept = []
    t = [1000.0]

    def now():
        return t[0]

    def sleep(s):
        slept.append(s)
        t[0] += s

    def slow_fetch(url):
        t[0] += 7  # the poll itself takes 7 s
        return stub_fetch(1)(url)

    gc.run(str(tmp_path), "chi", 300, fetch=slow_fetch, now=now, sleep=sleep, polls=2)
    assert slept and abs(slept[0] - (300 - 14)) < 1e-9  # two fetches (status + info) in the first poll


def test_launchd_plist_runs_the_collector(tmp_path):
    xml = gc.launchd_plist("chi", 300, str(tmp_path), "/usr/bin/python3", "/repo")
    assert "<string>ops.gbfs_collect</string>" in xml and "<key>KeepAlive</key><true/>" in xml
