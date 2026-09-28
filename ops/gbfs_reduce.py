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


def reduce_all(gbfs_root, out_path, today=None):
    """Every complete day (not `today`, which is still being collected) into one table."""
    days = sorted(glob.glob(os.path.join(gbfs_root, "????-??-??.csv.gz")))
    frames = [
        reduce_day(p, station_names(gbfs_root, os.path.basename(p)[:10]))
        for p in days
        if os.path.basename(p)[:10] != today
    ]
    table = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["station", "date"])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with gzip.open(out_path, "wt") as f:
        table.to_csv(f, index=False)
    return table


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
    table = reduce_all(os.path.join(a.data, "gbfs", a.system), out, today=today)
    print(f"{out}: {len(table)} station-days")


if __name__ == "__main__":
    main()
