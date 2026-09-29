"""Periop capacity DES - Holding Room (pre-op) -> OR -> PACU.

Same logic as the Excel workbook (MGT 6473 final project):
  * times ~ ABS(INT(NORM.INV(RAND(), mean, sd)))
  * case 1 enters the OR at its wave's start time; later cases = previous OR out + turnover
  * Holding In = OR In - pre-op time - early-arrival cushion (pre-op ends as the OR is ready)
  * PACU In = OR Out; census at time t counts patients with In <= t < Out
Two engines with identical rules: a vectorized NumPy engine (fast, used by Streamlit) and a\npure standard-library engine (used in the browser via Pyodide, where NumPy isn't loaded).
"""
import json
import math
import random
import time

T0, NB, BIN = 240, 96, 15          # grid: 96 x 15-min intervals starting 4:00 AM (minutes after midnight)

DEFAULTS = dict(n_or=11, cases=8, first=450, waves=1, wave_gap=30, turnover=30,
                pre_m=60, pre_s=30, or_m=60, or_s=20, pacu_m=90, pacu_s=40,
                hold_beds=23, obs=14, pacu_beds=12, buf_min=0, buf_max=0, reps=1000, seed=6473)


def draw(rng, m, s):
    """ABS(INT(NORM.INV(RAND(), m, s)))"""
    return abs(math.floor(rng.gauss(m, s)))


def peak(ins, outs):
    """Most patients present at the same moment (In <= t < Out)."""
    events = [(t, 1) for t in ins] + [(t, -1) for t in outs]
    events.sort()                   # at equal times, departures (-1) sort before arrivals
    cur = best = 0
    for _, d in events:
        cur += d
        best = max(best, cur)
    return best


def add_to_grid(counts, t_in, t_out):
    """Count the patient in every 15-min interval they touch (the Excel grid rule)."""
    lo = max(0, math.ceil((t_in - T0 - BIN + 1 / 60) / BIN))
    hi = min(NB - 1, math.ceil((t_out - T0) / BIN) - 1)
    for i in range(lo, hi + 1):
        counts[i] += 1


def percentile(vals, q):
    """Excel PERCENTILE (linear interpolation)."""
    s = sorted(vals)
    k = (len(s) - 1) * q
    f = math.floor(k)
    return s[f] + (k - f) * (s[f + 1] - s[f]) if f + 1 < len(s) else s[f]


