"""Frozen evaluation harness for autonomous forecast-improvement campaigns.

Agents may edit the CANDIDATE (a genome / candidate.py). They may never edit this file,
the data split, the metric, or the gate. This file is the "judge" (prepare.py in the
autoresearch pattern; the Refinery's verification gate in a Gas Town rig).

Contents
- make_panel(): synthetic weekly demand panel (NegBin, seasonality, Black-Friday spike,
  known-in-advance promotions, common AR(1) shock). Stand-in for real data.
- Split: validation origins (agents see scores), lockbox origins (one read per campaign),
  deployment origins (never seen; ground truth for the demo only).
- featurize()/fit_predict(): pooled ridge on a configurable feature genome, direct target
  = next-4-week unit sum (mirrors a next-30-day shipped-units target).
- evaluate(): rolling-origin WAPE plus per-series and per-origin error components.
- gate(): promotion rule = min effect + sequential alpha-spending z-test with a
  series-cluster bootstrap SE + sign consistency across origins + no segment regression.
- Ledger: every evaluation appended to JSONL (the audit trail / "beads").
"""

from __future__ import annotations

import json
import math
import time

import numpy as np

H = 4  # target = sum of next 4 weeks
T_TOTAL = 184
VAL_ORIGINS = list(range(110, 131, 4))  # 6 origins, agents may query
LOCKBOX_ORIGINS = list(range(134, 147, 4))  # 4 origins, read once per campaign
DEPLOY_ORIGINS = list(range(150, 179, 4))  # 8 origins, never visible (demo truth)
MIN_TRAIN_T = 56

BASELINE = dict(
    lags=(1, 2, 3, 4),
    rolls=(4, 13),
    yoy=False,
    promo=False,
    log=False,
    trend=False,
    cat=False,
    alpha=1.0,
    clip=None,
    window=None,
    series_mean=False,
)
SPACE = dict(
    lags=(1, 2, 3, 4, 6, 8, 13),
    rolls=(4, 8, 13, 26),
    yoy=(False, True),
    promo=(False, True),
    log=(False, True),
    trend=(False, True),
    cat=(False, True),
    alpha=(0.01, 0.1, 1.0, 10.0, 100.0),
    clip=(None, 0.99, 0.995),
    window=(None, 104, 52),
    # series_mean: mean of each series over ALL columns in the panel. Looks like a
    # harmless level feature, but on a full backtest panel it reads the future.
    series_mean=(False, True),
)


# ----------------------------------------------------------------------------- data
def make_panel(seed: int, S: int = 240, n_cat: int = 6, T: int = T_TOTAL):
    rng = np.random.default_rng(seed)
    cat = rng.integers(0, n_cat, S)
    level = np.exp(rng.normal(np.log(20), 1.0, S))
    amp = rng.uniform(0.1, 0.6, n_cat)[cat]
    phase = rng.uniform(0, 52, n_cat)[cat]
    bf = rng.uniform(0.2, 1.0, n_cat)[cat]
    g = rng.normal(0, 0.1, S)
    t = np.arange(T)
    woy = t % 52
    season = 1 + amp[:, None] * np.sin(2 * np.pi * (t[None, :] + phase[:, None]) / 52)
    season *= 1 + bf[:, None] * ((woy == 47) | (woy == 48))[None, :]
    trend = np.exp(g[:, None] * t[None, :] / 52)
    promo = rng.random((S, T)) < 0.08
    lift = np.exp(rng.normal(0.45, 0.15, S))
    shock = np.zeros(T)
    for i in range(1, T):
        shock[i] = 0.7 * shock[i - 1] + rng.normal(0, 0.05)
    mu = level[:, None] * season * trend * np.where(promo, lift[:, None], 1.0) * np.exp(shock)[None, :]
    k = 5.0
    y = rng.poisson(rng.gamma(k, mu / k)).astype(float)
    return dict(y=y, promo=promo.astype(float), cat=cat, n_cat=n_cat)


