# Adding known-in-advance promo-week counts cuts next-4-week WAPE by ~2%, but replication is inconclusive

**Evidence grade:** B: supported, awaiting replication

For slice C3-S1-promo_feature, adding the known-in-advance count of promotion weeks falling in the 4-week forecast window to the pooled ridge model (alpha=1.0, no log transform, no trend/category terms, no series-mean centering) reduced relative WAPE of the next-4-week unit sum versus the identical model without that feature. Under Design C (58 rolling origins, weeks 110-338, 364-week history), the two-way bootstrap mean difference was 1.95%, 95% CI [0.14%, 3.64%] at alpha=0.025 — above the preregistered 1.0% SESOI, so the kernel decision is **supported**.

An independent reimplementation using the same treatment definition and design (seed 8800) returned a **decision of inconclusive**, so this result has not yet been confirmed by replication. Evidence grade is **B: supported, awaiting replication**.

For planners: treat this as a promising but not yet load-bearing signal. Do not roll the promo-count feature into production forecasting pipelines on the strength of this result alone; wait for a conclusive replication (or a second independent run) before committing. The effect size and CI lower bound both clear the SESOI, which is encouraging, but the point estimate's width and the pending replication mean the true effect could still be smaller than practically useful, or the current estimate could be noise-favorable. No other model changes (log transform, trend/category terms, alpha, centering, history length) were varied in this test.
