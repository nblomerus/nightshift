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
import hashlib
import json
import os

import numpy as np
import pandas as pd

from judges.sandbox import SandboxError, run_plugin

NAME = "bikeshare"
TARGET = "station-day pickup WAPE two months ahead"
BASELINE_DESC = (
    "pooled Poisson GLM on day of week, the station's last-28-day and same-month-last-year mean pickups, and the "
    "system's last-28-day mean"
)

BASELINE = dict(
    yoy=True, station_dow=False, holidays=False, neighbours=False, trend=False, tweedie=False, censor=False, noise=0
)  # seasonal: two months ahead, a baseline without last year's level is a straw man (owner decision 2026-09-28)
MENU = {
    "station_dow": ("Add the station's own day-of-week profile over the last 8 weeks", {"station_dow": True}),
    "holidays": ("Add US federal holiday and adjacent-day indicators", {"holidays": True}),
    "neighbour_pool": ("Add the mean last-28-day pickups of the station's 5 nearest stations", {"neighbours": True}),
    "system_trend": ("Add the system's 12-month growth ratio", {"trend": True}),
    "tweedie_loss": ("Fit a Tweedie (p=1.5) GLM instead of Poisson", {"tweedie": True}),
    "censor_correct": ("Fit on latent demand: leave censored station-days out of training", {"censor": True}),
}
NEEDS_CENSOR_MASK = ("censor",)  # config fields that model latent demand: scorable only on masked months
# Positive control: the baseline against a copy that cannot tell stations apart. The effect is large in every
# month (+41 % to +77 % on real Divvy pilot months), so the protocol must detect it; a seasonal feature's effect
# swings with the season and did not (spec §5).
POSITIVE_CONTROL = dict(BASELINE)
POSITIVE_CONTROL_COMPARATOR = dict(BASELINE, blind=True)
PLACEBO = dict(BASELINE, noise=1)  # a pure-noise feature, against the baseline

ROLES = ("pilot", "exploration", "confirmation", "replication", "reserve")
FIRST_TARGET = "202201"  # leaves >= 11 months of history for year-over-year features
PURPOSE_ROLE = {"pilot": "pilot", "exploration": "exploration", "primary": "confirmation", "replication": "replication"}
TRAIN_MONTHS = 12

CONFIG = dict(
    root=os.environ.get("NIGHTSHIFT_BIKESHARE_ROOT", os.path.join("data", "bikeshare", "chi")),
    # decision standards for the censoring mask (spec §4); the rigspec may set them, no seat may
    censoring=dict(empty_minutes=60, min_coverage=0.9, month_coverage=0.9),
)
OK, CENSORED, NO_DATA = 1, 2, 0  # station-day status from GBFS snapshots
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
def configure(config, standards=None):
    """Point the judge at an ingested system (ops/bikeshare_ingest.py) and fix the designs from its months. The
    censoring thresholds come from the rigspec's decision standards when it sets them."""
    CONFIG.update(config)
    if standards and "censoring" in standards:
        CONFIG["censoring"] = dict(standards["censoring"])
    manifest = os.path.join(CONFIG["root"], "manifest.json")
    censor = os.path.join(CONFIG["root"], "censor_day.csv.gz")
    # the data manifest and the censoring table are locked into every prereg with the code
    sandbox = os.path.join(os.path.dirname(__file__), "sandbox.py")
    globals()["FILES"] = (__file__, sandbox, manifest) + ((censor,) if os.path.exists(censor) else ())
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
    censor = os.path.join(root, "censor_day.csv.gz")
    stamp = (
        (os.path.getmtime(censor), json.dumps(CONFIG["censoring"], sort_keys=True)) if os.path.exists(censor) else None
    )
    key = (root, as_of, tuple((m, manifest[m]["sha256"]) for m in months), stamp)
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
        C=_censor_status(root, stations, d_idx, len(days)),
        Y=Y,
        days=days,
        month_of_day=np.array([d.strftime("%Y%m") for d in days]),
        stations=stations,
        published={m: manifest[m]["published_at"] for m in months},
        coords=coords,
    )
    _PANELS[key] = panel
    return panel


def _censor_status(root, stations, d_idx, n_days):
    """[station, day] status from ops/gbfs_reduce.py: OK, CENSORED (empty too long, or too few polls: unknown), or
    NO_DATA (no snapshots that day at all). Thresholds are decision standards (CONFIG['censoring'])."""
    C = np.zeros((len(stations), n_days), dtype=np.int8)
    path = os.path.join(root, "censor_day.csv.gz")
    if not os.path.exists(path):
        return C
    t, s_idx = CONFIG["censoring"], {s: i for i, s in enumerate(stations)}
    cd = pd.read_csv(path)
    cd = cd[cd["date"].isin(d_idx)]
    have_day = np.zeros(n_days, bool)
    have_day[cd["date"].map(d_idx).to_numpy()] = True
    C[:, have_day] = CENSORED  # a station the snapshots never saw that day is unknown
    cd = cd[cd["station"].isin(s_idx)]
    ok = (cd["empty_minutes"] < t["empty_minutes"]) & (cd["coverage"] >= t["min_coverage"])
    C[cd["station"].map(s_idx).to_numpy(), cd["date"].map(d_idx).to_numpy()] = np.where(ok, OK, CENSORED)
    return C


