"""Monthly prospective forecasts: lock before the month exists, score after it is published (ROADMAP 8e).

When the operator publishes trip month L, `lock` forecasts every station-day of month L+2 with the current
champion AND the baseline, from data published by then only, and writes

    forecasts/<system>/<yyyymm>/champion.csv, baseline.csv    station, date, forecast
    forecasts/<system>/<yyyymm>/lock.json                     configs, digests, as_of, created_at, file hashes

Commit and push that directory: the git history and the GitHub push time are the public timestamp. When month
L+2 is published, `score` checks the lock (file hashes; created before the month began), scores both forecasts on
the station-days the censoring mask keeps, and writes scores/<system>/<yyyymm>.json.

    python -m ops.prospective lock  --system chi [--run runs/latest | --champion yoy_level,holidays]
    python -m ops.prospective score --system chi --month 202611
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess

import numpy as np
import pandas as pd

from agents.common import judge_digest
from judges import bikeshare as bj
from science import kernel as sk

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LockError(Exception):
    """A lock or a score that would not be a prospective test."""


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def champion_from_run(run_root):
    """The champion a lab run ended with: the baseline plus every promoted change, in order."""
    with open(os.path.join(run_root, "ledger.json")) as f:
        return [h["promoted"] for h in json.load(f)["champion_history"]]


def config_for(keys):
    unknown = [k for k in keys if k not in bj.MENU]
    if unknown:
        raise LockError(f"not on the judge's menu: {unknown}")
    g = dict(bj.BASELINE)
    for k in keys:
        g.update(bj.MENU[k][1])
    return g


def month_start_utc(month):
    """The earliest moment the month begins anywhere in the US (UTC midnight is earlier than any US midnight)."""
    return dt.datetime(int(month[:4]), int(month[4:]), 1, tzinfo=dt.UTC)


def _git_head():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def lock(system, out_root, champion_keys, now=None):
    """Forecast month L+2 from everything published so far. Refuses if that month has already begun."""
    now = now or dt.datetime.now(dt.UTC)
    panel = bj.load_panel()
    latest = max(panel["published"])
    month = bj.month_add(latest, 2)
    if now >= month_start_utc(month):
        raise LockError(f"{month} has already begun ({now.isoformat()}); a lock must precede its month")
    out = os.path.join(out_root, system, month)
    if os.path.exists(os.path.join(out, "lock.json")):
        raise LockError(f"{out} is already locked; a lock is never replaced")
    os.makedirs(out, exist_ok=True)
    arms = dict(champion=config_for(champion_keys), baseline=dict(bj.BASELINE))
    files = {}
    for arm, g in arms.items():
        uni, dates, pred = bj.predict_month(panel, panel["Y"], month, g)
        rows = [(panel["stations"][s], d.isoformat(), round(float(p), 4)) for s, ps in zip(uni, pred, strict=True)
                for d, p in zip(dates, ps, strict=True)]  # fmt: skip
        path = os.path.join(out, f"{arm}.csv")
        pd.DataFrame(rows, columns=["station", "date", "forecast"]).to_csv(path, index=False)
        files[f"{arm}.csv"] = sha256(path)
    record = dict(
        system=system,
        target_month=month,
        data_through=latest,
        as_of=panel["published"][latest],
        created_at=now.isoformat(),
        champion=dict(keys=list(champion_keys), config=arms["champion"]),
        baseline=dict(config=arms["baseline"]),
        judge_digest=judge_digest(bj),
        code_commit=_git_head(),
        files=files,
    )
    with open(os.path.join(out, "lock.json"), "w") as f:
        json.dump(record, f, indent=1, sort_keys=True)
    return record


def score(system, month, out_root, scores_root, n_boot=2000):
    """Score a locked month once the operator has published it."""
    out = os.path.join(out_root, system, month)
    with open(os.path.join(out, "lock.json")) as f:
        record = json.load(f)
    for name, digest in record["files"].items():
        if sha256(os.path.join(out, name)) != digest:
            raise LockError(f"{name} does not match its locked hash: the forecast changed after lock")
    if dt.datetime.fromisoformat(record["created_at"]) >= month_start_utc(month):
        raise LockError(f"lock created {record['created_at']}, after {month} began: not a prospective test")
    panel = bj.load_panel()
    if month not in panel["published"]:
        raise LockError(f"{month} is not published yet")
    days = {d.isoformat(): i for i, d in enumerate(panel["days"]) if d.strftime("%Y%m") == month}
    s_idx = {s: i for i, s in enumerate(panel["stations"])}
    use_mask = bj.masked(panel, month)
    frames = {arm: pd.read_csv(os.path.join(out, f"{arm}.csv")) for arm in ("champion", "baseline")}
    fc = frames["champion"].merge(frames["baseline"], on=["station", "date"], suffixes=("_c", "_b"))
    si = fc["station"].map(s_idx)  # a station with no pickups in any published month has none in this one
    di = fc["date"].map(days).to_numpy()
    y = np.where(si.notna(), panel["Y"][si.fillna(0).astype(int).to_numpy(), di], 0.0)
    keep = np.ones(len(fc), bool)
    if use_mask:
        keep = np.where(si.notna(), panel["C"][si.fillna(0).astype(int).to_numpy(), di] == bj.OK, False)
    fc = fc.assign(y=y, keep=keep)
    kept = fc[fc["keep"]]
    by_station = kept.assign(e_c=(kept["forecast_c"] - kept["y"]).abs(), e_b=(kept["forecast_b"] - kept["y"]).abs())
    g = by_station.groupby("station")[["e_c", "e_b", "y"]].sum()
    est = sk.paired_effect(g[["e_c"]].to_numpy(), g[["e_b"]].to_numpy(), 0.05, n_boot, np.random.default_rng(0))
    result = dict(
        system=system,
        target_month=month,
        lock=record,
        masked=bool(use_mask),
        censor_rate=float(1 - keep.mean()),
        station_days=int(len(kept)),
        stations=int(len(g)),
        wape_champion=float(g["e_c"].sum() / g["y"].sum()),
        wape_baseline=float(g["e_b"].sum() / g["y"].sum()),
        relative_wape_reduction=est,
        scored_at=dt.datetime.now(dt.UTC).isoformat(),
    )
    os.makedirs(os.path.join(scores_root, system), exist_ok=True)
    with open(os.path.join(scores_root, system, f"{month}.json"), "w") as f:
        json.dump(result, f, indent=1, sort_keys=True)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ops.prospective", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["lock", "score"])
    ap.add_argument("--system", default="chi")
    ap.add_argument("--data", default=None, help="default: data/bikeshare/<system>")
    ap.add_argument("--run", default=None, help="take the champion from this lab run's ledger.json")
    ap.add_argument("--champion", default="", help="comma-separated menu keys (overrides --run)")
    ap.add_argument("--month", default=None)
    ap.add_argument("--forecasts", default="forecasts")
    ap.add_argument("--scores", default="scores")
    a = ap.parse_args(argv)
    bj.configure(dict(root=a.data or os.path.join("data", "bikeshare", a.system)))
    if a.cmd == "lock":
        keys = [k for k in a.champion.split(",") if k] if a.champion else []
        if not a.champion and a.run:
            keys = champion_from_run(a.run)
        rec = lock(a.system, a.forecasts, keys)
        path = os.path.join(a.forecasts, a.system, rec["target_month"])
        print(f"locked {path} (champion: {keys or 'baseline'}). Publish the timestamp now:")
        print(f"  git add {path} && git commit -m 'Lock {a.system} forecasts for {rec['target_month']}' && git push")
    else:
        r = score(a.system, a.month, a.forecasts, a.scores)
        e = r["relative_wape_reduction"]
        wapes = f"champion WAPE {r['wape_champion']:.3f} vs baseline {r['wape_baseline']:.3f}"
        ci = f"reduction {e['point']:+.1%} [{e['lo']:+.1%}, {e['hi']:+.1%}]"
        print(f"{a.month}: {wapes}; {ci}; censor rate {r['censor_rate']:.0%}")


if __name__ == "__main__":
    main()
