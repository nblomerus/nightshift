"""Lab adapter for the frozen synthetic forecasting judge (judges/forecast.py), which it does not modify.

The rigspec names this module (`"judge": "judges.forecast_lab"`); seats reach data and treatments only through
it. Every lab judge exposes the same names:

    NAME, TARGET, BASELINE, BASELINE_DESC, MENU, DESIGNS, POSITIVE_CONTROL, PLACEBO, FILES
    data_keys(purpose, campaign=0, slot=0)      which data a purpose may use (AGENTS.md invariant 9)
    evaluate(genome, design, key, cache)        -> dict with unit-level abs_err[unit, origin]
    leak_canary(genome, design, key, cache)     -> True if predictions change when the future is hidden

FILES lists the sources whose SHA-256 is locked into every prereg (ROADMAP 4): the judge and this adapter, since
the menu and designs decide what gets evaluated.
"""

from __future__ import annotations

from judges import forecast as fh

NAME = "forecast"
TARGET = "next-4-week WAPE"
FILES = (fh.__file__, __file__)

BASELINE = fh.BASELINE
BASELINE_DESC = "pooled ridge on demand lags 1-4 and 4/13-week rolling means"

MENU = {
    "log_target": ("Model log(1+demand) instead of raw demand", {"log": True}),
    "promo_feature": ("Add the known-in-advance count of promotion weeks in the forecast window", {"promo": True}),
    "category_effects": ("Add product-category indicator features", {"cat": True}),
    "trend_feature": ("Add a 4-week vs 13-week rolling-mean trend ratio", {"trend": True}),
    "strong_ridge": ("Increase ridge regularisation from alpha=1 to alpha=100", {"alpha": 100.0}),
    "short_window": ("Train only on the most recent 52 weeks", {"window": 52}),
    "clip_outliers": ("Clip training targets at their 99th percentile", {"clip": 0.99}),
    "last_year_window": ("Add last year's demand over the same 4-week window as a feature", {"yoy": True}),
}

DESIGNS = {
    "A": dict(
        desc="6 rolling origins (weeks 110-130) on a 184-week history; compute cost 1x",
        T=184,
        origins=list(fh.VAL_ORIGINS),
    ),
    "B": dict(
        desc="32 rolling origins (weeks 110-234) on a 260-week history; compute cost ~5x",
        T=260,
        origins=list(range(110, 235, 4)),
    ),
    "C": dict(
        desc="58 rolling origins (weeks 110-338) on a 364-week history; compute cost ~10x",
        T=364,
        origins=list(range(110, 339, 4)),
    ),
}

POSITIVE_CONTROL = dict(BASELINE, yoy=True)  # known large effect
PLACEBO = dict(BASELINE, noise=5)  # negative control

# ---------------------------------------------------------------------------- data (invariant 9)
EXPLORATION_SEEDS = (6001, 6002)  # exploratory screens only; never used for confirmation
PILOT_SEEDS = (7001, 7002, 7003)  # power/controls only; never used for confirmatory tests
SEED_PURPOSES = {"primary": 1_000_000, "replication": 2_000_000, "extra_replication": 3_000_000}


def slice_seed(purpose, campaign, slot):
    """The panel seed for one slice's confirmatory data. Each purpose owns a block of a million seeds, far
    from the pilot and exploration seeds, so no seed serves two purposes or two slices (AGENTS.md invariant 9)."""
    if purpose not in SEED_PURPOSES or not 0 <= campaign < 1000 or not 0 <= slot < 1000:
        raise ValueError(f"no seed for {purpose!r}, campaign {campaign}, slot {slot}")
    return SEED_PURPOSES[purpose] + 1000 * campaign + slot


def data_keys(purpose, campaign=0, slot=0):
    """Pilot and exploration get fixed panels; each slice gets fresh ones per purpose."""
    if purpose == "pilot":
        return PILOT_SEEDS
    if purpose == "exploration":
        return EXPLORATION_SEEDS
    return (slice_seed(purpose, campaign, slot),)


# ---------------------------------------------------------------------------- evaluation
def _panel(design, key, cache):
    k = ("panel", key, design)
    if k not in cache:
        cache[k] = fh.make_panel(key, T=DESIGNS[design]["T"])
    return cache[k]


def evaluate(genome, design, key, cache):
    panel = _panel(design, key, cache)
    return fh.evaluate(panel, genome, DESIGNS[design]["origins"], cache.setdefault(("ev", key, design), {}))


def leak_canary(genome, design, key, cache):
    return fh.leak_canary(_panel(design, key, cache), genome, origin=DESIGNS[design]["origins"][0])
