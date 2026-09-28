"""GBFS availability collector (ROADMAP 8a, docs/specs/bikeshare.md §4).

Operators publish only the current state of each station, so the lab builds its own availability history: poll
`station_status` every few minutes and append one row per station per poll to a gzip CSV per local day. The
censoring mask (8d) is computed from these files. Data lands under data/ (gitignored: the licence forbids
redistribution).

    python -m ops.gbfs_collect --system chi --every 300          # run forever
    python -m ops.gbfs_collect --system chi --print-launchd       # plist to keep it running on macOS
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import os
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

SYSTEMS = {
    "chi": dict(name="Divvy (Chicago)", tz="America/Chicago"),
    "bkn": dict(name="Citi Bike (New York)", tz="America/New_York"),
}
FEED = "https://gbfs.lyft.com/gbfs/2.3/{system}/en/{feed}.json"
COLUMNS = [
    "fetched_at",
    "station_id",
    "last_reported",
    "num_bikes_available",
    "num_docks_available",
    "is_installed",
    "is_renting",
    "is_returning",
]


def fetch_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "nightshift-gbfs-collector"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def local_date(system, ts):
    return dt.datetime.fromtimestamp(ts, ZoneInfo(SYSTEMS[system]["tz"])).date().isoformat()


def append_rows(root, system, fetched_at, stations):
    """Append one row per station to <root>/<system>/<local date>.csv.gz (the operator's local day)."""
    path = os.path.join(root, system, f"{local_date(system, fetched_at)}.csv.gz")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with gzip.open(path, "at", newline="") as f:  # each append is its own gzip member; readers see one stream
        w = csv.writer(f)
        if new:
            w.writerow(COLUMNS)
        for s in stations:
            w.writerow([int(fetched_at)] + [s.get(c, "") for c in COLUMNS[1:]])
    return path


def save_station_information(root, system, fetched_at, fetch):
    """Station metadata (short_name joins to trip data), once per local day."""
    path = os.path.join(root, system, "station_information", f"{local_date(system, fetched_at)}.json")
    if os.path.exists(path):
        return None
    info = fetch(FEED.format(system=system, feed="station_information"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(info["data"]["stations"], f)
    return path


def poll_once(root, system, fetch=fetch_json, now=time.time):
    fetched_at = now()
    status = fetch(FEED.format(system=system, feed="station_status"))
    path = append_rows(root, system, fetched_at, status["data"]["stations"])
    save_station_information(root, system, fetched_at, fetch)
    return path


def log_error(root, system, ts, err):
    line = f"{dt.datetime.fromtimestamp(ts, dt.UTC).isoformat()} {type(err).__name__}: {err}"
    print(line, file=sys.stderr, flush=True)
    os.makedirs(os.path.join(root, system), exist_ok=True)
    with open(os.path.join(root, system, "errors.log"), "a") as f:
        f.write(line + "\n")


def run(root, system, every, fetch=fetch_json, now=time.time, sleep=time.sleep, polls=None):
    """Poll on a fixed grid of `every` seconds. A failed poll is logged and skipped, never fatal: the coverage rule
    in the censoring mask turns gaps into `unknown` days."""
    n = 0
    while polls is None or n < polls:
        t0 = now()
        try:
            poll_once(root, system, fetch, now)
        except Exception as e:  # network, JSON, disk: log and keep collecting
            log_error(root, system, t0, e)
        n += 1
        if polls is None or n < polls:
            sleep(max(0.0, every - (now() - t0) % every))


def launchd_plist(system, every, root, python, repo):
    label = f"com.nightshift.gbfs.{system}"
    args = [python, "-m", "ops.gbfs_collect", "--system", system, "--every", str(every), "--root", root]
    arg_xml = "".join(f"\n    <string>{a}</string>" for a in args)
    log = os.path.join(root, system, "collector.log")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>{arg_xml}
  </array>
  <key>WorkingDirectory</key><string>{repo}</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONPATH</key><string>{repo}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ops.gbfs_collect", description=__doc__.split("\n\n")[0])
    ap.add_argument("--system", choices=sorted(SYSTEMS), default="chi")
    ap.add_argument("--every", type=int, default=300, help="seconds between polls (feed TTL is 60)")
    ap.add_argument("--root", default="data/gbfs")
    ap.add_argument("--polls", type=int, default=None, help="stop after N polls (default: run forever)")
    ap.add_argument("--print-launchd", action="store_true", help="print a launchd plist that keeps this running")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    if a.print_launchd:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        print(launchd_plist(a.system, a.every, root, sys.executable, repo), end="")
        return
    run(root, a.system, a.every, polls=a.polls)


if __name__ == "__main__":
    main()
