"""Street-event permits for the bike-share judge (ROADMAP 8g, docs/specs/bikeshare-events.md).

Fetches the City of Chicago's CDOT permits for festivals, parades and athletic events (Socrata `pubx-yq2d`) and
writes a dated snapshot. An event is known at an origin from its `processed` date (spec §2); the permit's current
status is not kept, because it was not known at the time. Output under data/ (gitignored):

    <root>/permits-<yyyymmdd>.csv.gz     uid, kind, name, processed, start, end, lat, lon, closure
    <root>/manifest.json                 snapshot -> fetched_at, rows, dropped, sha256

The portal keeps only each permit's latest values, so the lab keeps a snapshot a month: prospective locks then read
a snapshot taken before them (spec §2, risk 2). Works permits are not fetched: they are processed on the day the
work starts, so none is known two months ahead.

    python -m ops.events_ingest --system chi
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import urllib.parse
import urllib.request

import pandas as pd

SYSTEMS = {"chi": dict(dataset="https://data.cityofchicago.org/resource/pubx-yq2d.json")}
KINDS = ("Festival", "Parade", "Athletic")
FIELDS = {  # source column -> snapshot column
    "uniquekey": "uid",
    "worktypedescription": "kind",
    "applicationname": "name",
    "applicationprocesseddate": "processed",
    "applicationstartdate": "start",
    "applicationenddate": "end",
    "latitude": "lat",
    "longitude": "lon",
    "streetclosure": "closure",
}
PAGE = 50_000
EVERY_DAYS = 28  # the supervisor takes a new snapshot when the latest is older than this


def fetch(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "nightshift-ingest"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_permits(system, get=fetch):
    """Every festival / parade / athletic permit, paged in a stable order."""
    kinds = ",".join(f"'{k}'" for k in KINDS)
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"$select": ",".join(FIELDS), "$where": f"worktypedescription in({kinds})",
                                    "$order": "uniquekey", "$limit": PAGE, "$offset": offset})  # fmt: skip
        page = json.loads(get(f"{SYSTEMS[system]['dataset']}?{q}"))
        rows += page
        if len(page) < PAGE:
            return rows
        offset += PAGE


def clean(rows):
    """-> (snapshot frame, dropped count). A permit without a processed date, a start date or coordinates cannot be
    placed in time or space, so it is dropped (and counted); a missing end date means a one-day event."""
    df = pd.DataFrame(rows, columns=list(FIELDS)).rename(columns=FIELDS)
    for c in ("processed", "start", "end"):
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    df["end"] = df["end"].fillna(df["start"])
    df["lat"], df["lon"] = pd.to_numeric(df["lat"], errors="coerce"), pd.to_numeric(df["lon"], errors="coerce")
    ok = df["processed"].notna() & df["start"].notna() & df["lat"].notna() & df["lon"].notna()
    df = df[ok & (df["end"] >= df["start"])].sort_values("uid").reset_index(drop=True)
    return df, int(len(ok) - len(df))


def read_manifest(root):
    path = os.path.join(root, "manifest.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return dict(snapshots={})


def ingest(system, root, get=fetch, log=print, today=None):
    """Write today's snapshot, unless one exists. Returns the manifest."""
    today = today or dt.date.today()
    name = f"permits-{today:%Y%m%d}.csv.gz"
    manifest = read_manifest(root)
    if name in manifest["snapshots"]:
        return manifest
    df, dropped = clean(fetch_permits(system, get))
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as f:  # mtime 0: the same rows give the same hash
        f.write(df.to_csv(index=False).encode())
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, name), "wb") as f:
        f.write(buf.getvalue())
    digest = hashlib.sha256(buf.getvalue()).hexdigest()
    manifest["snapshots"][name] = dict(fetched_at=dt.datetime.now(dt.UTC).isoformat(), date=today.isoformat(),
                                       rows=len(df), dropped=dropped, sha256=digest)  # fmt: skip
    tmp = os.path.join(root, "manifest.json.tmp")
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(root, "manifest.json"))
    log(f"events {system}: {len(df):,} permits ({dropped:,} dropped without a date or coordinates) -> {name}")
    return manifest


def due(root, today=None):
    """True when the latest snapshot is older than EVERY_DAYS (or there is none)."""
    snaps = read_manifest(root)["snapshots"].values()
    if not snaps:
        return True
    last = max(dt.date.fromisoformat(s["date"]) for s in snaps)
    return ((today or dt.date.today()) - last).days >= EVERY_DAYS


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ops.events_ingest", description=__doc__.split("\n\n")[0])
    ap.add_argument("--system", choices=sorted(SYSTEMS), default="chi")
    ap.add_argument("--root", default=None, help="default: data/events/<system>")
    a = ap.parse_args(argv)
    ingest(a.system, a.root or os.path.join("data", "events", a.system))


if __name__ == "__main__":
    main()
