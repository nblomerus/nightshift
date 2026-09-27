## Seats
| Seat | Kind | Owns |
|---|---|---|
| `pi@forecast-lab` | llm | the mission, the agenda, what to test next |
| `methodologist@forecast-lab` | llm | preregistrations: estimand, comparator, SESOI, design |
| `critic@forecast-lab` | llm | design review BEFORE data (registered-report stage 1) |
| `statistician@forecast-lab` | code | power, controls, lock, analysis, FDR ledger — deterministic, no LLM |
| `experimenter@forecast-lab` | llm | implementing the treatment arm and running it under the frozen judge |
| `replicator@forecast-lab` | llm | independent re-implementation from the prereg TEXT only, on fresh data |
| `writer@forecast-lab` | llm | the write-up; cannot change a decision |

## Slices
| Slice | Stage |
|---|---|
| C1-S1-last_year_window | written |
| C1-S2-log_target | parked |
| C2-S1-promo_feature | parked |
| C2-S2-log_target | parked |
| C3-S1-promo_feature | written |
| C3-S2-log_target | parked |

## Queue (every task has an owner)
| # | Kind | Slice | Creator → Owner | State |
|---|---|---|---|---|
| 1 | plan | None | human → pi | done |
| 2 | draft_prereg | C1-S1-last_year_window | pi → methodologist | done |
| 3 | draft_prereg | C1-S2-log_target | pi → methodologist | done |
| 4 | review_design | C1-S1-last_year_window | methodologist → critic | done |
| 5 | review_design | C1-S2-log_target | methodologist → critic | done |
| 6 | check_implementation | C1-S1-last_year_window | critic → experimenter | done |
| 7 | check_implementation | C1-S2-log_target | critic → experimenter | done |
| 8 | power_controls | C1-S1-last_year_window | experimenter → statistician | done |
| 9 | power_controls | C1-S2-log_target | experimenter → statistician | done |
| 10 | run_experiment | C1-S1-last_year_window | statistician → experimenter | done |
| 11 | draft_prereg | C1-S2-log_target | statistician → methodologist | done |
| 12 | analyse | C1-S1-last_year_window | experimenter → statistician | done |
| 13 | review_design | C1-S2-log_target | methodologist → critic | done |
| 14 | check_implementation | C1-S2-log_target | critic → experimenter | done |
| 15 | replicate | C1-S1-last_year_window | statistician → replicator | done |
| 16 | power_controls | C1-S2-log_target | experimenter → statistician | done |
| 17 | write | C1-S1-last_year_window | replicator → writer | done |
| 18 | plan | None | pi → pi | done |
| 19 | draft_prereg | C2-S1-promo_feature | pi → methodologist | done |
| 20 | draft_prereg | C2-S2-log_target | pi → methodologist | done |
| 21 | review_design | C2-S1-promo_feature | methodologist → critic | done |
| 22 | review_design | C2-S2-log_target | methodologist → critic | done |
| 23 | draft_prereg | C2-S1-promo_feature | critic → methodologist | done |
| 24 | check_implementation | C2-S2-log_target | critic → experimenter | done |
| 25 | draft_prereg | C2-S2-log_target | experimenter → methodologist | done |
| 26 | review_design | C2-S1-promo_feature | methodologist → critic | done |
| 27 | review_design | C2-S2-log_target | methodologist → critic | done |
| 28 | check_implementation | C2-S1-promo_feature | critic → experimenter | done |
| 29 | check_implementation | C2-S2-log_target | critic → experimenter | done |
| 30 | draft_prereg | C2-S1-promo_feature | experimenter → methodologist | done |
| 31 | draft_prereg | C2-S2-log_target | experimenter → methodologist | done |
| 32 | review_design | C2-S1-promo_feature | methodologist → critic | done |
| 33 | review_design | C2-S2-log_target | methodologist → critic | done |
| 34 | check_implementation | C2-S1-promo_feature | critic → experimenter | done |
| 35 | check_implementation | C2-S2-log_target | critic → experimenter | done |
| 36 | draft_prereg | C2-S1-promo_feature | experimenter → methodologist | done |
| 37 | draft_prereg | C2-S2-log_target | experimenter → methodologist | done |
| 38 | plan | None | pi → pi | done |
| 39 | draft_prereg | C3-S1-promo_feature | pi → methodologist | done |
| 40 | draft_prereg | C3-S2-log_target | pi → methodologist | done |
| 41 | review_design | C3-S1-promo_feature | methodologist → critic | done |
| 42 | review_design | C3-S2-log_target | methodologist → critic | done |
| 43 | check_implementation | C3-S1-promo_feature | critic → experimenter | done |
| 44 | draft_prereg | C3-S2-log_target | critic → methodologist | done |
| 45 | power_controls | C3-S1-promo_feature | experimenter → statistician | done |
| 46 | review_design | C3-S2-log_target | methodologist → critic | done |
| 47 | check_implementation | C3-S2-log_target | critic → experimenter | done |
| 48 | draft_prereg | C3-S1-promo_feature | statistician → methodologist | done |
| 49 | draft_prereg | C3-S2-log_target | experimenter → methodologist | done |
| 50 | review_design | C3-S1-promo_feature | methodologist → critic | done |
| 51 | review_design | C3-S2-log_target | methodologist → critic | done |
| 52 | check_implementation | C3-S1-promo_feature | critic → experimenter | done |
| 53 | check_implementation | C3-S2-log_target | critic → experimenter | done |
| 54 | power_controls | C3-S1-promo_feature | experimenter → statistician | done |
| 55 | draft_prereg | C3-S2-log_target | experimenter → methodologist | done |
| 56 | run_experiment | C3-S1-promo_feature | statistician → experimenter | done |
| 57 | analyse | C3-S1-promo_feature | experimenter → statistician | done |
| 58 | replicate | C3-S1-promo_feature | statistician → replicator | done |
| 59 | write | C3-S1-promo_feature | replicator → writer | done |

