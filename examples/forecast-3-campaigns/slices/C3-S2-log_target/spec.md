# Model log(1+demand) instead of raw demand

Champion: pooled ridge on demand lags 1-4 and 4/13-week rolling means + add last year's demand over the same 4-week window as a feature

Rationale (PI): Second-ranked screen result (+0.75%), with tighter pilot SE under design C (1.00% vs 1.27% for design B) — use design C. Fix the parked prereg by rewriting the 'no yoy/promo/...' constraint, which describes an obsolete champion; both arms should include yoy=true to match the current champion, and this test should be scoped strictly to the naive expm1 inverse-transform variant (bias-corrected/smearing log_target is a separate future hid, per campaign 1 lesson).
