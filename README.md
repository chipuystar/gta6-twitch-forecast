# gta6-twitch-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/chipuystar/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/chipuystar/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

An entry for make.fun's **gta6-twitch-ccu-forecast-01**: forecast Grand Theft
Auto VI's launch-day Twitch viewers, hour by hour (hours 2–24 of release day,
UTC), as five quantiles (5/25/50/75/95) per hour. Scored by mean pinball loss
on the log scale; lower is better.

## The model

`main.py` (Python 3.13, standard library only) builds an empirical launch-day
shape model from the case's own comparables — ~38 past launches with hourly
Twitch data:

1. **Template selection.** A comparable is used only when it is a clean,
   same-family launch: its unlock note marks it "Tier: comparable", and its
   launch-day peak is 1.5×–20× its hour-1 print. The upper bound removes
   launches whose hour 1 came before the game unlocked (their ratios to hour
   1 are inflated up to 2000×); the lower bound removes launches whose hour
   1 was already the peak. The tier filter matters on its own: several
   early-access-contaminated launches pass the ratio filter but carry shapes
   distorted by pre-release play.
2. **Hour-1-conditioned shape.** Across past launches, the hour-1 print is a
   strong predictor of how much the day still has to rise (log hour-1 vs log
   peak ratio, r = −0.75): a small hour-1 print means the launch's main
   markets have not unlocked yet, so the day rises steeply; a large hour-1
   print means the launch is already broad, so the day is flatter. The
   template is therefore split at 65,000 hour-1 viewers, and the half
   matching the target's hour-1 print is used.
3. **Quantiles.** For each hour 2–24, the 5/25/50/75/95 quantiles of
   log(viewers_h / viewers_1) across the selected templates, smoothed with a
   3-hour moving average, then scaled by the target's hour-1 print.
4. **Minimum spread.** Each hour's 90% interval is widened, symmetrically
   around the median, until it spans at least 1.0 log units (q95/q05 ≥
   2.72×), so a small template that agrees too closely cannot produce an
   overconfident interval.

Fallbacks keep the output valid even if the case is degraded: if the matching
half has fewer than 3 templates the full template is used; if the template is
empty, or anything unexpected happens, the program falls back to the
persistence baseline. The program never crashes on a case.

## Validation

Pinball loss on the log scale (lower is better). Practice answers come from
SullyGnome's hourly data for the four practice launches (their hour-1 prints
match the case files exactly).

| Practice case | Model | House baseline |
| --- | --- | --- |
| Marvel's Wolverine | 0.238 | 0.744 |
| Red Dead Redemption 2 | 0.129 | 0.287 |
| God of War Ragnarök | 0.176 | 0.215 |
| Marvel's Spider-Man 2 | 0.203 | 0.303 |
| **Mean** | **0.186** | **0.387** |

Leave-one-out over the 19-game template pool: **0.283** vs the baseline's
0.435. Runtime is ~0.04 s per case (limit: 8 s); output is byte-identical
across runs.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=0cyw4zjw&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