## Messages (send: questions and answers, no state change)

**#1 pi → pi** (None): (explorer) exploratory screen vs champion: last_year_window +13.33%, log_target +2.42%, promo_feature +1.64%, trend_feature +0.11%, strong_ridge -0.00%, short_window -0.25%, category_effects -1.17%, clip_outliers -10.65%

**#2 critic → pi** (C1-S2-log_target): Suggested new hypothesis: As already flagged in the rationale: preregister a separate hypothesis testing a bias-corrected log-transform (e.g., smearing estimator or exp(pred + sigma^2/2) correction) against the same raw-demand comparator, independent of whether logdem-v1 (naive, uncorrected) is killed.

**#3 statistician → methodologist** (C1-S2-log_target): Design B: probability of a decisive result 0.43 at the pilot effect +2.62% (pilot SE 1.27%, alpha 0.025); power at the 2.5% target 0.39. Leak canary clean. Controls: positive=supported, placebo=no_effect. Use the larger design C; I cannot lock this one.

**#4 critic → pi** (C1-S2-log_target): Suggested new hypothesis: Consider a separate preregistration for a bias-corrected log-transform variant (e.g., smearing estimator or exp(pred + sigma^2/2)-1 correction) as its own hid, since the current design explicitly tests only the naive uncorrected back-transform and a null/negative result here would not rule out the corrected variant.

**#5 writer → pi** (C1-S1-last_year_window): Adding last-year same-window demand feature cuts 4-week WAPE by 13.70% (Grade A, replicated) — grade A: replicated

**#6 statistician → pi** (C1-S2-log_target): Design C: probability of a decisive result 0.64 at the pilot effect +2.59% (pilot SE 1.00%, alpha 0.025); power at the 2.5% target 0.61. Leak canary clean. Controls: positive=supported, placebo=no_effect. No larger design exists: the lab cannot answer this with the available data at the fixed standards. Parked.

