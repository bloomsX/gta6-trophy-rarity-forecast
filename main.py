"""GTA VI trophy rarity forecast (gta6-trophy-rarity-forecast-01).

Forecasts, for each of the game's 55 PS5 trophies, five quantiles (5/25/50/75/95%)
of its Exophase earn rate at the case's target, scored by pinball loss on the
logit scale. Python 3.13, standard library only, deterministic, offline.

Model (per trophy, on the logit scale):
  * The case history is a sequence of reads of Exophase's trophy page. Reads
    repeat unchanged values while the page has not refreshed, so a flat stretch
    is NOT zero growth -- it is a stale page.
  * FLAT history (every read identical): a refresh is due. The page's shown
    player count is stale by the hours since the first read, so the target
    player count is extrapolated as P * ((1+h_target)/(1+h_first))^1.06
    (1.06 fits the launch-night refresh: 638 -> 3,868 players in ~4.5h).
    Earners are the old earners plus the new players' earnings (new players
    earn ~1 trophy each, concentrated on the earliest trophies), so the
    median rate falls by dilution. Spread is wide (0.5 logit) because the
    refresh's size and the new players' profile are both uncertain.
  * MOVING history: per-trophy least squares of logit(rate) on ln(1 + hours
    since launch) over an adaptive recent window (12h, widened until at least
    6 distinct reads), with the slope shrunk toward the mean slope of the
    trophy's kind (chapter / mission / activity / grind / misc / platinum,
    from the description and tier). The extrapolated growth is damped 35%
    (S-curves saturate; a straight line overshoots), and the median blends
    the fitted line with a last-read-anchored value 50/50. Spread is
    sqrt(fit residual^2 + random-walk^2), scaled 0.6 -- the house baselines'
    full random-walk spread is wider than the median error warrants.
  * A trophy at >= 99.9% (everyone tracked has it) is pinned near 100%.

Quantiles: q_tau = inv_logit(logit(median) + z_tau * sigma), rounded to 4
decimals half-up, clamped to [0.01, 99.99], non-decreasing.

Usage (outside the grader): mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
"""

import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817, 1.6448536269514722]

LAUNCH_TS = 1795046400  # 2026-11-19T00:00:00Z, epoch seconds

# ---- flat-regime (refresh-dilution) parameters, tuned on the practice cases
# against a reconstruction of the 04:30Z refresh (players 638 -> 3,868,
# trophies earned 943 -> 4,276, every rate but the 100% one falling).
DILUTION_GAMMA = 1.06
DILUTION_CAP = 50.0
P_NEW_BASE = 0.0013
SIGMA_FLAT = 0.5
# ---- moving-regime parameters, tuned on simulated final-like cases
WINDOW_HOURS = 12.0
MIN_DISTINCT = 6
WINDOW_MAX_HOURS = 72.0
SHRINK_K = 20.0
DAMP = 0.35
SIGMA_RW = 0.5
SIGMA_SCALE = 0.6
SIGMA_FLOOR = 0.3
SIGMA_NOFIT = 1.0
KIND_CEIL = {
    "chapter": 85.0,
    "mission": 70.0,
    "activity": 40.0,
    "grind": 25.0,
    "misc": 50.0,
    "platinum": 5.0,
}


def clamp(x: float) -> float:
    return min(99.99, max(0.01, x))


def logit(pct: float) -> float:
    p = clamp(pct) / 100.0
    return math.log(p / (1 - p))


def inv_logit(l: float) -> float:
    if l >= 0:
        return 100.0 / (1.0 + math.exp(-l))
    e = math.exp(l)
    return 100.0 * e / (1.0 + e)


def round4(x: float) -> float | int:
    """x rounded to 4 decimals, half up (as the starter rounds it)."""
    scaled = x * 10000
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000
    return int(value) if value.is_integer() else value


def parse_time(s: str) -> float:
    """ISO-8601 Zulu timestamp -> epoch seconds (no datetime import cost)."""
    # "2026-11-19T03:00:00Z" or "...T03:00:00.309Z"
    date, time = s.split("T")
    y, mo, d = (int(v) for v in date.split("-"))
    time = time.rstrip("Z")
    if "." in time:
        time, _frac = time.split(".")
    hh, mm, ss = (int(v) for v in time.split(":"))
    # days since epoch via Howard Hinnant's algorithm
    y -= 1 if mo <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    mp = (mo + 9) % 12
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    days = era * 146097 + doe - 719468
    return days * 86400 + hh * 3600 + mm * 60 + ss


def kind_of(trophy: dict) -> str:
    d = trophy["description"].lower()
    if trophy["tier"] == "platinum":
        return "platinum"
    if "chapter" in d:
        return "chapter"
    if d.startswith("complete") and (
        "mission" in d or "run" in d or "heist" in d or "play" in d
        or "takedown" in d or "operation" in d or "headliners" in d
        or "fishing" in d
    ):
        return "mission"
    if any(k in d for k in (
        "win ", "beat ", "gold medal", "arcade", "try each", "lose a",
        "take down 5", "make an unscheduled", "smash your way",
        "bowl 'em", "follow-through",
    )):
        return "activity"
    if any(k in d for k in (
        "complete 250", "complete 50", "complete 3 collectible",
        "complete 8 mission strands", "discover 100", "waink",
        "explore all", "spend $", "purchase all", "register 10",
        "earn $", "rob 5", "rob an armored", "rob a jewelry",
        "rob 3 shops",
    )):
        return "grind"
    return "misc"


