# Adding last-year same-window demand feature cuts 4-week WAPE by 13.70% (Grade A, replicated)

**Evidence grade:** A: replicated

Adding last year's demand over the same 4-week window as a feature to the pooled ridge model (lags 1-4, 4/13-week rolling means, alpha=1.0, no log/trend/category/promo/clip/window/series_mean adjustments, naive inverse transform) reduces relative WAPE by an estimated 13.70% versus the identical model without this feature, with a two-way bootstrap CI of [9.60%, 17.68%] at alpha=0.025 under Design B (32 rolling origins, weeks 110-234, 260-week history). This comfortably clears the preregistered SESOI of 1.0%, and the effect was independently replicated (seed 8600, same treatment definition, same decision: supported), earning an evidence grade of A.

For planners, this means incorporating a simple year-over-year seasonal signal — last year's demand summed over the matching 4-week horizon — meaningfully improves near-term forecast accuracy for this pooled SKU setup, beyond what recent lags and rolling means alone capture. The magnitude of improvement (~14%) is substantial relative to the 1% threshold set for practical significance.

Limits: this result is specific to the exact model configuration tested — a linear ridge model without log transform, trend, category effects, promotions, clipping, or windowing, and without series-level mean centering. It does not establish that this feature helps under other model families, transforms, or feature sets, nor does it address performance outside the Design B origin window (weeks 110-234) or history length (260 weeks). Interactions with promo or category features, if added later, are untested.
