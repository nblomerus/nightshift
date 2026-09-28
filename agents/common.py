"""Shared seat helpers. The domain (baseline, menu, designs, controls, data) comes from the judge the rigspec
names, as ctx["judge"]; see judges/forecast_lab.py for the contract."""

from __future__ import annotations

import hashlib
import importlib
import json
import re

from science import kernel as sk

REPLICATION_CAP = 2  # replication attempts per locked prereg, the first included


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


JUDGE_API = ("NAME", "TARGET", "BASELINE", "BASELINE_DESC", "MENU", "DESIGNS", "POSITIVE_CONTROL", "PLACEBO", "FILES",
             "data_keys", "evaluate", "leak_canary")  # fmt: skip


def load_judge(spec):
    """The judge module the rigspec names. Refuses a missing or incomplete one before the lab starts."""
    name = spec.get("judge")
    if not name:
        raise ValueError("rigspec names no judge")
    try:
        judge = importlib.import_module(name)
    except ImportError as e:
        raise ValueError(f"rigspec judge {name!r} cannot be imported: {e}") from e
    missing = [a for a in JUDGE_API if not hasattr(judge, a)]
    if missing:
        raise ValueError(f"rigspec judge {name!r} lacks {missing}")
    return judge


def judge_digest(judge):
    """SHA-256 over the judge's source files, in order (the frozen judge and its adapter)."""
    h = hashlib.sha256()
    for path in judge.FILES:
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def require_judge(rig, seat, sid, pre, to_stage, checks, judge):
    """Before the judge runs: if its source changed since lock, refuse `to_stage` through the rig (logged)."""
    now = judge_digest(judge)
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
def describe_config(judge, config):
    """Plain-language description of a machine config: the baseline plus every MENU change it contains.
    Refuses a config that is not the baseline plus MENU changes, rather than describing it wrongly."""
    menu = judge.MENU
    keys = [k for k, (_, p) in menu.items() if all(config.get(f) == v for f, v in p.items())]
    rebuilt = dict(judge.BASELINE)
    for k in keys:
        rebuilt.update(menu[k][1])
    if rebuilt != config:
        raise ValueError(f"config is not the baseline plus menu changes: {config}")
    return " + ".join([judge.BASELINE_DESC] + [menu[k][0].lower() for k in keys])


def decision_clause(std, alpha):
    """The decision rule of science/kernel.py::decide in words. Cites the SESOI only: the target effect
    sizes the design, it is not a threshold for the result."""
    s = f"{std['sesoi']:.1%}"
    return (
        f"Decision, on the {1 - alpha:.1%} two-way bootstrap CI of the relative WAPE reduction: supported if the "
        f"CI lies above zero and the point estimate is at least the SESOI of {s}; harmful if the CI lies below "
        f"zero; no effect if the CI lies within +-{s}; otherwise inconclusive."
    )


def prereg_statement(judge, champion, key, std, alpha):
    """The prereg statement, built only from the machine config and the fixed decision standards."""
    comparator = describe_config(judge, champion)
    treatment = describe_config(judge, dict(champion, **judge.MENU[key][1]))
    return (
        f"Hypothesis: the change '{judge.MENU[key][0]}' reduces {judge.TARGET} relative to the current champion. "
        f"Comparator (current champion): {comparator}. Treatment: {treatment}. {decision_clause(std, alpha)}"
    )


# ---------------------------------------------------------------------------- methodologist
PREREG_KEYS = ["hid", "statement", "design", "kills_if", "rationale"]
LLM_PREREG_KEYS = ["design", "kills_if", "rationale"]  # the rest is generated from config


REVISION_CAP = 3
