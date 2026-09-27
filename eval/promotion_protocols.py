"""Demo: a herd of proposer agents improving a forecaster under two promotion protocols.

Proposers here are stochastic mutation operators with different priors (a stand-in for
LLM coding agents; each "specialist" edits a different part of the genome). The point of
the demo is the HARNESS, not the proposers: same candidate stream, different judge.

Protocols
- ratchet : accept if validation WAPE improves at all (autoresearch-style keep/discard).
- gated   : accept only if forecast_harness.gate() passes; lockbox read once at the end;
            the final champion ships only if it also beats the incumbent on the lockbox.
Truth: deployment-window WAPE (never visible to either protocol).
"""

import copy
import json
import os

import numpy as np

from judges import forecast as fh

OUT = os.environ.get("PROTOCOLS_OUT", "runs/protocols")

SPECIALISTS = {
    "feature_agent": ["lags", "rolls", "yoy", "trend", "cat", "series_mean"],
    "causal_agent": ["promo", "yoy"],
    "transform_agent": ["log", "clip"],
    "regular_agent": ["alpha", "window"],
}


# Gate settings. "gated_strict" = first design (FWER alpha-spending, 5/6 origins, 2% segment
# guard). "gated_calibrated" = settings chosen after the strict gate was shown to reject
# the largest real gains in synthetic worlds where truth is known.
GATES = {
    "gated_strict": dict(),
    "gated_calibrated": dict(alpha_total=None, min_rel=0.002, min_sign_frac=4 / 6, max_seg_regress=0.05),
}


PROTOCOLS = ("ratchet", "ratchet_canary", "gated_strict", "gated_calibrated")


def mutate(g, rng, keys):
    g = copy.deepcopy(g)
    k = keys[rng.integers(len(keys))]
    space = fh.SPACE[k]
    if k in ("lags", "rolls"):
        cur = set(g[k])
        x = space[rng.integers(len(space))]
        cur ^= {x}
        if not cur:
            cur = {x}
        g[k] = tuple(sorted(cur))
    else:
        opts = [v for v in space if v != g[k]]
        g[k] = opts[rng.integers(len(opts))]
    return g, k


def campaign(seed, protocol, n_rounds=40, herd=4, ledger=None):
    panel = fh.make_panel(seed)
    rng = np.random.default_rng(1000 + seed)  # same proposal RNG for both protocols
    grng = np.random.default_rng(2000 + seed)
    cache = {}
    champ_g = dict(fh.BASELINE)
    champ = fh.evaluate(panel, champ_g, fh.VAL_ORIGINS, cache)
    base_val = champ["wape"]
    base_dep = fh.evaluate(panel, champ_g, fh.DEPLOY_ORIGINS, cache, pit=True)["wape"]
    k = 0
    accepted = []
    for r in range(n_rounds):
        # one round = the herd proposes in parallel against the same champion
        props = []
        for name in list(SPECIALISTS)[:herd]:
            g, knob = mutate(champ_g, rng, SPECIALISTS[name])
            res = fh.evaluate(panel, g, fh.VAL_ORIGINS, cache)
            k += 1
            if protocol.startswith("ratchet"):
                ok, info = res["wape"] < champ["wape"], {"rel_gain": (champ["wape"] - res["wape"]) / champ["wape"]}
            else:
                ok, info = fh.gate(res, champ, k, panel["cat"], grng, **GATES[protocol])
            leak = None
            if ok and protocol != "ratchet":  # canary only on would-be promotions
                leak = fh.leak_canary(panel, g)
                ok = ok and not leak
            info["leak_flag"] = leak
            props.append((ok, res["wape"], g, knob, name, info))
            if ledger:
                ledger.log(
                    seed=seed,
                    protocol=protocol,
                    round=r,
                    k=k,
                    agent=name,
                    knob=knob,
                    val_wape=res["wape"],
                    accepted_candidate=bool(ok),
                    **info,
                )
        winners = [p for p in props if p[0]]
        if winners:  # refinery: merge the best passing MR only
            ok, w, g, knob, name, info = min(winners, key=lambda p: p[1])
            prev_dep = fh.evaluate(panel, champ_g, fh.DEPLOY_ORIGINS, cache, pit=True)["wape"]
            new_dep = fh.evaluate(panel, g, fh.DEPLOY_ORIGINS, cache, pit=True)["wape"]
            accepted.append(dict(round=r, knob=knob, agent=name, val_gain=champ["wape"] - w, dep_gain=prev_dep - new_dep))
            champ_g, champ = g, fh.evaluate(panel, g, fh.VAL_ORIGINS, cache)
    shipped = champ_g
    lock_ok = None
    if protocol != "ratchet":  # every protocol except the bare ratchet reads the lockbox once
        lb_new = fh.evaluate(panel, champ_g, fh.LOCKBOX_ORIGINS, cache)["wape"]
        lb_old = fh.evaluate(panel, fh.BASELINE, fh.LOCKBOX_ORIGINS, cache)["wape"]
        lock_ok = lb_new < lb_old
        if not lock_ok:
            shipped = dict(fh.BASELINE)
    fin_val = fh.evaluate(panel, shipped, fh.VAL_ORIGINS, cache)["wape"]
    fin_dep = fh.evaluate(panel, shipped, fh.DEPLOY_ORIGINS, cache, pit=True)["wape"]
    n_harm = sum(a["dep_gain"] < 0 for a in accepted)
    leaky_shipped = bool(shipped.get("series_mean"))
    return dict(
        seed=seed,
        protocol=protocol,
        candidates=k,
        accepted=len(accepted),
        harmful_accepts=n_harm,
        base_val=base_val,
        base_dep=base_dep,
        final_val=fin_val,
        final_dep=fin_dep,
        reported_gain_pct=100 * (base_val - fin_val) / base_val,
        true_gain_pct=100 * (base_dep - fin_dep) / base_dep,
        lockbox_pass=lock_ok,
        leaky_shipped=leaky_shipped,
        final_genome=json.dumps(shipped, default=str),
        accepted_knobs=",".join(a["knob"] for a in accepted),
    )


if __name__ == "__main__":
    import pandas as pd

    os.makedirs(OUT, exist_ok=True)
    led = fh.Ledger(f"{OUT}/campaign_ledger.jsonl")
    # seeds 0-9 were used to diagnose/calibrate the gate; report on fresh seeds 10-29
    rows = [
        dict(campaign(s, p, n_rounds=n, ledger=led), n_rounds=n)
        for n in (40, 120)
        for s in range(10, 30)
        for p in PROTOCOLS
    ]
    pd.DataFrame(rows).to_csv(f"{OUT}/campaign_results.csv", index=False)
