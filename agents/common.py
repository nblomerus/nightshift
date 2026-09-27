"""Shared seat helpers and the lab's treatment menu / designs / controls (read by every seat)."""

from __future__ import annotations

import json
import re

from judges import forecast as fh

COMPARATOR_DESC = "the current champion: pooled ridge on demand lags 1-4 and 4/13-week rolling means"


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


EXPLORATION_SEEDS = (6001, 6002)  # exploratory screens only; never used for confirmation


PILOT_SEEDS = (7001, 7002, 7003)  # power/controls only; never used for confirmatory tests


POSITIVE_CONTROL = dict(fh.BASELINE, yoy=True)  # known large effect


REFERENCE_EFFECT = dict(fh.BASELINE, promo=True)  # known effect near SESOI: sets the variance for power


PLACEBO = dict(fh.BASELINE, noise=5)  # negative control


# ---------------------------------------------------------------------------- helpers
def ask_json(llm, seat_spec, system, prompt, retries=1):
    for _attempt in range(retries + 1):
        r = llm(prompt, system=system, tier=seat_spec["tier"])
        m = re.search(r"\{.*\}", r, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        prompt += "\n\nYour last reply was not valid JSON. Reply with ONE JSON object only."
    raise ValueError(f"no JSON from LLM: {r[:200]}")


def persona(rig, seat, extra=""):
    s = rig.spec["seats"][seat]
    return (
        f"You are {seat}, the {s['role']} of a research lab whose mission is: {rig.spec['mission']} "
        f"You own: {s['owns']}. Be concise and precise. {extra}"
    )


def evaluate_arm(genome, design, seed, cache):
    d = DESIGNS[design]
    panel = cache.setdefault(("panel", seed, design), fh.make_panel(seed, T=d["T"]))
    return fh.evaluate(panel, genome, d["origins"], cache.setdefault(("ev", seed, design), {}))


# ---------------------------------------------------------------------------- methodologist
PREREG_KEYS = ["hid", "statement", "design", "kills_if", "rationale"]


REVISION_CAP = 3