# ------------------------------------------------------------------------- features
def _roll_mean(y, w):
    c = np.cumsum(np.pad(y, ((0, 0), (1, 0))), axis=1)
    out = np.full_like(y, np.nan)
    out[:, w - 1 :] = (c[:, w:] - c[:, :-w]) / w
    return out


def featurize(panel, g):
    """Return X[S, T, F] for origin t (uses data <= t, plus known future promos) and
    target Y[S, T] = sum y[t+1..t+H]."""
    y, promo = panel["y"], panel["promo"]
    S, T = y.shape
    tr = np.log1p if g["log"] else (lambda a: a)
    feats = []
    for l in g["lags"]:
        f = np.full_like(y, np.nan)
        f[:, l - 1 :] = y[:, : T - l + 1]
        feats.append(tr(f))
    rolls = {w: _roll_mean(y, w) for w in set(g["rolls"]) | {4, 13}}
    for w in g["rolls"]:
        feats.append(tr(rolls[w] * H))
    if g["yoy"]:
        f = np.full_like(y, np.nan)
        s4 = np.cumsum(np.pad(y, ((0, 0), (1, 0))), axis=1)
        # last year's same next-4-week window: y[t-51 .. t-48]
        for t in range(51, T):
            f[:, t] = s4[:, t - 47] - s4[:, t - 51]
        feats.append(tr(f))
    if g["promo"]:
        pf = np.zeros_like(y)
        for h in range(1, H + 1):
            pf[:, : T - h] += promo[:, h:]
        feats.append(pf)
        feats.append(pf * (tr(rolls[13] * H) if g["log"] else rolls[13]))
    if g["trend"]:
        feats.append(np.log((rolls[4] + 1) / (rolls[13] + 1)))
    if g.get("series_mean"):
        feats.append(np.repeat(tr(np.nanmean(y, axis=1, keepdims=True) * H), T, axis=1))
    if g.get("noise"):
        # placebo: pure-noise columns (negative control; true effect ~0 or slightly harmful)
        nr = np.random.default_rng(12345)
        for _ in range(int(g["noise"])):
            feats.append(nr.normal(size=y.shape))
    if g["cat"]:
        for c in range(panel["n_cat"] - 1):
            feats.append(np.repeat((panel["cat"] == c)[:, None], T, axis=1).astype(float))
    X = np.stack(feats, axis=2)
    Y = np.full_like(y, np.nan)
    c = np.cumsum(np.pad(y, ((0, 0), (1, 0))), axis=1)
    Y[:, : T - H] = c[:, H + 1 : T + 1] - c[:, 1 : T - H + 1]  # sum y[t+1..t+H]
    return X, Y


def fit_predict(X, Y, g, origin):
    """Fit pooled ridge on origins t with t+H <= origin; predict at origin."""
    lo = MIN_TRAIN_T if g["window"] is None else max(MIN_TRAIN_T, origin - H - g["window"])
    Xt = X[:, lo : origin - H + 1].reshape(-1, X.shape[2])
    yt = Y[:, lo : origin - H + 1].reshape(-1)
    ok = np.isfinite(Xt).all(1) & np.isfinite(yt)
    Xt, yt = Xt[ok], yt[ok]
    if g["clip"] is not None:
        yt = np.minimum(yt, np.quantile(yt, g["clip"]))
    if g["log"]:
        yt = np.log1p(yt)
    mu, sd = Xt.mean(0), Xt.std(0) + 1e-9
    Z = (Xt - mu) / sd
    Z1 = np.hstack([Z, np.ones((len(Z), 1))])
    A = Z1.T @ Z1 + g["alpha"] * np.diag(np.r_[np.ones(Z.shape[1]), 0.0])
    beta = np.linalg.solve(A, Z1.T @ yt)
    Xo = np.nan_to_num((X[:, origin, :] - mu) / sd)
    p = np.hstack([Xo, np.ones((len(Xo), 1))]) @ beta
    p = np.expm1(p) if g["log"] else p
    return np.maximum(p, 0.0)


