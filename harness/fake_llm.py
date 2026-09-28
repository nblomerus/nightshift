"""A deterministic stand-in LLM for tests and offline demos. It answers each seat's prompt with valid JSON
so the whole workflow can run without a model. It is NOT a model of good behaviour: the critic always
approves and the PI picks the top of the exploratory screen."""

from __future__ import annotations

import json
import re

from agents.common import MENU

ORIGINAL_CHAMPION = "pooled ridge on demand lags 1-4 and 4/13-week rolling means"


def _key_in(text: str) -> str | None:
    for k, (desc, _) in MENU.items():
        if desc.lower() in text.lower() or k in text:
            return k
    return None


def fake_llm(prompt: str, system: str | None = None, tier: str | None = None) -> str:
    who = (system or "").split(",")[0]
    if "pi@" in who and "Pick up to TWO" in prompt:
        screen = re.findall(r"^- ([a-z_]+): ([+-][0-9.]+)%", prompt.split("EXPLORATORY screen")[1], re.M)
        tested_a = set(re.findall(r"campaign \d+ ([a-z_]+) on .*grade A", prompt))
        picks = [k for k, v in screen if float(v) > 0.5 and k not in tested_a][:2]
        return json.dumps(
            {
                "picks": [{"key": k, "rationale": f"top exploratory screen result ({k})"} for k in picks],
                "lesson": "screens rank; only confirmatory tests count",
            }
        )
    if "pi@" in who:
        return json.dumps({"next": "continue", "agenda_update": "see evidence ledger"})
    if "methodologist@" in who and "Draft a preregistration" in prompt:
        m = re.search(r"nothing else: '(.+?)'\. ", prompt)
        key = _key_in(m.group(1)) if m else None
        desc = MENU[key][0] if key else "the treatment"
        design = "C" if "larger design C" in prompt else "B"
        return json.dumps(
            {
                "hid": f"H-{key}",
                # stale on purpose, like the real model after a promotion: it names the ORIGINAL champion
                "statement": f"{desc}, compared with {ORIGINAL_CHAMPION}, reduces next-4-week WAPE.",
                "design": design,
                "kills_if": "CI lies within +-SESOI or below zero",
                "rationale": "fake",
            }
        )
    if "methodologist@" in who:
        return json.dumps({"answer": "The prereg is authoritative."})
    if "critic@" in who:
        return json.dumps({"verdict": "approve", "blocking": [], "message": "ok", "new_hypothesis_for_pi": None})
    if "experimenter@" in who:
        # strict: the statement must name the comparator the judge will actually run
        statement = prompt.split("Draft prereg statement:\n")[1].split("\n")[0]
        champion = re.search(r"against (.+?)\.\n", prompt).group(1)
        ok = champion in statement
        return json.dumps({"implementable_exactly": ok, "mismatch": "" if ok else "stale comparator", "message": ""})
    if "replicator@" in who:
        return json.dumps({"key": _key_in(prompt.split("Statement:")[1].split(". ")[0]) or "", "reasoning": "text match"})
    if "writer@" in who:
        return json.dumps({"headline": "Result as decided by the kernel", "finding_md": "Fake write-up."})
    return "{}"