**#7 pi → pi** (None): (explorer) exploratory screen vs champion: promo_feature +1.76%, log_target +0.75%, short_window +0.07%, strong_ridge +0.04%, trend_feature +0.04%, category_effects -0.67%, clip_outliers -13.74%

**#8 critic → methodologist** (C2-S1-promo_feature): Comparator, estimand, and treatment/comparator naming are all fine and this is clearly scoped to the promo-count feature only (correctly separating it from the yoy proposal). One blocking fix needed: rewrite kills_if as a single non-contradictory rule. Given the stated intent, I read the operative test as: establish the effect only if the 97.5% CI lower bound for relative WAPE reduction is > 1.0% (SESOI); otherwise kill (including if the CI contains 0 or the point estimate is negative, both of which are already implied whenever the lower bound is <=1.0%, so those clauses are redundant but harmless). Please replace 'includes 0 or excludes values >=1.0% (i.e., lower bound <= SESOI of 1.0%)' with the single clause 'the CI lower bound is <= 1.0% (SESOI)' — drop the 'excludes values >=1.0%' phrasing entirely, since as literally written it describes a stronger and different condition than the lower-bound rule you intend. Resubmit with that line fixed and I'll approve.

**#9 experimenter → methodologist** (C2-S2-log_target): The prereg statement says the comparator is 'the identical model trained on raw demand'—meaning all features and hyperparameters match the treatment except log transform is off. The statement also explicitly lists what is NOT in the model: 'no yoy, promo, trend, category, clip, window, or series_mean features.' The frozen judge config adds yoy=true to the comparator, which contradicts the stated design. Decide: (1) add yoy to the treatment statement ('...with demand lags [1,2,3,4], 4/13-week rolling means, AND last-4-week prior-year demand...'), or (2) set comparator.yoy=false to match the statement. The treatment config already has yoy=true, so option 1 (revise statement) aligns with what the judge will run.

**#10 critic → pi** (C2-S2-log_target): Suggested new hypothesis: Separate preregistration: pooled ridge with demand lags 1-4, 4/13-week rolling means, plus last year's demand over the same 4-week window (yoy feature) as comparator vs. the same feature set with log(1+demand) target and naive inverse transform as treatment — to test whether the log-transform effect holds once yoy is included, and optionally whether a bias-corrected (e.g., variance-adjusted) inverse transform changes the effect size relative to the naive expm1 used here.

**#11 experimenter → methodologist** (C2-S1-promo_feature): Clarify: (1) Are inverse transforms and bias corrections applied uniformly to both arms post-hoc (not model parameters), or should they be added to the config? (2) Does the comparator include yoy=true as a standing feature, or is it promo=false against a baseline without yoy? The config shows yoy in both; the statement's comparator language suggests it should not be there.

**#12 experimenter → methodologist** (C2-S2-log_target): The statement's comparator explicitly excludes yoy as a control baseline ('no yoy, promo, trend, category, clip, window, or series_mean features'). The frozen judge config includes yoy=true in both arms. This confounds the log-transform treatment with the addition of last-year's demand. To test log transform in isolation, either: (1) update statement to accept yoy in both arms, or (2) update config comparator to yoy=false. The current config will measure the combined effect of log transform + yoy feature, not log transform alone.

**#13 critic → pi** (C2-S2-log_target): Suggested new hypothesis: A natural follow-up once this test resolves: compare the naive expm1 inverse-transform log model against a bias-corrected (e.g., smearing estimator or variance-based correction) log-transform model, to isolate how much of any WAPE change is attributable to retransformation bias vs. the log transform's effect on the ridge fit itself. This would need its own preregistration with the correction as the treatment change.

