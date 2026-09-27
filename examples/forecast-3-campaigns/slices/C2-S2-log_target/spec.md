# Model log(1+demand) instead of raw demand

Champion: pooled ridge on demand lags 1-4 and 4/13-week rolling means + add last year's demand over the same 4-week window as a feature

Rationale (PI): Second-ranked exploratory effect, already has pilot data at two designs (SE 1.27%/1.00%, effect ~+2.6% both). Design C offers better SE and statistician-assessed power 0.61 / decisive-result probability 0.64 at the fixed standard — proceed to confirmatory on design C as the naive/uncorrected transform. Do NOT fold in the bias-corrected (smearing/exp(pred+sigma^2/2)) variant here — per critic's flags, that must be its own separate preregistered hid on fresh data regardless of this test's outcome, since a null result on the naive version doesn't inform the corrected one.