# ----------------------------------------------------------------------- evaluation
def truncate(panel, origin):
    """Point-in-time view: demand after `origin` is unknown (NaN); planned promotions stay."""
    p = dict(panel)
    y = panel["y"].copy()
    y[:, origin + 1 :] = np.nan
    p["y"] = y
    return p


def evaluate(panel, g, origins, cache=None, pit=False):
    """pit=False: one featurisation of the full panel (fast backtest, what agents see).
    pit=True: re-featurise a truncated panel per origin (production replay)."""
    key = json.dumps(g, sort_keys=True, default=str)
    if cache is not None and (key, tuple(origins), pit) in cache:
        return cache[(key, tuple(origins), pit)]
    X, Y = featurize(panel, g)
    abs_err = np.zeros((X.shape[0], len(origins)))
    actual = np.zeros_like(abs_err)
    for j, o in enumerate(origins):
        if pit:
            Xp, Yp = featurize(truncate(panel, o), g)
            p = fit_predict(Xp, Yp, g, o)
        else:
            p = fit_predict(X, Y, g, o)
        abs_err[:, j] = np.abs(p - Y[:, o])
        actual[:, j] = Y[:, o]
    res = dict(
        wape=abs_err.sum() / actual.sum(), abs_err=abs_err, actual=actual, wape_by_origin=abs_err.sum(0) / actual.sum(0)
    )
    if cache is not None:
        cache[(key, tuple(origins), pit)] = res
    return res


def leak_canary(panel, g, origin=VAL_ORIGINS[0], tol=1e-6):
    """True if predictions at `origin` change when the future is hidden (=> leakage)."""
    X, Y = featurize(panel, g)
    a = fit_predict(X, Y, g, origin)
    Xp, Yp = featurize(truncate(panel, origin), g)
    b = fit_predict(Xp, Yp, g, origin)
    return bool(np.max(np.abs(a - b) / (np.abs(a) + 1)) > tol)


def gate(cand, champ, k, cat, rng, alpha_total=0.05, min_rel=0.005, B=300, min_sign_frac=5 / 6, max_seg_regress=0.02):
    """Promotion decision for the k-th candidate tested in this campaign (k>=1)."""
    d = cand["wape"] - champ["wape"]
    rel = -d / champ["wape"]
    S = cand["abs_err"].shape[0]
    idx = rng.integers(0, S, (B, S))
    ce, ch, ac = cand["abs_err"].sum(1), champ["abs_err"].sum(1), cand["actual"].sum(1)
    boot = (ce[idx].sum(1) - ch[idx].sum(1)) / ac[idx].sum(1)
    se = boot.std() + 1e-12
    z = -d / se
    # alpha_total set -> FWER alpha-spending over the campaign (sums to alpha_total);
    # alpha_total None -> fixed per-test alpha (0.01), relying on min effect + lockbox.
    alpha_k = alpha_total * 6 / (math.pi**2 * k**2) if alpha_total else 0.01
    p = 0.5 * math.erfc(z / math.sqrt(2))
    sign_frac = float((cand["wape_by_origin"] < champ["wape_by_origin"]).mean())
    seg = []
    for c in np.unique(cat):
        m = cat == c
        wc = cand["abs_err"][m].sum() / cand["actual"][m].sum()
        wh = champ["abs_err"][m].sum() / champ["actual"][m].sum()
        seg.append((wc - wh) / wh)
    worst_seg = float(max(seg))
    ok = (rel >= min_rel) and (p < alpha_k) and (sign_frac >= min_sign_frac) and (worst_seg <= max_seg_regress)
    return ok, dict(
        rel_gain=float(rel), z=float(z), p=float(p), alpha_k=float(alpha_k), sign_frac=sign_frac, worst_seg=worst_seg
    )


class Ledger:
    def __init__(self, path):
        self.path = path
        open(path, "w").close()

    def log(self, **row):
        row["ts"] = time.time()
        with open(self.path, "a") as f:
            f.write(json.dumps(row, default=str) + "\n")