def masked(panel, month):
    """A month is masked if snapshots exist for enough of its days; only then are censored days excluded."""
    days = _month_days(panel, month)
    return len(days) > 0 and (panel["C"][:, days] != NO_DATA).any(0).mean() >= CONFIG["censoring"]["month_coverage"]


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
    if g.get("blind"):  # control comparator only: forget which station is which (every station gets the mean)
        st_mean = np.full_like(st_mean, st_mean.mean())
    S, D = len(uni), len(dates)
    dow = np.array([d.weekday() for d in dates])
    cols = [np.log1p(np.repeat(st_mean, D)), np.full(S * D, np.log1p(sys_mean))]
    cols += [np.tile((dow == k).astype(float), S) for k in range(6)]
    if g["yoy"] and not g.get("blind"):
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


# ---------------------------------------------------------------------------- seat-written features (ROADMAP 5)
EVAL_VERSION = "2026-09-29.1"  # bump when the scoring of an existing config changes; not for new capabilities
HISTORY_DAYS = 400

CODE_CONTRACT = """Write Python defining features(view) -> numpy array; numpy is available, nothing else is needed.
It runs sandboxed (no network, no files, no subprocesses, bounded time). view is a dict of numpy arrays, for ONE
forecast origin, holding only data published by then:
  n_stations, n_days: ints (0-d arrays)
  history: float32 [n_stations, H] daily docked pickups of each station for the H days up to the origin (H <= 400)
  history_dates: int [H] the day of each history column as a proleptic Gregorian ordinal
                 (datetime.date.fromordinal); the last one is the last day with published data
  target_dates: int [n_days] the days to forecast (ordinals), about 32-62 days after the last history day
  lat, lon: float [n_stations] station coordinates
Return shape (n_stations * n_days,) or (n_stations * n_days, k) with k <= 8, rows ordered station-major (all target days
of station 0, then station 1, ...), finite values. The frozen judge adds the columns to the champion's pooled log-link
GLM (standardised), fits on the 12 previous target months, and scores the forecast month. The same function must work
for every origin, so derive everything from the view; it must be deterministic."""


def evaluation_key():
    """What a result depends on besides the config: the scoring semantics and the data. Knowledge-graph repeats key on
    this, so upgrading the judge's capabilities does not re-open decided tests; the lock still stamps the full digest."""
    h = hashlib.sha256(EVAL_VERSION.encode())
    for path in FILES[2:]:  # the data files
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def _plugin_view(panel, Y, e, uni, month, view_month):
    dates = month_dates(month)
    lo = max(0, e - HISTORY_DAYS + 1)
    xy = panel["coords"][view_month].reindex([panel["stations"][i] for i in uni])
    xy = xy.fillna(xy.mean())
    return dict(
        n_rows=np.array(len(uni) * len(dates)),
        n_stations=np.array(len(uni)),
        n_days=np.array(len(dates)),
        history=Y[uni, lo : e + 1].astype(np.float32),
        history_dates=np.array([panel["days"][d].toordinal() for d in range(lo, e + 1)]),
        target_dates=np.array([d.toordinal() for d in dates]),
        lat=xy["lat"].to_numpy(dtype=float),
        lon=xy["lon"].to_numpy(dtype=float),
    )


def _with_code(g, rows, timeout=180.0):
    """Append every seat-written feature to its rows' design matrices: one sandboxed process per plugin."""
    code = g.get("code") or []
    if not code:
        return [X for X, _ in rows]
    views = [v for _, v in rows]
    extra = [run_plugin(item["source"], views, timeout=timeout) for item in code]
    return [np.column_stack([X] + [cols[i] for cols in extra]) for i, (X, _) in enumerate(rows)]


