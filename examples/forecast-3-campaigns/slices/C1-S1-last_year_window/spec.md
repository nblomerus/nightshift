# Add last year's demand over the same 4-week window as a feature

Champion: pooled ridge on demand lags 1-4 and 4/13-week rolling means

Rationale (PI): Largest exploratory lift (+13.33%) by a wide margin; plausible mechanism (seasonal/anchor signal known in advance for a 4-week-ahead forecast) rather than leakage, since it's prior-year actuals not future data. Worth a preregistered confirmatory test on fresh data/splits to guard against winner's-curse inflation of the screen estimate.
