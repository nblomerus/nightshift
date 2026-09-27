"""Shared seat helpers and the lab's treatment menu / designs / controls (read by every seat)."""

from __future__ import annotations

import hashlib
import json
import re

from judges import forecast as fh
from science import kernel as sk

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


EXPLORATION_SEEDS = (6001, 6002)  # exploratory screens only; never used for confirmation


PILOT_SEEDS = (7001, 7002, 7003)  # power/controls only; never used for confirmatory tests


SEED_PURPOSES = {"primary": 1_000_000, "replication": 2_000_000, "extra_replication": 3_000_000}


def slice_seed(purpose, campaign, slot):
    """The panel seed for one slice's confirmatory data. Each purpose owns a block of a million seeds, far
    from the pilot and exploration seeds, so no seed serves two purposes or two slices (AGENTS.md invariant 9)."""
    if purpose not in SEED_PURPOSES or not 0 <= campaign < 1000 or not 0 <= slot < 1000:
        raise ValueError(f"no seed for {purpose!r}, campaign {campaign}, slot {slot}")
    return SEED_PURPOSES[purpose] + 1000 * campaign + slot


REPLICATION_CAP = 2  # replication attempts per locked prereg, the first included


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


JUDGE_PATH = fh.__file__  # the frozen judge; its digest is locked into every prereg


def judge_digest():
    with open(JUDGE_PATH, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def require_judge(rig, seat, sid, pre, to_stage, checks):
    """Before the judge runs: if its source changed since lock, refuse `to_stage` through the rig (logged)."""
    now = judge_digest()
    if now != pre.judge_digest:
        rig.advance(seat, sid, to_stage, checks=dict(checks, judge_unchanged=False))
    return now


def slice_grade(rig, sid):
    """The evidence grade from the slice's proof files: the decision and the LATEST replication attempt."""
    dec, repl = rig.read_proof(sid, "decision.json"), rig.read_proof(sid, "replication.json") or {}
    replicated = repl.get("decision") == "supported" and bool(repl.get("same_treatment"))
    return sk.evidence_grade(dec["decision"], replicated, deviations=len(rig.deviations(sid)), controls_ok=True)


def audit_locked(rig, sid, pre, seat, stage):
    """Compare the prereg in use with the body written at lock (proof/prereg_locked.json) and record every
    changed field once. Catches a change that was re-locked, which `Preregistration.verify` cannot see."""
    locked = rig.read_proof(sid, "prereg_locked.json")["body"]
    now = json.loads(json.dumps(pre._body(), default=str))
    seen = {(d["field"], json.dumps(d["after"], sort_keys=True)) for d in rig.deviations(sid)}
    for field in sorted(set(locked) | set(now)):
        before, after = locked.get(field), now.get(field)
        if before != after and (field, json.dumps(after, sort_keys=True)) not in seen:
            rig.record_deviation(sid, seat, field, before, after, f"found at {stage}; not in the locked prereg")


# ---------------------------------------------------------------------------- prereg text from config
def describe_config(config):
    """Plain-language description of a machine config: the baseline plus every MENU change it contains.
    Refuses a config that is not the baseline plus MENU changes, rather than describing it wrongly."""
    keys = [k for k, (_, p) in MENU.items() if all(config.get(f) == v for f, v in p.items())]
    rebuilt = dict(fh.BASELINE)
    for k in keys:
        rebuilt.update(MENU[k][1])
    if rebuilt != config:
        raise ValueError(f"config is not the baseline plus menu changes: {config}")
    return " + ".join([BASELINE_DESC] + [MENU[k][0].lower() for k in keys])


def decision_clause(std, alpha):
    """The decision rule of science/kernel.py::decide in words. Cites the SESOI only: the target effect
    sizes the design, it is not a threshold for the result."""
    s = f"{std['sesoi']:.1%}"
    return (
        f"Decision, on the {1 - alpha:.1%} two-way bootstrap CI of the relative WAPE reduction: supported if the "
        f"CI lies above zero and the point estimate is at least the SESOI of {s}; harmful if the CI lies below "
        f"zero; no effect if the CI lies within +-{s}; otherwise inconclusive."
    )


def prereg_statement(champion, key, std, alpha):
    """The prereg statement, built only from the machine config and the fixed decision standards."""
    comparator = describe_config(champion)
    treatment = describe_config(dict(champion, **MENU[key][1]))
    return (
        f"Hypothesis: the change '{MENU[key][0]}' reduces next-4-week WAPE relative to the current champion. "
        f"Comparator (current champion): {comparator}. Treatment: {treatment}. {decision_clause(std, alpha)}"
    )


# ---------------------------------------------------------------------------- methodologist
PREREG_KEYS = ["hid", "statement", "design", "kills_if", "rationale"]
LLM_PREREG_KEYS = ["design", "kills_if", "rationale"]  # the rest is generated from config


REVISION_CAP = 3