def wave_starts(p):
    """Split the ORs into waves as evenly as possible (11 ORs: 1 wave 11 / 2 waves 6+5 / 3 waves 4+4+3)."""
    n = p["n_or"]
    return [p["first"] + (i * p["waves"] // n) * p["wave_gap"] for i in range(n)]


def simulate_py(p):
    """Pure standard-library engine (used in the browser via Pyodide, or when NumPy is missing)."""
    t_start = time.perf_counter()
    rng = random.Random(p["seed"])
    starts = wave_starts(p)
    peaks_h, peaks_p, last_or, last_pacu = [], [], [], []
    grid_h, grid_p = [], []
    for _ in range(p["reps"]):
        h_in, h_out, p_in, p_out = [], [], [], []
        gh, gp = [0] * NB, [0] * NB
        for o in range(p["n_or"]):
            prev_out = None
            for c in range(p["cases"]):
                pre = draw(rng, p["pre_m"], p["pre_s"])
                ort = draw(rng, p["or_m"], p["or_s"])
                pac = draw(rng, p["pacu_m"], p["pacu_s"])
                cush = rng.randint(p["buf_min"], max(p["buf_min"], p["buf_max"]))
                or_in = starts[o] if c == 0 else prev_out + p["turnover"]
                or_out = or_in + ort
                prev_out = or_out
                hold_in = or_in - pre - cush
                h_in.append(hold_in); h_out.append(or_in)
                p_in.append(or_out); p_out.append(or_out + pac)
                add_to_grid(gh, hold_in, or_in)
                add_to_grid(gp, or_out, or_out + pac)
        peaks_h.append(peak(h_in, h_out))
        peaks_p.append(peak(p_in, p_out))
        last_or.append(max(p_in))
        last_pacu.append(max(p_out))
        grid_h.append(gh)
        grid_p.append(gp)

    avail = max(0, p["hold_beds"] - p["obs"])
    need_h = math.ceil(percentile(peaks_h, 0.95))
    need_p = math.ceil(percentile(peaks_p, 0.95))
    p95_h = [percentile([g[i] for g in grid_h], 0.95) for i in range(NB)]
    p95_p = [percentile([g[i] for g in grid_p], 0.95) for i in range(NB)]
    busy = [i for i, v in enumerate(p95_h) if v > 0]
    n = len(peaks_h)
    return {
        "params": p,
        "starts": starts,
        "avail": avail,
        "need_hold": need_h,
        "need_pacu": need_p,
        "mean_hold": sum(peaks_h) / n,
        "mean_pacu": sum(peaks_p) / n,
        "max_hold": max(peaks_h),
        "max_pacu": max(peaks_p),
        "over_hold": sum(v > avail for v in peaks_h) / n,
        "over_pacu": sum(v > p["pacu_beds"] for v in peaks_p) / n,
        "obs_fit": max(0, p["hold_beds"] - need_h),
        "last_or_mean": sum(last_or) / n,
        "last_or_p95": percentile(last_or, 0.95),
        "last_pacu_p95": percentile(last_pacu, 0.95),
        "hold_empty_after": T0 + (busy[-1] + 1) * BIN if busy else None,
        "p95_hold": p95_h,
        "p95_pacu": p95_p,
        # share of days each stage would run over with N beds, N = 0..30
        "curve_hold": [sum(v > b for v in peaks_h) / n for b in range(31)],
        "curve_pacu": [sum(v > b for v in peaks_p) / n for b in range(31)],
        "elapsed_s": time.perf_counter() - t_start,
        "engine": "pure Python",
    }


def simulate_np(p):
    """Vectorized NumPy engine: same rules, all simulated days at once (about 20x faster in CPython)."""
    import numpy as np
    t_start = time.perf_counter()
    rng = np.random.default_rng(p["seed"])
    R, n, C = p["reps"], p["n_or"], p["cases"]
    shape = (R, n, C)
    pre = np.abs(np.floor(rng.normal(p["pre_m"], p["pre_s"], shape)))
    ort = np.abs(np.floor(rng.normal(p["or_m"], p["or_s"], shape)))
    pac = np.abs(np.floor(rng.normal(p["pacu_m"], p["pacu_s"], shape)))
    cush = rng.integers(p["buf_min"], max(p["buf_min"], p["buf_max"]) + 1, shape)
    starts = np.array(wave_starts(p), float)
    # OR In for case c = wave start + sum of earlier cases' (OR time + turnover)
    step = ort + p["turnover"]
    before = np.concatenate([np.zeros((R, n, 1)), np.cumsum(step[:, :, :-1], axis=2)], axis=2)
    or_in = starts[None, :, None] + before
    or_out = or_in + ort
    h_in, h_out = (or_in - pre - cush).reshape(R, -1), or_in.reshape(R, -1)
    p_in, p_out = or_out.reshape(R, -1), (or_out + pac).reshape(R, -1)

    def peaks(a, b):   # sweep the day's events in time order (departures before arrivals at a tie); max running census
        t = np.concatenate([a, b], axis=1)
        d = np.concatenate([np.ones_like(a), -np.ones_like(b)], axis=1)
        order = np.lexsort((d, t), axis=-1)
        return np.cumsum(np.take_along_axis(d, order, axis=1), axis=1).max(axis=1)

    s0 = T0 + BIN * np.arange(NB)
    e0 = s0 + BIN - 1 / 60

    def grid(a, b):    # patients touching each 15-min interval (Excel grid rule)
        return ((a[:, :, None] <= e0) & (b[:, :, None] > s0)).sum(axis=1)

    pk_h, pk_p = peaks(h_in, h_out), peaks(p_in, p_out)
    p95_h = np.percentile(grid(h_in, h_out), 95, axis=0)       # linear = Excel PERCENTILE
    p95_p = np.percentile(grid(p_in, p_out), 95, axis=0)
    last_or, last_pacu = p_in.max(axis=1), p_out.max(axis=1)
    avail = max(0, p["hold_beds"] - p["obs"])
    need_h = int(math.ceil(np.percentile(pk_h, 95)))
    need_p = int(math.ceil(np.percentile(pk_p, 95)))
    busy = np.nonzero(p95_h > 0)[0]
    beds = np.arange(31)
    return {
        "params": p, "starts": starts.tolist(), "avail": avail,
        "need_hold": need_h, "need_pacu": need_p,
        "mean_hold": float(pk_h.mean()), "mean_pacu": float(pk_p.mean()),
        "max_hold": int(pk_h.max()), "max_pacu": int(pk_p.max()),
        "over_hold": float((pk_h > avail).mean()), "over_pacu": float((pk_p > p["pacu_beds"]).mean()),
        "obs_fit": max(0, p["hold_beds"] - need_h),
        "last_or_mean": float(last_or.mean()), "last_or_p95": float(np.percentile(last_or, 95)),
        "last_pacu_p95": float(np.percentile(last_pacu, 95)),
        "hold_empty_after": int(T0 + (busy[-1] + 1) * BIN) if busy.size else None,
        "p95_hold": p95_h.tolist(), "p95_pacu": p95_p.tolist(),
        "curve_hold": (pk_h[:, None] > beds).mean(axis=0).tolist(),
        "curve_pacu": (pk_p[:, None] > beds).mean(axis=0).tolist(),
        "elapsed_s": time.perf_counter() - t_start,
        "engine": "NumPy",
    }


def simulate(params=None, engine="auto"):
    """engine: "auto" (NumPy if installed, else pure Python), "numpy" or "python"."""
    p = dict(DEFAULTS, **(params or {}))
    if engine in ("auto", "numpy"):
        try:
            import numpy  # noqa: F401
            return simulate_np(p)
        except ImportError:
            if engine == "numpy":
                raise
    return simulate_py(p)


def run_json(params_json):
    """Entry point for the browser page: JSON in, JSON out."""
    return json.dumps(simulate(json.loads(params_json), engine="python"))


if __name__ == "__main__":
    for eng in ("numpy", "python"):
        r = simulate(engine=eng)
        print(eng, {k: r[k] for k in ("need_hold", "need_pacu", "mean_hold", "mean_pacu", "over_pacu", "obs_fit", "elapsed_s")})
