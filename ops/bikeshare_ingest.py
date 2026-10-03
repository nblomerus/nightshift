"""Bike-share trip ingest (ROADMAP 8c, docs/specs/bikeshare.md §2-3).

Downloads the operator's monthly trip zips, records each month's publication time (S3 LastModified) and SHA-256,
and aggregates docked pickups to station x day. Output under data/ (gitignored: the licence forbids redistribution):

    <root>/manifest.json                      month -> published_at, sha256, trip counts
    <root>/station_day/<yyyymm>.csv.gz        station, date, pickups
    <root>/stations/<yyyymm>.csv              station, lat, lon, ids (the ids seen for that name that month)

Stations are keyed by NAME: Divvy replaced every station id in 2025-06 (e.g. KA1503000071 -> CHI00252) while
names carried over, and GBFS station_information carries the same names. Trips without a start station
(dockless e-bike rentals) are counted in the manifest but are not station demand.

    python -m ops.bikeshare_ingest --system chi --from 202102
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import urllib.request
import zipfile

import pandas as pd

SYSTEMS = {
    "chi": dict(bucket="divvy-tripdata", key="{m}-divvy-tripdata.zip"),
    "bkn": dict(bucket="tripdata", key="{m}-citibike-tripdata.zip"),
}
FIRST_MONTH = "202102"  # the current Lyft schema starts here
COLUMNS = ["started_at", "start_station_name", "start_station_id", "start_lat", "start_lng"]


def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "nightshift-ingest"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def list_months(system, get=fetch):
    """{yyyymm: published_at (ISO, UTC)} for every monthly trip zip in the operator's bucket."""
    bucket, pattern = SYSTEMS[system]["bucket"], SYSTEMS[system]["key"]
    key_re = re.compile("^" + re.escape(pattern).replace(r"\{m\}", r"(\d{6})") + "$")
    out, token = {}, None
    while True:
        url = f"https://s3.amazonaws.com/{bucket}?list-type=2" + (f"&continuation-token={token}" if token else "")
        xml = get(url).decode()
        for key, modified in re.findall(r"<Key>([^<]+)</Key>\s*<LastModified>([^<]+)</LastModified>", xml):
            m = key_re.match(key)
            if m:
                out[m.group(1)] = modified
        token_m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", xml)
        if not token_m:
            return dict(sorted(out.items()))
        token = urllib.request.quote(token_m.group(1), safe="")


def read_trips(zip_bytes):
    """All trip CSVs in a month zip (Citi Bike splits large months), skipping macOS resource forks."""
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    names = [n for n in z.namelist() if n.endswith(".csv") and not n.startswith("__MACOSX") and "/._" not in n]
    frames = [pd.read_csv(z.open(n), usecols=COLUMNS, dtype={"start_station_id": str}) for n in sorted(names)]
    return pd.concat(frames, ignore_index=True)


def aggregate(trips):
    """-> (station_day, stations, counts). The date is the local date in `started_at` (operators publish local
    times)."""
    docked = trips[trips["start_station_name"].notna() & (trips["start_station_name"].str.strip() != "")].copy()
    docked["station"] = docked["start_station_name"].str.strip()
    docked["date"] = docked["started_at"].str.slice(0, 10)
    station_day = docked.groupby(["station", "date"]).size().rename("pickups").reset_index()
    stations = (
        docked.groupby("station")
        .agg(
            lat=("start_lat", "median"),
            lon=("start_lng", "median"),
            ids=("start_station_id", lambda s: "|".join(sorted(set(s.dropna())))),
        )
        .reset_index()
    )
    counts = dict(trips=len(trips), docked_trips=len(docked), stations=len(stations))
    return station_day, stations, counts


def write_month(root, month, published_at, zip_bytes):
    station_day, stations, counts = aggregate(read_trips(zip_bytes))
    for sub in ("station_day", "stations"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    with gzip.open(os.path.join(root, "station_day", f"{month}.csv.gz"), "wt") as f:
        station_day.to_csv(f, index=False)
    stations.to_csv(os.path.join(root, "stations", f"{month}.csv"), index=False)
    entry = dict(published_at=published_at, sha256=hashlib.sha256(zip_bytes).hexdigest(), **counts)
    manifest = read_manifest(root)
    manifest["months"][month] = entry
    tmp = os.path.join(root, "manifest.json.tmp")
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(root, "manifest.json"))
    return entry


def read_manifest(root):
    path = os.path.join(root, "manifest.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return dict(months={}, ingested_at=None)


def ingest(system, root, first=FIRST_MONTH, last=None, get=fetch, log=print):
    """Ingest every published month in [first, last] not already in the manifest with the same publication time.
    A month whose zip fails to download or parse is logged and skipped, not fatal, so later months still get
    ingested. Its failure is tracked in manifest['failed'][month] = {error, first_seen, last_seen, attempts} and
    cleared the next time that month succeeds, so a month stuck failing for days can be escalated by the caller."""
    start = read_manifest(root)
    done, failed = start["months"], start.get("failed", {})
    now = dt.datetime.now(dt.UTC).isoformat()
    for month, published_at in list_months(system, get).items():
        if month < first or (last and month > last):
            continue
        if done.get(month, {}).get("published_at") == published_at:
            continue
        url = f"https://s3.amazonaws.com/{SYSTEMS[system]['bucket']}/{SYSTEMS[system]['key'].format(m=month)}"
        try:
            entry = write_month(root, month, published_at, get(url))
        except Exception as e:
            prior = failed.get(month, {})
            failed[month] = dict(error=f"{type(e).__name__}: {e}", first_seen=prior.get("first_seen", now),
                                  last_seen=now, attempts=prior.get("attempts", 0) + 1)  # fmt: skip
            log(f"{month}: ingest failed ({failed[month]['attempts']}x): {failed[month]['error']}")
            continue
        failed.pop(month, None)
        log(f"{month}: {entry['docked_trips']:,} docked of {entry['trips']:,} trips, {entry['stations']} stations")
    manifest = read_manifest(root)
    manifest["failed"] = failed
    manifest["ingested_at"] = now
    with open(os.path.join(root, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ops.bikeshare_ingest", description=__doc__.split("\n\n")[0])
    ap.add_argument("--system", choices=sorted(SYSTEMS), default="chi")
    ap.add_argument("--from", dest="first", default=FIRST_MONTH)
    ap.add_argument("--to", dest="last", default=None)
    ap.add_argument("--root", default=None, help="default: data/bikeshare/<system>")
    a = ap.parse_args(argv)
    ingest(a.system, a.root or os.path.join("data", "bikeshare", a.system), a.first, a.last)


if __name__ == "__main__":
    main()
