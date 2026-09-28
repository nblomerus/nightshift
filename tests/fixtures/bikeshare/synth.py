"""Synthetic bike-share trips in the operator's (Lyft) schema, served through a stub S3 `get`. Real trip data may
not be redistributed, so the tests run on this. Planted: station-specific day-of-week profiles, strong annual
seasonality, holiday dips, 8 %/year growth, 20 % dockless trips, the 2025-06 station-id switch (names carry
over) and a macOS resource fork inside each zip."""

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


def expected_pickups(first="202102", last="202508", n_stations=20, seed=0):
    """station name -> date -> planted mean pickups, and station coordinates."""
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
    return names, lat, lon, means


def trip_zips(first="202102", last="202508", n_stations=20, seed=0):
    """{yyyymm: (zip bytes, published_at)}"""
    names, lat, lon, means = expected_pickups(first, last, n_stations, seed)
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
