"""science_kernel — the parts of the scientific method an autonomous lab must NOT delegate to an LLM.

LLM agents may propose questions, write hypotheses, design treatments and narrate results.
This module owns what makes the result trustworthy, and it is deterministic code:

  Preregistration   typed, hashed, locked BEFORE any data for the test is generated
  Decision          computed from unit-level paired data by the locked rule (not by an LLM)
  Multiplicity      lab-wide online FDR ledger (LOND), so 1,000 autonomous tests != 50 false wins
  Controls          positive (planted effect) + negative (placebo) must pass for a protocol to count
  Replication       'supported' becomes 'replicated' only on an independent re-run of the locked prereg
  Deviations        any change after locking is recorded and downgrades the evidence grade

Decision labels (minimum-effect + equivalence framing, cf. Lakens et al. 2018):
  supported      CI lower bound > 0 and point estimate >= SESOI
  harmful        CI upper bound < 0
  no_effect      CI entirely inside (-SESOI, +SESOI)   <- a real negative result
  inconclusive   anything else (report it; never round it up)
"""

from __future__ import annotations

import dataclasses as dc
import hashlib
import json
import time
from collections.abc import Callable
from typing import Literal

import numpy as np

Decision = Literal["supported", "harmful", "no_effect", "inconclusive"]


@dc.dataclass(frozen=True)
class Preregistration:
    hid: str
    statement: str  # plain-language hypothesis
    estimand: str  # e.g. "relative WAPE reduction, treatment vs comparator"
    treatment: dict  # what changes (a config/genome or a code ref + hash)
    comparator: dict  # the control arm — REQUIRED, never implicit
    primary_metric: str
    unit: str  # unit of resampling, e.g. "series" (cluster)
    sesoi: float  # smallest effect size of interest (same units as estimand)
    alpha: float = 0.05  # nominal; the ledger may spend less
    n_boot: int = 2000
    design: dict = dc.field(default_factory=dict)  # origins, data slice, seeds — fixed up front
    kills_if: str = ""  # what result would make the PI drop the direction
    judge_digest: str = ""  # SHA-256 of the frozen judge's source at lock; results must be produced by it
    # Smallest improvement that is "supported" (promotes after replication); None = the SESOI (the original rule).
    # A rig that seeks any reliable improvement sets 0: supported then means the CI lies above zero.
    min_effect: float | None = None
    locked_at: float = 0.0
    digest: str = ""

    def _body(self):
        body = {k: v for k, v in dc.asdict(self).items() if k not in ("locked_at", "digest")}
        if body["min_effect"] is None:  # absent from every prereg locked before the field existed: digests unchanged
            del body["min_effect"]
        return body

    def lock(self) -> Preregistration:
        d = hashlib.sha256(json.dumps(self._body(), sort_keys=True, default=str).encode()).hexdigest()
        return dc.replace(self, locked_at=time.time(), digest=d)

    def verify(self) -> bool:
        return self.digest == hashlib.sha256(json.dumps(self._body(), sort_keys=True, default=str).encode()).hexdigest()


def paired_effect(err_t, err_c, alpha: float, n_boot: int, rng, two_way: bool = True) -> dict:
    """Relative WAPE reduction (positive = treatment better).
    err_*: [units, origins] absolute errors on the same units/origins (paired design).
    two_way=False: cluster bootstrap over units only (ignores shocks shared across units in time).
    two_way=True : pigeonhole bootstrap (Owen 2007) — resample units AND origins independently,
                   so time-to-time variation in the effect widens the interval."""
    point = 1 - err_t.sum() / err_c.sum()
    n_units, n_origins = err_t.shape
    if not two_way:
        et, ec = err_t.sum(1), err_c.sum(1)
        idx = rng.integers(0, n_units, (n_boot, n_units))
        boot = 1 - et[idx].sum(1) / ec[idx].sum(1)
    else:
        boot = np.empty(n_boot)
        for b in range(n_boot):
            si, oi = rng.integers(0, n_units, n_units), rng.integers(0, n_origins, n_origins)
            boot[b] = 1 - err_t[np.ix_(si, oi)].sum() / err_c[np.ix_(si, oi)].sum()
    lo, hi = np.quantile(boot, [alpha / 2, 1 - alpha / 2])
    return dict(point=float(point), lo=float(lo), hi=float(hi))