**#14 experimenter → methodologist** (C2-S1-promo_feature): The preregistration statement and machine config are locked on incompatible yoy settings. The statement's comparator arm requires yoy=false; the config supplies yoy=true for comparator. Resolve before freezing: either update the statement to yoy=true in both arms, or update the config to yoy=false in both arms. The treatment arm (promo=true vs promo=false difference) is otherwise congruent.

**#15 experimenter → methodologist** (C2-S2-log_target): The prereg statement explicitly lists '(no yoy, promo, trend, category, clip, window, or series_mean features)' as a constraint on the pooled ridge model. The frozen judge config includes yoy=true in both treatment and comparator arms. The statement claims the comparator is 'identical model trained on raw demand' with the same feature exclusions; the config contradicts this by adding yoy to both arms. Clarify whether yoy should be present (align statement to config) or absent (align config to statement) before locking.

**#16 methodologist → pi** (C2-S1-promo_feature): C2-S1-promo_feature parked after 3 prereg revisions: The preregistration statement and machine config are locked on incompatible yoy settings. The statement's comparator arm requires yoy=false; the config supplies yoy=true for comparator. Resolve before freezing: either update the statement to yoy=true in both arms, or update the config to yoy=false i

**#17 methodologist → pi** (C2-S2-log_target): C2-S2-log_target parked after 3 prereg revisions: The prereg statement explicitly lists '(no yoy, promo, trend, category, clip, window, or series_mean features)' as a constraint on the pooled ridge model. The frozen judge config includes yoy=true in both treatment and comparator arms. The statement claims the comparator is 'identical model trained 

**#18 pi → pi** (None): (explorer) exploratory screen vs champion: promo_feature +1.76%, log_target +0.75%, short_window +0.07%, strong_ridge +0.04%, trend_feature +0.04%, category_effects -0.67%, clip_outliers -13.74%

**#19 critic → methodologist** (C3-S2-log_target): Comparator, statement, and design choice (B over A/C) are all explicit and well-justified, and the primary kill criterion (bootstrap 97.5% CI vs. 1.0% SESOI, point estimate <=0) is concrete and matches the estimand. However, the supplementary kill clause about low-volume/intermittent series degradation is qualitative -- it names a mechanism (Jensen's-gap bias) but gives no threshold, no segment definition, and no test statistic, so it isn't falsifiable as stated. Please either (a) specify it operationally -- e.g., define the low-volume segment by a volume quantile fixed ex ante, and give a numeric degradation threshold with its own test -- or (b) remove it and let the primary CI/point-estimate criteria stand alone as the sole kill conditions. Once that's fixed I'll approve; everything else in the design is sound.

**#20 critic → pi** (C3-S2-log_target): Suggested new hypothesis: Segment-level bias audit for the log_target treatment: preregister an ex ante volume-quantile definition of 'low-volume/intermittent' SKUs and a numeric WAPE-degradation bound for that segment under the naive inverse transform, to be tested as a follow-up if PR-LOGTX passes.

**#21 statistician → methodologist** (C3-S1-promo_feature): Design B: probability of a decisive result 0.44 at the pilot effect +1.96% (pilot SE 0.93%, alpha 0.025); power at the 2.5% target 0.67. Leak canary clean. Controls: positive=supported, placebo=no_effect. Use the larger design C; I cannot lock this one.

**#22 experimenter → methodologist** (C3-S2-log_target): The preregistered comparator arm in the statement is pooled ridge without YoY features. The frozen judge config adds yoy=true to both treatment and comparator. This changes the comparator baseline and invalidates the stated contrast ('identical pooled ridge model on raw demand'). Clarify: does the comparator arm include YoY (last-4-week demand feature), or should the config set yoy=false for comparator to match the statement?

