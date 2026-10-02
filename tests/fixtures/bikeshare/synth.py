"""Synthetic bike-share trips in the operator's (Lyft) schema, served through a stub S3 `get`. Real trip data may
not be redistributed, so the tests run on this. Planted: station-specific day-of-week profiles, strong annual
seasonality, holiday dips, 8 %/year growth, 20 % dockless trips, the 2025-06 station-id switch (names carry
over) and a macOS resource fork inside each zip. Optionally, street events (CDOT permits, served through a stub
Socrata `get`) that raise pickups at stations within 400 m while they run."""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import numpy as np
import pandas as pd

from judges.bikeshare import _holidays, month_add, month_dates

HEADER = [
    "ride_id",
    "rideable_type",
    "started_at",
    "ended_at",
    "start_station_name",
    "start_station_id",
    "end_station_name",
    "end_station_id",
    "start_lat",
    "start_lng",
    "end_lat",
    "end_lng",
    "member_casual",
]


def months(first, last):
    out, m = [], first
    while m <= last:
        out.append(m)
        m = month_add(m, 1)
    return out


def published_at(month):
    """A few days after the month ends, varying by month (as the operator's uploads do)."""
    nxt = month_add(month, 1)
    day = 3 + int(month) % 9
    return dt.datetime(int(nxt[:4]), int(nxt[4:]), day, 19, 30, tzinfo=dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


EVENT_LIFT = 2.5  # planted: pickups at a station within 400 m of a running street event


def street_events(first="202102", last="202508", n_stations=20, seed=0, per_month=6):
    """Planted street events beside random stations: most processed 40-120 days ahead (known at the origin), a
    fifth processed 3 days ahead (real, but unknowable two months out), plus permits the ingest must drop."""
    _, lat, lon = _stations(n_stations, seed)
    rng = np.random.default_rng(seed + 7)
    out = []
    for m in months(first, last):
        days = month_dates(m)
        for k in range(per_month):
            i, start = int(rng.integers(n_stations)), days[int(rng.integers(len(days)))]
            lead = 3 if k % 5 == 4 else int(rng.integers(40, 121))
            out.append(
                dict(
                    uid=f"{m}{k:02d}",
                    kind=("Festival", "Parade", "Athletic")[k % 3],
                    start=start,
                    end=start + dt.timedelta(days=int(rng.integers(0, 3))),
                    processed=start - dt.timedelta(days=lead),
                    lat=lat[i] + 0.0005,
                    lon=lon[i],
                )
            )  # fmt: skip  (about 55 m north of the station)
    return out


def _stations(n_stations, seed):
    rng = np.random.default_rng(seed)
    level = rng.lognormal(1.2, 0.5, n_stations)
    rng.random(n_stations)  # weekend lovers (drawn in expected_pickups' order)
    cluster = rng.integers(0, 4, n_stations)
    lat = 41.85 + 0.03 * cluster + rng.normal(0, 0.004, n_stations)
    lon = -87.65 + 0.02 * (cluster % 2) + rng.normal(0, 0.004, n_stations)
    return level, lat, lon


def expected_pickups(first="202102", last="202508", n_stations=20, seed=0, events=None):
    """station name -> date -> planted mean pickups, and station coordinates. `events`: street events that lift
    pickups at stations within 400 m while they run."""
    rng = np.random.default_rng(seed)
    level = rng.lognormal(1.2, 0.5, n_stations)
    weekend_lover = rng.random(n_stations) < 0.5
    cluster = rng.integers(0, 4, n_stations)
    lat = 41.85 + 0.03 * cluster + rng.normal(0, 0.004, n_stations)
    lon = -87.65 + 0.02 * (cluster % 2) + rng.normal(0, 0.004, n_stations)
    names = [f"Station {i:02d} & Fixture Ave" for i in range(n_stations)]
    d0 = dt.date(2021, 2, 1)
    means = {}
    for m in months(first, last):
        hols = _holidays(int(m[:4]))
        for d in month_dates(m):
            season = 1 + 0.7 * np.sin(2 * np.pi * (d.timetuple().tm_yday - 110) / 365.25)
            growth = 1.08 ** ((d - d0).days / 365.25)
            wk = d.weekday() >= 5
            dow = np.where(weekend_lover, 1.5 if wk else 0.8, 0.6 if wk else 1.15)
            hol = 0.6 if d in hols else 1.0
            means[d] = level * season * growth * dow * hol
    for ev in events or ():
        near = ((lat - ev["lat"]) * 111_320) ** 2 + ((lon - ev["lon"]) * 111_320 * np.cos(np.radians(41.9))) ** 2
        lift = np.where(near <= 400**2, EVENT_LIFT, 1.0)
        d = ev["start"]
        while d <= ev["end"]:
            if d in means:
                means[d] = means[d] * lift
            d += dt.timedelta(days=1)
    return names, lat, lon, means


def trip_zips(first="202102", last="202508", n_stations=20, seed=0, events=None):
    """{yyyymm: (zip bytes, published_at)}"""
    names, lat, lon, means = expected_pickups(first, last, n_stations, seed, events)
    rng = np.random.default_rng(seed + 1)
    out = {}
    for m in months(first, last):
        rows = []
        for d in month_dates(m):
            counts = rng.poisson(means[d])
            for i, n in enumerate(counts):
                sid = f"CHI{i:05d}" if m >= "202506" else f"KA15030000{i:02d}"
                for _ in range(n):
                    t = dt.datetime.combine(d, dt.time()) + dt.timedelta(seconds=int(rng.integers(0, 86400)))
                    rows.append([t.strftime("%Y-%m-%d %H:%M:%S.000"), names[i], sid, lat[i], lon[i]])
            for _ in range(int(0.25 * counts.sum())):  # dockless e-bike trips: no start station
                t = dt.datetime.combine(d, dt.time()) + dt.timedelta(seconds=int(rng.integers(0, 86400)))
                rows.append([t.strftime("%Y-%m-%d %H:%M:%S.000"), "", "", 41.9, -87.6])
        df = pd.DataFrame(
            rows, columns=["started_at", "start_station_name", "start_station_id", "start_lat", "start_lng"]
        )
        df.insert(0, "ride_id", [f"R{m}{k:07d}" for k in range(len(df))])
        df.insert(1, "rideable_type", "classic_bike")
        df.insert(3, "ended_at", df["started_at"])
        for c in ("end_station_name", "end_station_id", "end_lat", "end_lng"):
            df[c] = ""
        df["member_casual"] = "member"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{m}-divvy-tripdata.csv", df[HEADER].to_csv(index=False))
            z.writestr(f"__MACOSX/._{m}-divvy-tripdata.csv", b"\x00\x05\x16\x07binary resource fork")
        out[m] = (buf.getvalue(), published_at(m))
    return out


def stub_get(zips):
    """A stand-in for ops.bikeshare_ingest.fetch serving the bucket listing and the zips."""

    def get(url):
        if "list-type=2" in url:
            items = "".join(
                f"<Contents><Key>{m}-divvy-tripdata.zip</Key><LastModified>{p}</LastModified><Size>1</Size></Contents>"
                for m, (_, p) in sorted(zips.items())
            )
            other = "<Contents><Key>index.html</Key><LastModified>x</LastModified></Contents>"
            return f"<ListBucketResult>{items}{other}</ListBucketResult>".encode()
        return zips[url.rsplit("/", 1)[1][:6]][0]

    return get


def gbfs_day(root, day, stations, empty_polls=None, missing_polls=None, every=300, tz="America/Chicago"):
    """Write one collector day file (ops/gbfs_collect.py format) and its station_information.
    stations: {station_id: name}; empty_polls / missing_polls: {station_id: number of polls}."""
    import csv
    import gzip
    import json
    import os
    from zoneinfo import ZoneInfo

    empty_polls, missing_polls = empty_polls or {}, missing_polls or {}
    start = dt.datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(tz)).timestamp()
    os.makedirs(os.path.join(root, "station_information"), exist_ok=True)
    with open(os.path.join(root, "station_information", f"{day}.json"), "w") as f:
        json.dump([dict(station_id=s, name=n, short_name=s) for s, n in stations.items()], f)
    with gzip.open(os.path.join(root, f"{day}.csv.gz"), "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fetched_at", "station_id", "last_reported", "num_bikes_available", "num_docks_available",
                    "is_installed", "is_renting", "is_returning"])  # fmt: skip
        for k in range(86_400 // every):
            for s in stations:
                if k < missing_polls.get(s, 0):
                    continue
                bikes = 0 if k < empty_polls.get(s, 0) else 5
                w.writerow([int(start) + k * every, s, int(start) + k * every, bikes, 10 - bikes, 1, 1, 1])


def permit_rows(events, junk=True):
    """Socrata rows (CDOT schema, strings) for `events`, plus permits the ingest must drop: no processed date (an
    application cancelled before processing), and no coordinates."""

    def iso(d):
        return f"{d.isoformat()}T00:00:00.000"

    rows = [dict(uniquekey=e["uid"], worktypedescription=e["kind"], applicationname=f"Fest {e['uid']}",
                 applicationprocesseddate=iso(e["processed"]), applicationstartdate=iso(e["start"]),
                 applicationenddate=iso(e["end"]), latitude=str(e["lat"]), longitude=str(e["lon"]),
                 streetclosure="Full") for e in events]  # fmt: skip
    if junk:
        rows.append(dict(uniquekey="X1", worktypedescription="Festival", applicationstartdate=iso(dt.date(2024, 7, 1)),
                         latitude="41.9", longitude="-87.6"))  # fmt: skip
        rows.append(dict(uniquekey="X2", worktypedescription="Parade", applicationprocesseddate=iso(dt.date(2024, 5, 1)),
                         applicationstartdate=iso(dt.date(2024, 7, 1))))  # fmt: skip
    return rows


def stub_socrata(rows):
    """A stand-in for ops.events_ingest.fetch: serves `rows` in $limit/$offset pages."""
    import json
    import urllib.parse

    def get(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        limit, offset = int(q["$limit"]), int(q["$offset"])
        return json.dumps(rows[offset : offset + limit]).encode()

    return get
