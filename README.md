# Vice Forecast — GTA VI Trophy Rarity Forecast

[![GTA 6 Trophy Rarity Forecast](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01)
[![Rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/bloomsX/gta6-trophy-rarity-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![Reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/bloomsX/gta6-trophy-rarity-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecasts, for each of **Grand Theft Auto VI**'s 55 PS5 trophies, five quantiles
(5%, 25%, 50%, 75%, 95%) of its Exophase earn rate at **2026-11-26T00:00:00Z** —
a week after launch — from the house's recording of Exophase's trophy page,
built for the [make.fun GTA 6 Trophy Rarity Forecast bounty](https://make.fun/bounty/gta6-trophy-rarity-forecast-01).

## Model

Trophy earn rates follow S-curves, and Exophase's page refreshes on its own
schedule, so the model treats the two regimes differently:

- **Flat history (page hasn't refreshed):** a refresh is due, not zero growth.
  The shown player count is stale, so the target player count is extrapolated
  as `P * ((1 + h_target) / (1 + h_first))^1.06` — the exponent fits the
  launch-night refresh (638 → 3,868 players in ~4.5 h). New players earn
  ~1 trophy each, concentrated on the earliest trophies, so the median rate
  falls by dilution; the spread is wide (0.5 logit) because the refresh's
  size and the new players' profile are both uncertain.
- **Moving history:** per-trophy least squares of `logit(rate)` on
  `ln(1 + hours since launch)` over an adaptive recent window (12 h, widened
  until at least 6 distinct reads, so a stale tail can't flatten the fit),
  with the slope shrunk toward the mean slope of the trophy's kind
  (chapter / mission / activity / grind / misc / platinum, from the
  description and tier). The extrapolated growth is damped 35% — S-curves
  saturate, and a straight line overshoots — and the median blends the fitted
  line with a last-read-anchored value 50/50. Spread is
  `sqrt(fit residual² + random-walk²) × 0.6`: the house baselines' full
  random-walk spread is wider than the median error warrants.
- A trophy at ≥ 99.9% (everyone tracked has it) is pinned near 100%.

Quantiles are `inv_logit(logit(median) + z_τ · σ)`, rounded to 4 decimals
half-up, clamped to [0.01, 99.99], non-decreasing.

## Validation

Practice cases p00/p01, scored against a reconstruction of the documented
04:30Z refresh (players 638 → 3,868, trophies earned 943 → 4,276):

| case | this model | flat baseline | trend baseline |
|------|-----------|---------------|----------------|
| p00 vs proportional reconstruction | **0.104** | ~1.51 | ~1.51 |
| p01 vs proportional reconstruction | **0.116** | ~1.51 | ~1.51 |
| p00/p01 vs early-story reconstruction | **0.19** | ~1.51 | ~1.51 |
| p00/p01 vs uniform reconstruction | **0.11–0.12** | ~1.51 | ~1.51 |

On five simulated final-like cases (358 reads, cut 59.5 h in, target 168 h):
**0.148–0.155** vs flat 0.48–0.51 and trend 0.32–0.35 — about 2× better than
the house trend baseline, consistent across seeds. A 12-hour stale tail
before the deadline degrades it only to 0.19.

## Notes and limitations

- The moving-regime branch is tuned on the builder's own simulator only: the
  practice cases are flat, so they validate the flat branch, not the moving
  one. If real trophy curves saturate much less (or much more) than the
  simulator assumes, the 35% growth damp and the 0.6 spread scale could be
  off. The design is directionally principled (saturation damp, a spread
  tighter than the baselines'), and the simulated edge over the trend
  baseline is large, but the exact final score is unknowable until the real
  case runs.
- One bug was caught and fixed during validation: a hand-computed launch
  timestamp constant was 21 hours off, silently collapsing dilution to 1.0
  (practice loss 1.14 instead of 0.11). It is now set to 1795046400 and
  verified against `datetime`.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, no network, deterministic (two runs on
the same case produce byte-identical output). Runtime ≈ 0.03 s per case,
far under the 8 s limit.

`main.py` reads every `*.in` case in the input directory and writes the
matching `*.out` forecast (`{"trophies": [{"id": 1, "q": [q05, q25, q50, q75, q95]}, …]}`).
