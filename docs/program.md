# program.md — forecasting improvement campaign (human-owned)

Proposer agents read this before every run. Only the human edits it. Lessons from finished
campaigns are added under "Learned" through a reviewed pull request, never by an agent writing
to it directly.

## Objective
Lower rolling-origin WAPE of the next-4-week (≈30-day) shipped-units forecast per SKU×DC, as scored by
`forecast_harness.evaluate(..., VAL_ORIGINS)`. Ties go to the simpler candidate.

## What agents may change (the sandbox)
- `candidate.py`: the feature genome, model class, loss, hyper-parameters, target transform, and cleaning of training data.
- New feature code in `features/`, provided every feature is point-in-time. It must pass `leak_canary`.

## What agents must not change (the judge)
- `forecast_harness.py`: the metric, the splits, the gate, the canary and the ledger.
- Data extracts, origin lists, lockbox and deployment windows.
- `program.md`.
- Any file under `ledger/`.
The Refinery rejects any merge request whose diff touches these paths.

## Budgets
- Each experiment: ≤ 10 min wall clock on 1 GPU or 4 CPU cores. Early stop if it is 2× slower than the champion.
- Each campaign: ≤ N candidates (set per campaign). The lockbox is read once, at campaign end.
- Token budget per proposer per round: set in the town config.

## Promotion rule (enforced by the Refinery, restated here for agents)
A candidate replaces the champion only if all of the following hold:
1. Relative WAPE gain ≥ 0.2%.
2. Series-bootstrap z-test p < 0.01.
3. It beats the champion on ≥ 4 of 6 validation origins.
4. No category regresses by more than 5%.
5. The leak canary is clean.
The campaign's final champion ships only if it also beats the incumbent on the lockbox. After that it
runs in shadow for ≥ 4 weeks before it serves.

## Research directions (priority order; edit between campaigns)
1. Stockout-aware targets: censored demand, and excluding or imputing out-of-stock weeks.
2. Known-future covariates: promotions, price changes, events (Black Friday) and their interactions.
3. Hierarchy: pooling across category/DC, and reconciliation of SKU forecasts to category totals.
4. Loss/objective: Tweedie vs L2 vs quantile, and bias correction after log transforms.
5. Model class: global GBM vs zero-shot time-series foundation models as features or challengers.

## Things that have been tried (the agent must read and not repeat)
- (populated from the ledger by the Witness at the end of each campaign)

## Learned
- (human-curated; e.g. "segment guard at 2% blocked seasonal features that help most SKUs" — see demo)
