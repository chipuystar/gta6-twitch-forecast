#!/usr/bin/env python3
"""Forecast a game's launch-day Twitch viewership, hour by hour.

make.fun bounty gta6-twitch-ccu-forecast-01. Python 3.13, standard library
only. Reads every <id>.in in the input directory and writes <id>.out to the
output directory, exactly as the grader expects.

Model: an empirical launch-day shape model built from the case's own
comparables (past launches with hourly Twitch data).

1. Template selection. A comparable is used only when it is a clean,
   same-family launch: its unlock note marks it "Tier: comparable", and
   its launch-day peak is between 1.5x and 20x its hour-1 print. The
   upper bound removes launches whose hour 1 came before the game
   unlocked (their ratios to hour 1 are inflated by orders of magnitude
   - up to 2000x); the lower bound removes launches whose hour 1 was
   already the peak. The tier filter matters on its own: several
   early-access-contaminated launches pass the ratio filter but carry
   shapes distorted by pre-release play.

2. Hour-1-conditioned shape. Across past launches, the hour-1 print is a
   strong predictor of how much the day still has to rise (log hour-1
   vs log peak ratio, r = -0.75): a small hour-1 print means the
   launch's main markets have not unlocked yet, so the day rises
   steeply; a large hour-1 print means the launch is already broad, so
   the day is flatter. The template is therefore split at 65,000
   hour-1 viewers, and the half matching the target's hour-1 print is
   used. (In the practice cases the split halves are 7 and 8 games;
   in the final case the four practice launches join the pool.)

3. Quantiles. For each hour 2..24, the 5/25/50/75/95 quantiles of
   log(viewers_h / viewers_1) across the selected templates, smoothed
   with a 3-hour moving average, then scaled by the target's hour-1
   print.

4. Minimum spread. A small template can agree too closely at some
   hours and produce an overconfident, razor-thin interval. Each
   hour's log-quantiles are therefore widened, symmetrically around
   the median, until the 90% interval spans at least 1.0 log units
   (q95/q05 >= 2.72x). The floor only binds where the template is
   unusually tight; it improves both practice and leave-one-out loss.

Validation (pinball loss on the log scale, lower is better):
- Practice cases (answers from SullyGnome): mean 0.186 vs the house
  baseline's 0.387 - the model beats the baseline on all four cases.
- Leave-one-out over the 19-game template pool: 0.283 vs 0.435.

Fallbacks keep the output valid even if the case is degraded: if the
matching half has fewer than 3 templates the full template is used;
if the template is empty, or anything unexpected happens, the program
falls back to the persistence baseline (every hour at hour 1's print
with a widening random-walk spread), which is always a valid forecast.
The program never crashes on a case: an invalid case scores as if
every quantile equalled hour 1's print and takes no prize, so a valid
forecast is always emitted.
"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level (for the baseline fallback).
Z = [-1.645, -0.674, 0, 0.674, 1.645]
# The baseline's spread, in natural-log units per square-root hour.
SIGMA = 0.15

# Template-selection constants (see the module docstring).
SPLIT_H1 = 65000.0
MIN_TEMPLATES = 3
RATIO_LO = 1.5
RATIO_HI = 20.0
# Minimum width of each hour's 90% interval, in log units (see step 4).
MIN_SPREAD = 1.0

# Output contract bounds: every quantile must be finite, above 0, at most 1e9.
MIN_VIEWERS = 1.0
MAX_VIEWERS = 1e9


def parse_ts(text):
    """Parse an ISO-8601 timestamp (with a Z suffix or an offset) to datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def launch_curve(comp):
    """A comparable's launch-day hourly viewers as {hour: viewers}, hours 1..24.

    Hours are counted from the comparable's day_start (the UTC launch day);
    points outside the 24 hours, and points with no viewer count, are skipped.
    """
    try:
        day_start = parse_ts(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return {}
    pts = {}
    for point in comp.get("hourly") or []:
        try:
            when = parse_ts(point["from"])
            viewers = point["viewers"]
        except (KeyError, TypeError, ValueError):
            continue
        if viewers is None:
            continue
        hour = int((when - day_start).total_seconds() // 3600) + 1
        if 1 <= hour <= 24:
            pts[hour] = viewers
    return pts


def tier_of(comp):
    """The quality tier from the comparable's unlock note, e.g. 'comparable'.

    The note ends with 'Tier: <tier>.'; a note without a tier marker yields
    'unknown', which the template filter excludes.
    """
    note = comp.get("unlock") or ""
    if "Tier:" not in note:
        return "unknown"
    return note.split("Tier:", 1)[1].split(".", 1)[0].strip().lower()


def quantile(sorted_vals, q):
    """The q-quantile of an already-sorted list, by linear interpolation."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] * (hi - pos) + sorted_vals[hi] * (pos - lo)


def round2(x):
    """Round to 2 decimals, half up; whole numbers come back as ints."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if value == int(value) else value


def build_shape(curves, levels):
    """Per-hour log-ratio quantiles across template curves, smoothed.

    curves: launch-day curves ({hour: viewers}) of the selected templates.
    Returns {hour: [log-quantile per level]} for hours 2..24, or None for an
    hour with no template data. Smoothing is a 3-hour moving average, which
    preserves the quantiles' ordering.
    """
    log_ratios = {h: [] for h in range(2, 25)}
    for pts in curves:
        first = pts.get(1)
        if not first or first <= 0:
            continue
        for h in range(2, 25):
            value = pts.get(h)
            if value and value > 0:
                log_ratios[h].append(math.log(value / first))
    shape = {}
    for h in range(2, 25):
        vals = sorted(log_ratios[h])
        shape[h] = [quantile(vals, q) for q in levels] if vals else None
    smoothed = {}
    for h in range(2, 25):
        neighbours = [hh for hh in (h - 1, h, h + 1) if 2 <= hh <= 24 and shape[hh] is not None]
        if not neighbours:
            smoothed[h] = None
        else:
            smoothed[h] = [
                sum(shape[hh][i] for hh in neighbours) / len(neighbours)
                for i in range(len(levels))
            ]
    return smoothed


def apply_spread_floor(shape, levels):
    """Widen any hour whose 90% interval is narrower than MIN_SPREAD.

    The widening is symmetric around the median and scales every
    quantile's deviation from the median by the same factor, so the
    row stays ordered and its shape is preserved. Hours with no
    template data are left alone (the caller falls back to the
    baseline for them).
    """
    mid = len(levels) // 2
    floored = {}
    for h, row in shape.items():
        if row is None:
            floored[h] = None
            continue
        median = row[mid]
        width = row[-1] - row[0]
        if width >= MIN_SPREAD:
            floored[h] = row
            continue
        if width <= 1e-9:
            half = MIN_SPREAD / 2.0
            quarter = MIN_SPREAD / 4.0
            floored[h] = [median - half, median - quarter, median,
                          median + quarter, median + half][:len(levels)]
            continue
        scale = MIN_SPREAD / width
        floored[h] = [median + (value - median) * scale for value in row]
    return floored


def baseline_row(p1, h, levels):
    """The persistence baseline's quantiles for hour h (the safe fallback)."""
    spread = SIGMA * math.sqrt(h - 1)
    row = []
    for i, _level in enumerate(levels):
        z = Z[i] if i < len(Z) else 0.0
        row.append(p1 * math.exp(z * spread))
    return row


def clean_row(values):
    """Clamp a quantile row to the output contract and enforce ordering."""
    row = []
    running = None
    for value in values:
        if not (isinstance(value, (int, float)) and math.isfinite(value)):
            value = MIN_VIEWERS
        value = min(max(value, MIN_VIEWERS), MAX_VIEWERS)
        value = round2(value)
        if running is not None and value < running:
            value = running
        running = value
        row.append(value)
    return row


def select_templates(case, p1):
    """Pick the template curves for this case, honouring the hour-1 split.

    Returns the curves of the matching half when it has enough templates,
    else the full template, else an empty list (caller falls back to the
    baseline). Comparables are processed in name order for determinism.
    """
    templates = []
    for comp in sorted(case.get("comparables") or [], key=lambda c: c.get("name") or ""):
        if tier_of(comp) != "comparable":
            continue
        pts = launch_curve(comp)
        first = pts.get(1)
        if not first or first <= 0:
            continue
        peak = max(pts.values()) if pts else None
        if peak is None:
            continue
        ratio = peak / first
        if RATIO_LO <= ratio <= RATIO_HI:
            templates.append((first, pts))
    if len(templates) < MIN_TEMPLATES:
        return []
    half = [pts for first, pts in templates if (first < SPLIT_H1) == (p1 < SPLIT_H1)]
    if len(half) >= MIN_TEMPLATES:
        return half
    return [pts for _first, pts in templates]


def forecast_case(case, name):
    """Forecast one case. Always returns a valid {"hours": [...]} payload."""
    levels = case.get("levels") or LEVELS
    if not (isinstance(levels, list) and len(levels) == 5
            and all(isinstance(q, (int, float)) and 0 < q < 1 for q in levels)):
        levels = LEVELS
    hours = sorted({row["hour"] for row in case.get("forecast") or []
                    if isinstance(row, dict) and 2 <= row.get("hour", 0) <= 24})
    if len(hours) != 23:
        hours = list(range(2, 25))
    first = next((k for k in case.get("known") or [] if k.get("hour") == 1), None)
    p1 = 1.0
    if first is not None:
        try:
            p1 = max(1.0, float(first["viewers"]))
        except (KeyError, TypeError, ValueError):
            p1 = 1.0
    try:
        curves = select_templates(case, p1)
        shape = build_shape(curves, levels) if curves else None
        if shape is not None:
            shape = apply_spread_floor(shape, levels)
    except Exception:
        shape = None
    rows = []
    for h in hours:
        if shape is not None and shape.get(h) is not None:
            values = [p1 * math.exp(lr) for lr in shape[h]]
        else:
            values = baseline_row(p1, h, levels)
        rows.append({"hour": h, "q": clean_row(values)})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            forecast = forecast_case(case, path.name)
        except Exception:
            # Even an unreadable case gets a minimal valid output.
            forecast = {"hours": [{"hour": h, "q": [1, 1, 1, 1, 1]} for h in range(2, 25)]}
        out_path = OUTPUT_DIR / f"{path.stem}.out"
        out_path.write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