**#23 methodologist → experimenter** (C3-S2-log_target): Per the prereg rationale, YoY is false for both arms: "no YoY term in either arm per the machine config (yoy:false)" -- this explicitly locks yoy=false for both treatment and comparator. The statement's feature list also lists 'no YoY' among the shared feature set for the pooled ridge model applied to both log_target treatment and raw-demand comparator. A YoY feature addition is called out as 'a distinct hypothesis... that must be preregistered and tested separately from this log-link test; conflating them would make the statement untestable against the locked config.' Therefore: the frozen judge config's yoy=true on both arms deviates from PR-LOGTX as written. The comparator should not include YoY; the config should be corrected to yoy=false for both treatment and comparator to match this prereg. If yoy=true is run instead, that is a deviation from PR-LOGTX (a different, unpreregistered joint test of log-transform + YoY) and results under that config cannot be reported as a test of this statement.

**#24 critic → pi** (C3-S2-log_target): Suggested new hypothesis: Segment-level bias audit for the naive log-inverse-transform: preregister an ex ante volume-quantile split and a numeric bound on acceptable WAPE degradation in low-volume/sparse series attributable to Jensen's-gap bias, to be tested as a follow-up if PR-LOGTX's aggregate result is positive.

**#25 experimenter → methodologist** (C3-S2-log_target): The statement undersells the comparator — it says 'no YoY feature' but the frozen judge will include last year's 4-week demand in both arms. This is a material difference: the comparator is stronger than claimed, which weakens the treatment's relative advantage. Clarify whether the statement should say the comparator INCLUDES YoY (making the treatment's log transform the only differing element), or whether the config should have yoy=false for the comparator. Also confirm that 'naive inverse transform' (exp(ŷ) − 1 with no adjustment) is what the treatment will execute, and that 'pooled ridge' is defined somewhere external to this statement.

**#26 methodologist → pi** (C3-S2-log_target): C3-S2-log_target parked after 3 prereg revisions: The statement undersells the comparator — it says 'no YoY feature' but the frozen judge will include last year's 4-week demand in both arms. This is a material difference: the comparator is stronger than claimed, which weakens the treatment's relative advantage. Clarify whether the statement should 

**#27 writer → pi** (C3-S1-promo_feature): Adding known-in-advance promo-week counts cuts next-4-week WAPE by ~2%, but replication is inconclusive — grade B: supported, awaiting replication

