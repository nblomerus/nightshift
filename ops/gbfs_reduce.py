"""Reduce GBFS snapshots to a station-day censoring table (ROADMAP 8d, docs/specs/bikeshare.md §4).

For every local day collected by ops/gbfs_collect.py, and every station (by NAME, the key the trip data shares),
record how many minutes the station was renting with no bike available and what share of the day's polls saw it.
The judge applies the censoring thresholds (decision standards) to these raw numbers.

    <data>/gbfs/<system>/<yyyy-mm-dd>.csv.gz  ->  <data>/bikeshare/<system>/censor_day.csv.gz
        station, date, empty_minutes, coverage

    python -m ops.gbfs_reduce --system chi
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import os

import pandas as pd

DAY_SECONDS = 86_400


def station_names(gbfs_root, day):
    """station_id -> name from the station_information saved on `day`, or the latest one before it."""
    files = sorted(glob.glob(os.path.join(gbfs_root, "station_information", "*.json")))
    older = [f for f in files if os.path.basename(f)[:10] <= day] or files[:1]
    if not older:
        return {}
    with open(older[-1]) as f:
        return {s["station_id"]: s["name"].strip() for s in json.load(f) if s.get("name")}


def reduce_day(path, names, every=None):
    """One day file -> station, date, empty_minutes, coverage. `every` is the poll interval (seconds); by default
    the median gap between polls. Coverage is polls that saw the station over the polls a full day would have."""
    day = os.path.basename(path)[:10]
    df = pd.read_csv(path, dtype={"station_id": str})
    polls = sorted(df["fetched_at"].unique())
    if every is None:
        every = int(pd.Series(polls).diff().median()) if len(polls) > 1 else 300
    df["station"] = df["station_id"].map(names)
    df = df[df["station"].notna()]
    df["empty"] = (df["is_renting"] == 1) & (df["num_bikes_available"] == 0)
    g = df.groupby("station").agg(polls=("fetched_at", "nunique"), empty=("empty", "sum"))
    out = pd.DataFrame(
        dict(
            station=g.index,
            date=day,
            empty_minutes=g["empty"].to_numpy() * every / 60,
            coverage=(g["polls"].to_numpy() / (DAY_SECONDS / every)).clip(max=1.0),
        )
    )
    return out.reset_index(drop=True)


def _unchanged(out_path, csv_text):
    """True if `out_path` already holds exactly `csv_text` (compared decompressed: gzip's own header mtime would
    otherwise make two writes of identical content look different byte-for-byte)."""
    if not os.path.exists(out_path):
        return False
    with gzip.open(out_path, "rt") as f:
        return f.read() == csv_text


def reduce_all(gbfs_root, out_path, today=None):
    """Every complete day (not `today`, which is still being collected) into one table. A day file that fails to
    parse (e.g. truncated by the collector) is skipped, not fatal: it would otherwise abort the whole rebuild and
    freeze the censoring table at whatever it last was. Returns (table, skipped), where `skipped` is a list of
    (path, error) for the caller to alert on. Leaves the file untouched when the freshly computed table is
    byte-identical to what's already there, so its mtime (and anything keyed on it) stays stable too."""
    days = sorted(glob.glob(os.path.join(gbfs_root, "????-??-??.csv.gz")))
    frames, skipped = [], []
    for p in days:
        if os.path.basename(p)[:10] == today:
            continue
        try:
            frames.append(reduce_day(p, station_names(gbfs_root, os.path.basename(p)[:10])))
        except Exception as e:
            skipped.append((p, f"{type(e).__name__}: {e}"))
    table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["station", "date"])
    csv_text = table.to_csv(index=False)
    if not _unchanged(out_path, csv_text):
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with gzip.open(out_path, "wt") as f:
            f.write(csv_text)
    return table, skipped


def main(argv=None):
    import datetime as dt
    from zoneinfo import ZoneInfo

    from ops.gbfs_collect import SYSTEMS

    ap = argparse.ArgumentParser(prog="python -m ops.gbfs_reduce", description=__doc__.split("\n\n")[0])
    ap.add_argument("--system", choices=sorted(SYSTEMS), default="chi")
    ap.add_argument("--data", default="data")
    a = ap.parse_args(argv)
    today = dt.datetime.now(ZoneInfo(SYSTEMS[a.system]["tz"])).date().isoformat()
    out = os.path.join(a.data, "bikeshare", a.system, "censor_day.csv.gz")
    table, skipped = reduce_all(os.path.join(a.data, "gbfs", a.system), out, today=today)
    print(f"{out}: {len(table)} station-days")
    for path, error in skipped:
        print(f"skipped {path}: {error}")


if __name__ == "__main__":
    main()