def decide(est: dict, sesoi: float, min_effect: float | None = None) -> Decision:
    """supported: the CI lies above zero and the point is at least `min_effect` (the SESOI when None); harmful: the CI
    lies below zero; no_effect: the CI lies within +-SESOI; otherwise inconclusive."""
    if est["lo"] > 0 and est["point"] >= (sesoi if min_effect is None else min_effect):
        return "supported"
    if est["hi"] < 0:
        return "harmful"
    if est["lo"] > -sesoi and est["hi"] < sesoi:
        return "no_effect"
    return "inconclusive"


class FDRLedger:
    """LOND online FDR (Javanmard & Montanari 2018): alpha_i = alpha * gamma_i * (D_{i-1} + 1),
    with gamma_i proportional to 1/i^1.6 and summing to 1. Controls FDR over an unbounded
    stream of lab-wide tests; every test, whatever its outcome, consumes a slot."""

    def __init__(self, alpha: float = 0.05, horizon: int = 100_000):
        g = 1.0 / np.arange(1, horizon + 1) ** 1.6
        self.gamma = g / g.sum()
        self.alpha, self.i, self.discoveries, self.rows = alpha, 0, 0, []

    def next_alpha(self) -> float:
        return float(self.alpha * self.gamma[self.i] * (self.discoveries + 1))

    def record(self, prereg: Preregistration, alpha_used: float, est: dict, decision: Decision, **extra):
        assert prereg.verify(), "prereg was modified after locking"
        self.i += 1
        self.discoveries += decision == "supported"
        self.rows.append(
            dict(hid=prereg.hid, digest=prereg.digest[:12], alpha=alpha_used, decision=decision, **est, **extra)
        )


def run_test(prereg: Preregistration, run_arm: Callable[[dict], dict], rng, ledger: FDRLedger | None = None) -> dict:
    """Execute a LOCKED prereg: run both arms under the frozen judge, decide by the locked rule.
    The resampling scheme is part of the prereg: design={'bootstrap': 'two_way'|'units'}."""
    assert prereg.digest and prereg.verify(), "run_test requires a locked, unmodified prereg"
    alpha = ledger.next_alpha() if ledger else prereg.alpha
    t, c = run_arm(prereg.treatment), run_arm(prereg.comparator)
    two_way = prereg.design.get("bootstrap", "two_way") == "two_way"
    est = paired_effect(t["abs_err"], c["abs_err"], alpha, prereg.n_boot, rng, two_way=two_way)
    dec = decide(est, prereg.sesoi, prereg.min_effect)
    if ledger is not None:
        ledger.record(prereg, alpha, est, dec)
    return dict(decision=dec, alpha=alpha, **est)


def evidence_grade(decision: Decision, replicated: bool | None, deviations: int, controls_ok: bool) -> str:
    """Ordinal grade the lab's status ladder should read, instead of an LLM-reported confidence. `replicated` is
    None before any replication, True when the replication reached the same decision, False when it did not: a
    failed replication stays at B, and says so rather than "awaiting"."""
    if not controls_ok:
        return "D: protocol failed controls"
    if deviations:
        return "C: deviated from prereg (exploratory)"
    status = {None: "awaiting replication", False: "not replicated"}
    if decision == "supported":
        return "A: replicated" if replicated else f"B: supported, {status[replicated]}"
    if decision in ("no_effect", "harmful"):
        return "A: negative result, replicated" if replicated else f"B: negative result, {status[replicated]}"
    return "C: inconclusive"
