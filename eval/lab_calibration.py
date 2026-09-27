"""Calibrate the LAB, not just the model: how often does each decision procedure make false claims?

A bank of forecasting hypotheses ("changing knob X improves next-4-week WAPE") whose TRUE effects
are known, because they are estimated on 40 held-out synthetic panels from the same process. Simulated
labs test every hypothesis once, in random order, each on a fresh panel, under four procedures:

  single_run_threshold  one run; point estimate vs the stated threshold -> supported / refuted
                        (how a free-text 'decision: >=1% gain' hypothesis is read off one experiment)
  prereg_ci             locked prereg; cluster-bootstrap CI; minimum-effect/equivalence decision; alpha 0.05
  prereg_ci_fdr         as above, alpha from a lab-wide LOND online-FDR ledger
  prereg_fdr_replicated as above, and 'supported' only if an independent re-run of the same locked
                        prereg (fresh panel) is also 'supported'
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from judges import forecast as fh
from science import kernel as sk

OUT = os.environ.get("CALIBRATION_OUT", "runs/calibration")

SESOI = 0.01  # 1% relative WAPE reduction
BASE0 = dict(fh.BASELINE)
BASE1 = dict(fh.BASELINE, yoy=True, promo=True, log=True)
CHANGES = [
    ("yoy", True),
    ("promo", True),
    ("log", True),
    ("cat", True),
    ("trend", True),
    ("rolls", (4, 13, 26)),
    ("lags", (1, 2, 3, 4, 13)),
    ("alpha", 100.0),
    ("alpha", 0.01),
    ("clip", 0.99),
    ("window", 52),
    ("noise", 5),
]


def bank():
    hyps = []
    for bname, base in (("base0", BASE0), ("base1", BASE1)):
        for k, v in CHANGES:
            if base.get(k) == v:  # on base1 yoy/promo/log are already on -> test removal
                v = fh.BASELINE[k]
            t = dict(base, **{k: v})
            hyps.append(dict(hid=f"{bname}:{k}={v}", treatment=t, comparator=base))
    return hyps


def arm_runner(panel, cache, origins=None):
    return lambda g: fh.evaluate(panel, g, origins or fh.VAL_ORIGINS, cache)


GROUND_TRUTH_SEEDS = range(1000, 1040)


def ground_truth(hyps, seeds=GROUND_TRUTH_SEEDS, origins=None, T=fh.T_TOTAL):
    num = {h["hid"]: 0.0 for h in hyps}
    den = {h["hid"]: 0.0 for h in hyps}
    for s in seeds:
        panel, cache = fh.make_panel(s, T=T), {}
        run = arm_runner(panel, cache, origins)
        for h in hyps:
            num[h["hid"]] += run(h["treatment"])["abs_err"].sum()
            den[h["hid"]] += run(h["comparator"])["abs_err"].sum()
    return {k: 1 - num[k] / den[k] for k in num}


def run_labs(hyps, n_labs=10, seed0=5000, bootstrap="two_way", origins=None, T=fh.T_TOTAL):
    rows = []
    for lab in range(n_labs):
        rng = np.random.default_rng(lab)
        ledger = sk.FDRLedger(alpha=0.05)
        order = rng.permutation(len(hyps))
        for j, i in enumerate(order):
            h = hyps[i]
            pre = sk.Preregistration(
                hid=h["hid"],
                statement=f"{h['hid']} reduces WAPE by >= {SESOI:.0%}",
                estimand="relative WAPE reduction vs comparator, 6 rolling origins",
                treatment=h["treatment"],
                comparator=h["comparator"],
                primary_metric="WAPE(next-4-week sum)",
                unit="series",
                sesoi=SESOI,
                n_boot=1000,
                design=dict(origins=origins or fh.VAL_ORIGINS, T=T, bootstrap=bootstrap),
            ).lock()
            s1, s2 = seed0 + 1000 * lab + 2 * j, seed0 + 1000 * lab + 2 * j + 1
            p1, c1 = fh.make_panel(s1, T=T), {}
            run1 = arm_runner(p1, c1, origins)
            nominal = sk.run_test(pre, run1, rng)  # alpha 0.05
            alpha_f = ledger.next_alpha()
            fdr = sk.run_test(pre, run1, rng, ledger=ledger)  # alpha from the ledger
            single = "supported" if nominal["point"] >= SESOI else "refuted"
            repl = fdr["decision"]
            if fdr["decision"] == "supported":
                p2, c2 = fh.make_panel(s2, T=T), {}
                r2 = sk.run_test(pre, arm_runner(p2, c2, origins), rng)  # independent re-run, same locked prereg
                repl = "supported" if r2["decision"] == "supported" else "not_replicated"
            fut = np.nan
            if T == fh.T_TOTAL:  # own-future truth only defined for the standard panel length
                fut = 1 - (
                    fh.evaluate(p1, h["treatment"], fh.DEPLOY_ORIGINS, c1)["abs_err"].sum()
                    / fh.evaluate(p1, h["comparator"], fh.DEPLOY_ORIGINS, c1)["abs_err"].sum()
                )
            rows.append(
                dict(
                    lab=lab,
                    order=j,
                    hid=h["hid"],
                    bootstrap=bootstrap,
                    own_future_effect=fut,
                    point=nominal["point"],
                    lo95=nominal["lo"],
                    hi95=nominal["hi"],
                    alpha_fdr=alpha_f,
                    single_run_threshold=single,
                    prereg_ci=nominal["decision"],
                    prereg_ci_fdr=fdr["decision"],
                    prereg_fdr_replicated=repl,
                )
            )
    return pd.DataFrame(rows)


def controls(seed=9001):
    """Protocol admissibility: must detect a planted effect and must not support a placebo."""
    panel, cache = fh.make_panel(seed), {}
    run = arm_runner(panel, cache)
    rng = np.random.default_rng(0)
    mk = lambda hid, t, c: sk.Preregistration(
        hid=hid,
        statement=hid,
        estimand="rel WAPE reduction",
        treatment=t,
        comparator=c,
        primary_metric="WAPE",
        unit="series",
        sesoi=SESOI,
        n_boot=1000,
    ).lock()
    pos = sk.run_test(mk("positive: last-year window", dict(BASE0, yoy=True), BASE0), run, rng)["decision"]
    neg = sk.run_test(mk("negative: 5 noise features", dict(BASE0, noise=5), BASE0), run, rng)["decision"]
    return dict(positive=pos, negative=neg, admissible=(pos == "supported" and neg != "supported"))


def score(df, truth):
    df = df.copy()
    df["true_effect"] = df.hid.map(truth)
    real = df.true_effect >= SESOI
    out = []
    for proc in ("single_run_threshold", "prereg_ci", "prereg_ci_fdr", "prereg_fdr_replicated"):
        sup = df[proc] == "supported"
        neg_claim = df[proc].isin(["refuted", "no_effect", "harmful"])
        out.append(
            dict(
                procedure=proc,
                tests=len(df),
                supported=int(sup.sum()),
                false_discoveries=int((sup & ~real).sum()),
                false_discovery_rate=float((sup & ~real).sum() / max(sup.sum(), 1)),
                power=float((sup & real).sum() / max(real.sum(), 1)),
                false_negative_claims=int((neg_claim & real).sum()),
                inconclusive=int((df[proc] == "inconclusive").sum() + (df[proc] == "not_replicated").sum()),
            )
        )
    return pd.DataFrame(out), df


if __name__ == "__main__":
    hyps = bank()
    truth = ground_truth(hyps)
    # design A: 6 origins (standard panel); design B: 32 origins (5-year panel), powered design
    LONG_T, LONG_ORIGINS = 260, list(range(110, 235, 4))
    truth_long = ground_truth(hyps, origins=LONG_ORIGINS, T=LONG_T)
    runs = [
        ("6 origins", "units", run_labs(hyps, bootstrap="units"), truth),
        ("6 origins", "two_way", run_labs(hyps, bootstrap="two_way"), truth),
        ("32 origins", "two_way", run_labs(hyps, bootstrap="two_way", origins=LONG_ORIGINS, T=LONG_T), truth_long),
    ]
    scored = [(d, b, *score(df, tr)) for d, b, df, tr in runs]
    summary = pd.concat([s.assign(design=d, bootstrap=b) for d, b, s, _ in scored])
    detail = pd.concat([x.assign(design=d) for d, b, _, x in scored])
    truth = dict(six_origins=truth, thirty_two_origins=truth_long)
    ctrl = controls()
    os.makedirs(OUT, exist_ok=True)
    detail.to_csv(f"{OUT}/lab_calibration_tests.csv", index=False)
    summary.to_csv(f"{OUT}/lab_calibration_summary.csv", index=False)
    Path(f"{OUT}/lab_calibration_truth.json").write_text(json.dumps(dict(truth=truth, controls=ctrl), indent=1))
    print(summary.round(3).to_string(index=False))
    print(ctrl)
