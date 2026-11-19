# Agent build notes — gta6-trophy-rarity-forecast-01

## What it is

`main.py` (Python 3.13, stdlib only, offline, deterministic) forecasts five
quantiles (5/25/50/75/95%) of each of the 55 GTA VI PS5 trophies' Exophase
earn rate at the case target, scored by pinball loss on the logit scale.

## Model (see the docstring in main.py for the full write-up)

- Flat history (all reads identical) → refresh-anticipation mode: player
  dilution `((1+h_target)/(1+h_first))^1.06`, new players earn ~1 trophy
  each (p_new_base 0.0013, weighted toward early trophies), sigma 0.5.
- Moving history → per-trophy OLS of logit(rate) on ln(1+hours) over an
  adaptive 12 h window (widens until >= 6 distinct reads), slope shrunk
  toward the kind mean (k=20), extrapolated growth damped 35%, median =
  50/50 blend of fitted line and last-read anchor, sigma =
  max(sqrt(sd^2 + (0.5*sqrt(days))^2), 0.3) * 0.6.
- Trophy at >= 99.9% pinned near 100%.

## Validation (all in /tmp/trophy-val, kept out of the repo)

- Practice p00/p01 vs a reconstruction of the documented 04:30Z refresh
  (players 638 -> 3,868, trophies 943 -> 4,276): 0.10-0.19 across three
  reconstructions (proportional / early-story / uniform) vs baselines ~1.51.
- Simulated final-like cases (5 seeds, 358 reads, cut 59.5 h, target 168 h):
  0.148-0.155 vs flat 0.48-0.51, trend 0.32-0.35.
- Runtime ~0.03 s/case; two runs byte-identical.

## Tuning lessons (don't re-break these)

- The 48 h window loses to 24 h, which loses to 12 h: the flat launch-night
  prefix drags the slope down. Fitting ALL history scores 0.49-0.55 on the
  final sims, worse than flat.
- A straight-line extrapolation overshoots systematically (+0.43 logit
  median bias on the sims) because S-curves saturate; the 35% growth damp
  is the single biggest win after the window fix.
- The house baselines' full random-walk spread is too wide: sigma scale
  0.6 beats 1.0 by ~0.07 on the sims.
- Practice is flat, so the flat branch is tuned there; the non-flat branch
  is tuned on the simulator only — the practice numbers do NOT validate it.
- `LAUNCH_TS` is 1795046400 (2026-11-19T00:00:00Z). It was once wrong by
  +21 h and silently killed the dilution (dilution collapsed to 1.0);
  verify any timestamp constant against `datetime` before trusting it.