def check_code(source, repeats=2):
    """Deterministic checks before a seat's code can be locked: it runs in the sandbox on real point-in-time views,
    returns usable columns, and returns the same columns every time."""
    import time

    panel = load_panel()
    month = target_months(panel)[-1]
    _, e, view_month = origin(panel, month)
    X, uni = _design_rows(panel, panel["Y"], e, month, view_month, BASELINE, np.random.default_rng(0))
    views = [_plugin_view(panel, panel["Y"], e, uni, month, view_month)]
    tm = month_add(month, -2)
    te = int(_month_days(panel, month_add(tm, -2)).max())
    _, uni2 = _design_rows(panel, panel["Y"], te, tm, month_add(tm, -2), BASELINE, np.random.default_rng(0))
    views.append(_plugin_view(panel, panel["Y"], te, uni2, tm, month_add(tm, -2)))
    outs, t0 = [], time.time()
    try:
        for _ in range(repeats):
            outs.append(run_plugin(source, views))
    except SandboxError as err:
        return dict(ok=False, deterministic=False, seconds=round(time.time() - t0, 1), error=str(err), columns=0)
    same = all(np.array_equal(a, b) for run in outs[1:] for a, b in zip(outs[0], run, strict=True))
    varies = any(float(np.std(a)) > 0 for a in outs[0])
    error = (
        "" if same and varies else "different output on a second run" if not same else "constant output: no information"
    )
    cols = int(outs[0][0].shape[1])
    return dict(ok=same and varies, deterministic=same, seconds=round(time.time() - t0, 1), error=error, columns=cols)


def predict_month(panel, Y, month, g):
    """Forecast target `month` as of its origin, from Y. Returns (station indices, dates, predictions)."""
    as_of, e, view_month = origin(panel, month)
    rng = np.random.default_rng(int(month))
    code = bool(g.get("code"))
    rows, ys = [], []
    for k in range(2, 2 + TRAIN_MONTHS):  # training targets: months M-2 .. M-13, all visible at as_of
        tm = month_add(month, -k)
        tdays = _month_days(panel, tm)
        if not len(tdays) or tdays.max() > e or month_add(tm, -2) not in panel["published"]:
            continue
        te = int(_month_days(panel, month_add(tm, -2)).max())
        if te < 56:
            continue
        X, uni = _design_rows(panel, Y, te, tm, month_add(tm, -2), g, rng)
        y = Y[np.ix_(uni, tdays)].reshape(-1)
        keep = np.ones(len(y), bool)
        if g.get("censor") and masked(panel, tm):  # latent demand: censored days say nothing about it
            keep = panel["C"][np.ix_(uni, tdays)].reshape(-1) == OK
        rows.append((X, _plugin_view(panel, Y, te, uni, tm, month_add(tm, -2)) if code else None))
        ys.append((y, keep))
    X, uni = _design_rows(panel, Y, e, month, view_month, g, rng)
    rows.append((X, _plugin_view(panel, Y, e, uni, month, view_month) if code else None))
    mats = _with_code(g, rows)
    Xtrain = np.vstack([m[k] for m, (_, k) in zip(mats[:-1], ys, strict=True)])
    ytrain = np.concatenate([y[k] for y, k in ys])
    model = _fit_glm(Xtrain, ytrain, 1.5 if g["tweedie"] else 1.0)
    return uni, month_dates(month), model(mats[-1]).reshape(len(uni), -1)


# ---------------------------------------------------------------------------- the lab contract
def _origins(design, key):
    window = DESIGNS[design]["window"]
    return [m for m in target_months(load_panel()) if m >= window and role(m) == key]


def design_checks(genome, design, key):
    """Guards the rigspec requires before lock: a latent-demand treatment needs every scored month masked."""
    needs = any(genome.get(f) for f in NEEDS_CENSOR_MASK)
    panel = load_panel()
    return {"censor_mask_available": not needs or all(masked(panel, m) for m in _origins(design, key))}


def evaluate(genome, design, key, cache):
    """abs_err[station, origin] and actual[station, origin] over the design's months of role `key`. In a masked
    month only uncensored station-days are scored, for both arms alike; the censor rate is reported."""
    ck = ("bikeshare", design, key, json.dumps(genome, sort_keys=True))
    if ck in cache:
        return cache[ck]
    panel, months = load_panel(), _origins(design, key)
    S = len(panel["stations"])
    abs_err, actual = np.zeros((S, len(months))), np.zeros((S, len(months)))
    censor_rate = []
    for j, m in enumerate(months):
        uni, _, pred = predict_month(panel, panel["Y"], m, genome)
        days = _month_days(panel, m)
        y = panel["Y"][np.ix_(uni, days)]
        keep = panel["C"][np.ix_(uni, days)] == OK if masked(panel, m) else np.ones_like(y, bool)
        abs_err[uni, j], actual[uni, j] = (np.abs(pred - y) * keep).sum(1), (y * keep).sum(1)
        censor_rate.append(float(1 - keep.mean()))
    out = dict(
        abs_err=abs_err,
        actual=actual,
        wape=abs_err.sum() / actual.sum(),
        origins=months,
        masked=[masked(panel, m) for m in months],
        censor_rate=censor_rate,
    )
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