def fit_line(xs, ys):
    """OLS y ~ a + b x. Returns (a, b, resid_std, n) or None."""
    n = len(xs)
    if n == 0:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        return (my, 0.0, 0.0, n)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    sd = 0.0
    if n > 2:
        var = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys)) / (n - 2)
        sd = math.sqrt(max(var, 0.0))
    return (a, b, sd, n)


def forecast_case(case: dict, name: str) -> dict:
    if case["levels"] != LEVELS:
        raise ValueError(f"{name} asks for levels {case['levels']}, not {LEVELS}")
    if not case["history"]:
        raise ValueError(f"{name} has no history")
    trophies = case["trophies"]
    hist = case["history"]
    horizon_days = case["horizon_minutes"] / 1440.0

    read_ts = [parse_time(r["at"]) for r in hist]
    hours = [(ts - LAUNCH_TS) / 3600.0 for ts in read_ts]
    h_target = (parse_time(case["target"]) - LAUNCH_TS) / 3600.0
    x_target = math.log1p(max(h_target, 0.0))

    # Flat history: every read identical -> the page has not refreshed.
    signatures = set()
    for r in hist:
        signatures.add(tuple(r["rates"]))
    flat = len(signatures) <= 1

    last = hist[-1]
    rows = []

    if flat:
        h_first = max(hours[0], 0.0)
        dil = ((1.0 + max(h_target, 0.0)) / (1.0 + h_first)) ** DILUTION_GAMMA
        dil = min(DILUTION_CAP, max(1.0, dil))
        for i, trophy in enumerate(trophies):
            rate_last = last["rates"][i]
            if rate_last is None:
                rate_last = 0.01
            if rate_last >= 99.9:
                rows.append({"id": trophy["id"], "q": [99.9, 99.95, 99.99, 99.99, 99.99]})
                continue
            p_new = P_NEW_BASE * min(1.0, rate_last / 2.0)
            med = clamp((rate_last + (dil - 1.0) * 100.0 * p_new) / dil)
            med_logit = logit(med)
            q = [round4(clamp(inv_logit(med_logit + z * SIGMA_FLAT))) for z in Z]
            rows.append({"id": trophy["id"], "q": q})
        return {"trophies": rows}

    # Moving history: adaptive recent window (widen until >= MIN_DISTINCT
    # distinct reads, so a stale tail cannot flatten the fit).
    t_end = read_ts[-1]
    window = WINDOW_HOURS
    while window <= WINDOW_MAX_HOURS:
        sub = [r for r, ts in zip(hist, read_ts) if ts >= t_end - window * 3600]
        if len(set(tuple(r["rates"]) for r in sub)) >= MIN_DISTINCT or window >= WINDOW_MAX_HOURS:
            break
        window *= 2
    in_window = [ts >= t_end - window * 3600 for ts in read_ts]

    fits = []
    for i in range(len(trophies)):
        xs, ys = [], []
        for j, r in enumerate(hist):
            if not in_window[j]:
                continue
            v = r["rates"][i]
            if v is None:
                continue
            xs.append(math.log1p(max(hours[j], 0.0)))
            ys.append(logit(v))
        fits.append(fit_line(xs, ys) if xs else None)

    kind_slopes = {}
    for kind in ("chapter", "mission", "activity", "grind", "misc", "platinum"):
        bs = [
            f[1] for f, t in zip(fits, trophies)
            if f and kind_of(t) == kind and f[3] >= 3 and abs(f[1]) < 20
        ]
        if bs:
            kind_slopes[kind] = sum(bs) / len(bs)
    all_bs = [f[1] for f in fits if f and f[3] >= 3 and abs(f[1]) < 20]
    global_b = sum(all_bs) / len(all_bs) if all_bs else 0.0

    rw = SIGMA_RW * math.sqrt(horizon_days)
    x_last = math.log1p(max(hours[-1], 0.0))

    for i, trophy in enumerate(trophies):
        rate_last = last["rates"][i]
        if rate_last is None:
            rate_last = 0.01
        if rate_last >= 99.9:
            rows.append({"id": trophy["id"], "q": [99.9, 99.95, 99.99, 99.99, 99.99]})
            continue
        lg_last = logit(rate_last)
        kind = kind_of(trophy)
        kb = kind_slopes.get(kind, global_b)
        f = fits[i]
        if f is None or f[3] < 3:
            # No usable fit: hold the last rate, grow at the kind's slope.
            med_logit = lg_last + kb * (x_target - x_last) * (1.0 - DAMP)
            sig = SIGMA_NOFIT
            med = clamp(inv_logit(med_logit))
        else:
            a, b, sd, n = f
            w = n / (n + SHRINK_K)
            b_s = w * b + (1.0 - w) * kb
            gap = x_target - x_last
            med_fit = (a + b_s * x_target) - DAMP * b_s * gap
            med_anchor = lg_last + b_s * gap * (1.0 - DAMP)
            med = clamp(inv_logit(0.5 * med_fit + 0.5 * med_anchor))
            med = min(med, KIND_CEIL.get(kind, 90.0))
            sig = max(math.sqrt(sd * sd + rw * rw), SIGMA_FLOOR) * SIGMA_SCALE
        med_logit = logit(med)
        q = [round4(clamp(inv_logit(med_logit + z * sig))) for z in Z]
        for j in range(1, 5):
            if q[j] < q[j - 1]:
                q[j] = q[j - 1]
        rows.append({"id": trophy["id"], "q": q})
    return {"trophies": rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