## Workflow guard log
| Slice | Seat | From → To | Allowed | Note |
|---|---|---|---|---|
| C1-S1-last_year_window | pi | question → hypothesis | yes | Largest exploratory lift (+13.33%) by a wide margin; plausible mechanism (seasonal/anchor signal known in adva |
| C1-S2-log_target | pi | question → hypothesis | yes | Second-largest, plausible, low-risk change (distributional transform, not a new feature source) with a consist |
| C1-S1-last_year_window | experimenter | hypothesis → run | **REFUSED** | no edge hypothesis -> run |
| C1-S1-last_year_window | methodologist | hypothesis → prereg_draft | yes |  |
| C1-S1-last_year_window | methodologist | prereg_draft → design_review | yes | rev 0, design B |
| C1-S2-log_target | methodologist | hypothesis → prereg_draft | yes |  |
| C1-S2-log_target | methodologist | prereg_draft → design_review | yes | rev 0, design B |
| C1-S1-last_year_window | critic | design_review → approved_design | yes | Comparator is explicit and minimal (identical pooled-ridge config, yoy=true vs yoy=false, no incidental change |
| C1-S2-log_target | critic | design_review → approved_design | yes | Comparator is explicit (pooled ridge, lags 1-4 + 4/13-week rolling means, alpha=1.0, raw-demand control) and t |
| C1-S1-last_year_window | experimenter | approved_design → implementation_checked | yes |  |
| C1-S2-log_target | experimenter | approved_design → implementation_checked | yes |  |
| C1-S1-last_year_window | statistician | implementation_checked → controls_passed | yes | P(decisive) 1.00 at pilot effect +13.17%; leak canary clean |
| C1-S1-last_year_window | statistician | controls_passed → locked | yes | 088c26e5b67f |
| C1-S2-log_target | statistician | implementation_checked → controls_passed | **REFUSED** | unmet guards: ['p_decisive>=0.8'] |
| C1-S2-log_target | statistician | implementation_checked → prereg_draft | yes | underpowered |
| C1-S1-last_year_window | experimenter | locked → run | yes |  |
| C1-S2-log_target | methodologist | prereg_draft → design_review | yes | rev 1, design C |
| C1-S2-log_target | critic | design_review → approved_design | yes | Comparator is explicit and isolates exactly one variable (target transform), holding features/alpha/design fix |
| C1-S1-last_year_window | statistician | run → analysed | yes | supported (alpha 0.0250) |
| C1-S2-log_target | experimenter | approved_design → implementation_checked | yes |  |
| C1-S1-last_year_window | replicator | analysed → replicated | yes | supported; reimplementation matched |
| C1-S1-last_year_window | writer | replicated → written | yes |  |
| C1-S2-log_target | statistician | implementation_checked → controls_passed | **REFUSED** | unmet guards: ['p_decisive>=0.8'] |
| C1-S2-log_target | statistician | implementation_checked → parked | yes | underpowered at largest design |
| C2-S1-promo_feature | pi | question → hypothesis | yes | Top exploratory effect (+1.76%) with a plausible causal mechanism (known-in-advance promo weeks reduce demand  |
| C2-S2-log_target | pi | question → hypothesis | yes | Second-ranked exploratory effect, already has pilot data at two designs (SE 1.27%/1.00%, effect ~+2.6% both).  |
| C2-S1-promo_feature | methodologist | hypothesis → prereg_draft | yes |  |
| C2-S1-promo_feature | methodologist | prereg_draft → design_review | yes | rev 0, design B |
| C2-S2-log_target | methodologist | hypothesis → prereg_draft | yes |  |
| C2-S2-log_target | methodologist | prereg_draft → design_review | yes | rev 0, design B |
| C2-S1-promo_feature | critic | design_review → prereg_draft | yes | design objections: kills_if is internally contradictory: it says the result is killed if the CI 'includes 0 or |
| C2-S2-log_target | critic | design_review → approved_design | yes | Comparator (raw-demand ridge, alpha=1.0, lags 1-4 + 4/13-week rolling means, no yoy/promo/trend/category/clip/ |
| C2-S2-log_target | experimenter | approved_design → prereg_draft | yes | not implementable as written: Comparator specification conflict: statement claims 'identical model trained on  |
| C2-S1-promo_feature | methodologist | prereg_draft → design_review | yes | rev 1, design B |
| C2-S2-log_target | methodologist | prereg_draft → design_review | yes | rev 1, design B |
| C2-S1-promo_feature | critic | design_review → approved_design | yes | No blocking issues. Comparator is explicit and held identical apart from the promo-count feature (yoy/log/tren |
| C2-S2-log_target | critic | design_review → approved_design | yes | Comparator and treatment are symmetric and fully specified (same lags [1-4], same 4/13-week rolling means, sam |
| C2-S1-promo_feature | experimenter | approved_design → prereg_draft | yes | not implementable as written: Statement specifies 'naive inverse transform, no bias correction' as part of tre |
| C2-S2-log_target | experimenter | approved_design → prereg_draft | yes | not implementable as written: Comparator specification differs. Statement specifies comparator trained on raw  |
| C2-S1-promo_feature | methodologist | prereg_draft → design_review | yes | rev 2, design B |
| C2-S2-log_target | methodologist | prereg_draft → design_review | yes | rev 2, design B |
| C2-S1-promo_feature | critic | design_review → approved_design | yes | Comparator is explicit (promo=true vs promo=false, all else fixed), the estimand matches the design (Design B, |
| C2-S2-log_target | critic | design_review → approved_design | yes | No blocking issues. The statement is explicit and symmetric: both treatment (log target, naive expm1 inverse)  |
| C2-S1-promo_feature | experimenter | approved_design → prereg_draft | yes | not implementable as written: Statement specifies yoy=false in BOTH arms; config specifies yoy=true in BOTH ar |
| C2-S2-log_target | experimenter | approved_design → prereg_draft | yes | not implementable as written: Statement excludes yoy feature; config includes yoy=true in both treatment and c |
| C2-S1-promo_feature | methodologist | prereg_draft → parked | yes | revision cap reached |
| C2-S2-log_target | methodologist | prereg_draft → parked | yes | revision cap reached |
| C3-S1-promo_feature | pi | question → hypothesis | yes | Top screen result (+1.76%) and a natural extension of the current champion. Resolve the parked prereg by writi |
| C3-S2-log_target | pi | question → hypothesis | yes | Second-ranked screen result (+0.75%), with tighter pilot SE under design C (1.00% vs 1.27% for design B) — use |
| C3-S1-promo_feature | methodologist | hypothesis → prereg_draft | yes |  |
| C3-S1-promo_feature | methodologist | prereg_draft → design_review | yes | rev 0, design B |
| C3-S2-log_target | methodologist | hypothesis → prereg_draft | yes |  |
| C3-S2-log_target | methodologist | prereg_draft → design_review | yes | rev 0, design B |
| C3-S1-promo_feature | critic | design_review → approved_design | yes | Comparator is explicit and matched (identical ridge model, promo=false vs promo=true), the statement is falsif |
| C3-S2-log_target | critic | design_review → prereg_draft | yes | design objections: The third kills_if clause ('log-transform treatment shows systematic degradation on low-vol |
| C3-S1-promo_feature | experimenter | approved_design → implementation_checked | yes |  |
| C3-S2-log_target | methodologist | prereg_draft → design_review | yes | rev 1, design B |
| C3-S2-log_target | critic | design_review → approved_design | yes | Comparator is explicit and matches the estimand (identical pooled ridge, same lag/rolling-mean features, alpha |
| C3-S1-promo_feature | statistician | implementation_checked → controls_passed | **REFUSED** | unmet guards: ['p_decisive>=0.8'] |
| C3-S1-promo_feature | statistician | implementation_checked → prereg_draft | yes | underpowered |
| C3-S2-log_target | experimenter | approved_design → prereg_draft | yes | not implementable as written: Statement claims 'no YoY' (treatment); config sets yoy=true for both arms. State |
| C3-S1-promo_feature | methodologist | prereg_draft → design_review | yes | rev 1, design C |
| C3-S2-log_target | methodologist | prereg_draft → design_review | yes | rev 2, design B |
| C3-S1-promo_feature | critic | design_review → approved_design | yes | No blocking issues. Comparator (identical ridge model, promo=false) is explicit and correctly matched to the t |
| C3-S2-log_target | critic | design_review → approved_design | yes | Comparator and treatment are both explicit and share the identical raw feature set (lags 1-4, rolls 4/13, yoy= |
| C3-S1-promo_feature | experimenter | approved_design → implementation_checked | yes |  |
| C3-S2-log_target | experimenter | approved_design → prereg_draft | yes | not implementable as written: Statement claims comparator has no YoY feature; config shows comparator.yoy=true |
| C3-S2-log_target | methodologist | prereg_draft → parked | yes | revision cap reached |
| C3-S1-promo_feature | statistician | implementation_checked → controls_passed | yes | P(decisive) 0.92 at pilot effect +2.23%; leak canary clean |
| C3-S1-promo_feature | statistician | controls_passed → locked | yes | 84228ef24cc9 |
| C3-S1-promo_feature | experimenter | locked → run | yes |  |
| C3-S1-promo_feature | statistician | run → analysed | yes | supported (alpha 0.0250) |
| C3-S1-promo_feature | replicator | analysed → not_replicated | yes | inconclusive; reimplementation matched |
| C3-S1-promo_feature | writer | not_replicated → written | yes |  |