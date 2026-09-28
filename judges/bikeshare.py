"""Frozen judge for bike-share station demand (ROADMAP 8c, docs/specs/bikeshare.md).

Agents may choose a config from MENU; they never edit this file, the data, the split or the metric.

Task: daily docked pickups per station for target month M, forecast at the publication time of trip month M-2
(`as_of`); month M-1 is the gap the operator's publication lag forces. The point-in-time view at an origin holds
only months whose publication time is <= as_of, and every feature reads the view up to its last day `e` and
nothing after it: `leak_canary` checks that by scrambling everything after `e`.

Model: a pooled log-link GLM (Poisson by default, Tweedie p=1.5 as a treatment) fit by IRLS on the 12 target
months before M whose actuals are visible at as_of, each with its own features as of its own origin.

Metric: WAPE over station-days; unit-level abs_err[station, origin] for the kernel's paired two-way bootstrap.
Data roles (invariant 9) are disjoint target months, rotating through the calendar (spec §5).
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os

import numpy as np
import pandas as pd

NAME = "bikeshare"
TARGET = "station-day pickup WAPE two months ahead"
BASELINE_DESC = "pooled Poisson GLM on day of week, the station's and the system's last-28-day mean pickups"

BASELINE = dict(yoy=False, station_dow=False, holidays=False, neighbours=False, trend=False, tweedie=False, noise=0)
MENU = {
    "yoy_level": ("Add the station's mean daily pickups in the same calendar month last year", {"yoy": True}),
    "station_dow": ("Add the station's own day-of-week profile over the last 8 weeks", {"station_dow": True}),
    "holidays": ("Add US federal holiday and adjacent-day indicators", {"holidays": True}),
    "neighbour_pool": ("Add the mean last-28-day pickups of the station's 5 nearest stations", {"neighbours": True}),
    "system_trend": ("Add the system's 12-month growth ratio", {"trend": True}),
    "tweedie_loss": ("Fit a Tweedie (p=1.5) GLM instead of Poisson", {"tweedie": True}),
}
POSITIVE_CONTROL = dict(BASELINE, yoy=True)  # seasonality two months ahead: a large known effect
PLACEBO = dict(BASELINE, noise=1)  # a pure-noise feature

ROLES = ("pilot", "exploration", "confirmation", "replication", "reserve")
FIRST_TARGET = "202201"  # leaves >= 11 months of history for year-over-year features
PURPOSE_ROLE = {"pilot": "pilot", "exploration": "exploration", "primary": "confirmation", "replication": "replication"}
TRAIN_MONTHS = 12

CONFIG = dict(root=os.environ.get("NIGHTSHIFT_BIKESHARE_ROOT", os.path.join("data", "bikeshare", "chi")))
FILES: tuple = ()
DESIGNS: dict = {}
_PANELS: dict = {}


# ---------------------------------------------------------------------------- months and roles
def month_add(month, k):
    y, m = divmod(int(month[:4]) * 12 + int(month[4:]) - 1 + k, 12)
    return f"{y:04d}{m + 1:02d}"


def role(month):
    """Disjoint target-month roles. 12 mod 5 != 0, so each role rotates through every calendar month."""
    if month < FIRST_TARGET:
        return None
    return ROLES[(12 * (int(month[:4]) - 2022) + int(month[4:]) - 1) % len(ROLES)]


def data_keys(purpose, campaign=0, slot=0):
    """Real data is finite: every slice of a purpose scores the same role's months. No fresh months exist for an
    extra replication until the owner opens the reserve, so that purpose gets none."""
    return (PURPOSE_ROLE[purpose],) if purpose in PURPOSE_ROLE else ()


# ---------------------------------------------------------------------------- data
def configure(config):
    """Point the judge at an ingested system (ops/bikeshare_ingest.py) and fix the designs from its months."""
    CONFIG.update(config)
    manifest = os.path.join(CONFIG["root"], "manifest.json")
    globals()["FILES"] = (__file__, manifest)  # the data manifest is locked into every prereg with the code
    targets = target_months(load_panel())
    recent = targets[-24:]
    conf_all = [m for m in targets if role(m) == "confirmation"]
    conf_recent = [m for m in recent if role(m) == "confirmation"]
    DESIGNS.clear()
    DESIGNS["A"] = dict(desc=f"confirmation months in the last 24 months ({len(conf_recent)} origins)", T=None,
                        origins=conf_recent, window=recent[0] if recent else FIRST_TARGET)  # fmt: skip
    DESIGNS["B"] = dict(desc=f"every confirmation month since {FIRST_TARGET} ({len(conf_all)} origins)", T=None,
                        origins=conf_all, window=FIRST_TARGET)  # fmt: skip


def load_panel(root=None, as_of=None):
    """Station x day pickups for every ingested month published at or before `as_of` (all months if None)."""
    root = root or CONFIG["root"]
    with open(os.path.join(root, "manifest.json")) as f:
        manifest = json.load(f)["months"]
    months = sorted(m for m, e in manifest.items() if as_of is None or e["published_at"] <= as_of)
    key = (root, as_of, tuple((m, manifest[m]["sha256"]) for m in months))
    if key in _PANELS:
        return _PANELS[key]
    frames, coords = [], {}
    for m in months:
        with gzip.open(os.path.join(root, "station_day", f"{m}.csv.gz"), "rt") as f:
            frames.append(pd.read_csv(f))
        coords[m] = pd.read_csv(os.path.join(root, "stations", f"{m}.csv")).set_index("station")[["lat", "lon"]]
    sd = pd.concat(frames, ignore_index=True)
    first = dt.date(int(months[0][:4]), int(months[0][4:]), 1)
    end_m = month_add(months[-1], 1)
    days = pd.date_range(first, dt.date(int(end_m[:4]), int(end_m[4:]), 1) - dt.timedelta(days=1)).date
    stations = sorted(sd["station"].unique())
    s_idx, d_idx = {s: i for i, s in enumerate(stations)}, {d.isoformat(): i for i, d in enumerate(days)}
    Y = np.zeros((len(stations), len(days)))
    sd = sd[sd["date"].isin(d_idx)]
    Y[sd["station"].map(s_idx).to_numpy(), sd["date"].map(d_idx).to_numpy()] = sd["pickups"].to_numpy()
    panel = dict(
        Y=Y,
        days=days,
        month_of_day=np.array([d.strftime("%Y%m") for d in days]),
        stations=stations,
        published={m: manifest[m]["published_at"] for m in months},
        coords=coords,
    )
    _PANELS[key] = panel
    return panel


def target_months(panel):
    ms = panel["published"]
    return [m for m in sorted(ms) if role(m) is not None and month_add(m, -2) in ms and month_add(m, -13) in ms]


def origin(panel, month):
    """as_of and the index of the last visible day for target month `month` (point-in-time rule)."""
    as_of = panel["published"][month_add(month, -2)]  # the month the operator must have published
    visible = [m for m, p in panel["published"].items() if p <= as_of]
    e = int(np.flatnonzero(np.isin(panel["month_of_day"], visible)).max())
    return as_of, e, max(visible)


# ---------------------------------------------------------------------------- features
def _holidays(year):
    def nth(month, weekday, n):  # n-th weekday (Mon=0) of the month; n=-1 is the last
        d = dt.date(year, month, 1)
        days = [d + dt.timedelta(i) for i in range(31) if (d + dt.timedelta(i)).month == month]
        return [x for x in days if x.weekday() == weekday][n]

    fixed = [dt.date(year, m, d) for m, d in ((1, 1), (6, 19), (7, 4), (11, 11), (12, 25))]
    return set(fixed + [nth(1, 0, 2), nth(2, 0, 2), nth(5, 0, -1), nth(9, 0, 0), nth(10, 0, 1), nth(11, 3, 3)])


def _month_days(panel, month):
    return np.flatnonzero(panel["month_of_day"] == month)


def month_dates(month):
    first = dt.date(int(month[:4]), int(month[4:]), 1)
    nxt = month_add(month, 1)
    return list(pd.date_range(first, dt.date(int(nxt[:4]), int(nxt[4:]), 1) - dt.timedelta(days=1)).date)


def _design_rows(panel, Y, e, month, view_month, g, rng):
    """Features for every universe station x calendar day of `month`, from Y[:, :e+1] only (as of the origin).
    The target month need not be in the panel: a prospective forecast is made before it exists."""
    dates = month_dates(month)
    uni = np.flatnonzero(Y[:, max(0, e - 55) : e + 1].sum(1) > 0)
    st_mean = Y[uni, e - 27 : e + 1].mean(1)
    sys_mean = Y[:, e - 27 : e + 1].sum(0).mean()
    S, D = len(uni), len(dates)
    dow = np.array([d.weekday() for d in dates])
    cols = [np.log1p(np.repeat(st_mean, D)), np.full(S * D, np.log1p(sys_mean))]
    cols += [np.tile((dow == k).astype(float), S) for k in range(6)]
    if g["yoy"]:
        ly = _month_days(panel, month_add(month, -12))
        ly = ly[ly <= e]
        yoy = Y[uni][:, ly].mean(1) if len(ly) else st_mean
        cols += [np.log1p(np.repeat(yoy, D)), np.repeat((Y[uni][:, ly].sum(1) == 0).astype(float), D)]
    if g["station_dow"]:
        hist = np.arange(e - 55, e + 1)
        hist_dow = np.array([panel["days"][d].weekday() for d in hist])
        prof = np.stack([Y[uni][:, hist[hist_dow == k]].mean(1) for k in range(7)], 1)  # [S, 7]
        cols.append(np.log((prof[:, dow] + 0.1) / (st_mean[:, None] + 0.1)).reshape(-1))
    if g["holidays"]:
        year_hols = _holidays(int(month[:4]))
        hol = np.array([d in year_hols for d in dates], float)
        adj = np.array([any(d + dt.timedelta(k) in year_hols for k in (-1, 1)) for d in dates], float)
        cols += [np.tile(hol, S), np.tile(adj, S)]
    if g["neighbours"]:
        xy = panel["coords"][view_month].reindex([panel["stations"][i] for i in uni])
        xy = xy.fillna(xy.mean()).to_numpy() * np.array([1.0, np.cos(np.radians(41.9))])
        dist = ((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1)
        np.fill_diagonal(dist, np.inf)
        nn = np.argsort(dist, 1)[:, :5]
        cols.append(np.log1p(np.repeat(st_mean[nn].mean(1), D)))
    if g["trend"]:  # system pickups in the last 28 days vs the same 28 days a year earlier; 1 without a year
        last, prev = Y[:, e - 27 : e + 1].sum(), Y[:, e - 27 - 364 : e + 1 - 364].sum() if e >= 391 else 0.0
        cols.append(np.full(S * D, np.log(last / prev) if prev > 0 else 0.0))
    if g["noise"]:
        cols.append(rng.normal(size=S * D))
    if g.get("peek"):  # test-only: reads the target month itself, which the leak canary must catch
        cols.append(np.log1p(np.repeat(Y[uni][:, _month_days(panel, month)].mean(1), D)))
    return np.column_stack(cols), uni


def _fit_glm(X, y, power, ridge=1e-3, iters=25):
    """Log-link GLM by IRLS; power 1 = Poisson, 1 < power < 2 = Tweedie. Standardised columns, small ridge."""
    mu_x, sd_x = X.mean(0), X.std(0)
    sd_x[sd_x == 0] = 1.0
    Z = np.column_stack([np.ones(len(X)), (X - mu_x) / sd_x])
    beta = np.zeros(Z.shape[1])
    beta[0] = np.log(y.mean() + 1e-9)
    pen = ridge * len(y) * np.eye(Z.shape[1])
    pen[0, 0] = 0.0
    for _ in range(iters):
        eta = np.clip(Z @ beta, -20, 20)
        mu = np.exp(eta)
        w = mu ** (2 - power)
        z = eta + (y - mu) / mu
        new = np.linalg.solve(Z.T @ (Z * w[:, None]) + pen, Z.T @ (w * z))
        if np.max(np.abs(new - beta)) < 1e-8:
            beta = new
            break
        beta = new
    return lambda Xn: np.exp(np.clip(np.column_stack([np.ones(len(Xn)), (Xn - mu_x) / sd_x]) @ beta, -20, 20))


def predict_month(panel, Y, month, g):
    """Forecast target `month` as of its origin, from Y. Returns (station indices, dates, predictions)."""
    as_of, e, view_month = origin(panel, month)
    rng = np.random.default_rng(int(month))
    Xs, ys = [], []
    for k in range(2, 2 + TRAIN_MONTHS):  # training targets: months M-2 .. M-13, all visible at as_of
        tm = month_add(month, -k)
        tdays = _month_days(panel, tm)
        if not len(tdays) or tdays.max() > e or month_add(tm, -2) not in panel["published"]:
            continue
        te = int(_month_days(panel, month_add(tm, -2)).max())
        if te < 56:
            continue
        X, uni = _design_rows(panel, Y, te, tm, month_add(tm, -2), g, rng)
        Xs.append(X)
        ys.append(Y[np.ix_(uni, tdays)].reshape(-1))
    model = _fit_glm(np.vstack(Xs), np.concatenate(ys), 1.5 if g["tweedie"] else 1.0)
    X, uni = _design_rows(panel, Y, e, month, view_month, g, rng)
    return uni, month_dates(month), model(X).reshape(len(uni), -1)


# ---------------------------------------------------------------------------- the lab contract
def _origins(design, key):
    window = DESIGNS[design]["window"]
    return [m for m in target_months(load_panel()) if m >= window and role(m) == key]


def evaluate(genome, design, key, cache):
    """abs_err[station, origin] and actual[station, origin] over the design's months of role `key`."""
    ck = ("bikeshare", design, key, json.dumps(genome, sort_keys=True))
    if ck in cache:
        return cache[ck]
    panel, months = load_panel(), _origins(design, key)
    S = len(panel["stations"])
    abs_err, actual = np.zeros((S, len(months))), np.zeros((S, len(months)))
    for j, m in enumerate(months):
        uni, _, pred = predict_month(panel, panel["Y"], m, genome)
        y = panel["Y"][np.ix_(uni, _month_days(panel, m))]
        abs_err[uni, j], actual[uni, j] = np.abs(pred - y).sum(1), y.sum(1)
    out = dict(abs_err=abs_err, actual=actual, wape=abs_err.sum() / actual.sum(), origins=months)
    cache[ck] = out
    return out


def leak_canary(genome, design, key, cache, tol=1e-9):
    """True if predictions change when everything after the origin's last visible day is scrambled."""
    panel = load_panel()
    month = _origins(design, key)[0]
    _, e, _ = origin(panel, month)
    scrambled = panel["Y"].copy()
    scrambled[:, e + 1 :] = np.random.default_rng(0).poisson(5.0, scrambled[:, e + 1 :].shape)
    _, _, a = predict_month(panel, panel["Y"], month, genome)
    _, _, b = predict_month(panel, scrambled, month, genome)
    return bool(np.max(np.abs(a - b)) > tol)
