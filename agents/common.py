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
        if not r.strip():  # a reasoning model that spent its whole budget thinking returns nothing
            prompt += "\n\nYour last reply was empty: keep your reasoning brief and reply with ONE JSON object only."
        else:
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
    if hasattr(judge, "configure"):  # a real-data judge is pointed at its data before the check
        judge.configure(spec.get("judge_config", {}), spec.get("decision_standards", {}))
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


def evaluation_key(judge):
    """What a result depends on besides its config: the judge's declared evaluation key (scoring semantics + data), or
    its full digest. Used only to recognise repeats when planning; locks always stamp the full digest."""
    return judge.evaluation_key() if hasattr(judge, "evaluation_key") else judge_digest(judge)


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
    code = config.get("code") or []
    config = {k: v for k, v in config.items() if k != "code"}
    keys = [k for k, (_, p) in menu.items() if all(config.get(f) == v for f, v in p.items())]
    rebuilt = dict(judge.BASELINE)
    for k in keys:
        rebuilt.update(menu[k][1])
    if rebuilt != config:
        raise ValueError(f"config is not the baseline plus menu changes: {config}")
    parts = [judge.BASELINE_DESC] + [menu[k][0].lower() for k in keys]
    parts += [
        f"seat-written feature '{c['name']}' (code sha {hashlib.sha256(c['source'].encode()).hexdigest()[:12]})"
        for c in code
    ]
    return " + ".join(parts)


def decision_clause(std, alpha):
    """The decision rule of science/kernel.py::decide in words. Cites the SESOI only: the target effect
    sizes the design, it is not a threshold for the result."""
    s = f"{std['sesoi']:.1%}"
    return (
        f"Decision, on the {1 - alpha:.1%} two-way bootstrap CI of the relative WAPE reduction: supported if the "
        f"CI lies above zero and the point estimate is at least the SESOI of {s}; harmful if the CI lies below "
        f"zero; no effect if the CI lies within +-{s}; otherwise inconclusive."
    )


# ---------------------------------------------------------------------------- changes: menu items and seat ideas
def is_code(key):
    """A seat-proposed idea, implemented as code (ROADMAP 5), rather than a judge menu item."""
    return str(key).startswith("code:")


def change_desc(ctx, key):
    if is_code(key):
        idea = ctx["ideas"][key]
        return f"Add a seat-written feature '{idea['name']}': {idea['idea']}"
    return ctx["judge"].MENU[key][0]


def treatment_of(ctx, key, sid=None, champion=None):
    """The machine config a change makes of the champion. A code idea has one only once its code is written."""
    champion = ctx["champion"] if champion is None else champion
    if is_code(key):
        item = (ctx.get("code") or {}).get(sid)
        if item is None:
            raise ValueError(f"{sid}: the code for {key} has not been written yet")
        return dict(champion, code=list(champion.get("code") or []) + [dict(name=item["name"], source=item["source"])])
    return dict(champion, **ctx["judge"].MENU[key][1])


def statement_for(ctx, key, std, alpha):
    """The prereg statement, built only from the machine config, the change and the fixed decision standards. For a
    code idea it names the idea; the locked config carries the exact code."""
    J, champion = ctx["judge"], ctx["champion"]
    comparator = describe_config(J, champion)
    if is_code(key):
        treatment = f"{comparator} + seat-written feature '{ctx['ideas'][key]['name']}'"
    else:
        treatment = describe_config(J, dict(champion, **J.MENU[key][1]))
    return (
        f"Hypothesis: the change '{change_desc(ctx, key)}' reduces {J.TARGET} relative to the current champion. "
        f"Comparator (current champion): {comparator}. Treatment: {treatment}. {decision_clause(std, alpha)}"
    )


def prereg_statement(judge, champion, key, std, alpha):
    return statement_for(dict(judge=judge, champion=champion, ideas={}), key, std, alpha)


CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.S)


def extract_code(reply):
    """The Python source in a reply's fenced code block (the last one), or None."""
    blocks = CODE_FENCE.findall(reply or "")
    return blocks[-1].strip() + "\n" if blocks else None


# ---------------------------------------------------------------------------- methodologist
PREREG_KEYS = ["hid", "statement", "design", "kills_if", "rationale"]
LLM_PREREG_KEYS = ["design", "kills_if", "rationale"]  # the rest is generated from config


REVISION_CAP = 3
