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

T0, NB, BIN = 240, 192, 15         # grid: 192 x 15-min intervals = 48 hours from 4:00 AM, room for long OR days

DEFAULTS = dict(n_or=11, cases=8, first=450, waves=1, wave_gap=45, turnover=30,
                pre_m=60, pre_s=30, or_m=60, or_s=20, pacu_m=90, pacu_s=40,
                hold_beds=23, obs=14, pacu_beds=12, buf_min=0, buf_max=0, reps=1000, seed=6473,
                service_level=0.95)   # beds are sized to be enough on this share of simulated days
# The case baseline. reps=1000 simulated days gives a steady answer (use reps=100 to mirror the Excel log's size).


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


def ceil_beds(x):
    """Round a percentile up to whole beds, ignoring floating-point dust (17.0000000001 stays 17)."""
    return int(math.ceil(x - 1e-9))


def percentile(vals, q):
    """Excel PERCENTILE (linear interpolation)."""
    s = sorted(vals)
    k = (len(s) - 1) * q
    f = math.floor(k)
    return s[f] + (k - f) * (s[f + 1] - s[f]) if f + 1 < len(s) else s[f]


def curve_len(*peak_lists):
    """Bed counts for the sizing curve: 0 up to one past the busiest simulated day (at least 0..30)."""
    return max(31, max(max(v) for v in peak_lists) + 2)


def avg_census(ins, outs):
    """Average patients present while the unit is in use (first arrival to last departure) = patient-minutes / window."""
    window = max(outs) - min(ins)
    return sum(o - i for i, o in zip(ins, outs)) / window if window > 0 else 0.0


def case_counts(p):
    """Cases each OR does. A fractional average (e.g. 2.5 per OR, today's level) is spread as evenly as possible:
    11 ORs x 2.5 = 27.5 -> 28 cases -> 6 ORs do 3 and 5 ORs do 2. Whole numbers give every OR the same count."""
    n = p["n_or"]
    total = int(p["cases"] * n + 0.5)
    base, extra = divmod(total, n)
    return [base + (1 if o < extra else 0) for o in range(n)]


def total_cases(p):
    return sum(case_counts(p))


def wave_starts(p):
    """Split the ORs into waves as evenly as possible (11 ORs: 1 wave 11 / 2 waves 6+5 / 3 waves 4+4+3)."""
    n = p["n_or"]
    return [p["first"] + (i * p["waves"] // n) * p["wave_gap"] for i in range(n)]


def simulate_py(p):
    """Pure standard-library engine (used in the browser via Pyodide, or when NumPy is missing)."""
    t_start = time.perf_counter()
    rng = random.Random(p["seed"])
    starts = wave_starts(p)
    counts = case_counts(p)
    peaks_h, peaks_p, last_or, last_pacu, cen_h, cen_p = [], [], [], [], [], []
    grid_h, grid_p = [], []
    for _ in range(p["reps"]):
        h_in, h_out, p_in, p_out = [], [], [], []
        gh, gp = [0] * NB, [0] * NB
        for o in range(p["n_or"]):
            prev_out = None
            for c in range(counts[o]):
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
        cen_h.append(avg_census(h_in, h_out))
        cen_p.append(avg_census(p_in, p_out))
        grid_h.append(gh)
        grid_p.append(gp)

    avail = max(0, p["hold_beds"] - p["obs"])
    sl = p["service_level"]
    need_h = ceil_beds(percentile(peaks_h, sl))
    need_p = ceil_beds(percentile(peaks_p, sl))
    p95_h = [percentile([g[i] for g in grid_h], sl) for i in range(NB)]       # busy day (service-level percentile)
    p95_p = [percentile([g[i] for g in grid_p], sl) for i in range(NB)]
    p50_h = [percentile([g[i] for g in grid_h], 0.5) for i in range(NB)]      # typical day (median)
    p50_p = [percentile([g[i] for g in grid_p], 0.5) for i in range(NB)]
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
        "avg_census_hold": sum(cen_h) / n,      # average patients present while the unit is in use
        "avg_census_pacu": sum(cen_p) / n,
        "max_hold": max(peaks_h),
        "max_pacu": max(peaks_p),
        "over_hold": sum(v > avail for v in peaks_h) / n,
        "over_pacu": sum(v > p["pacu_beds"] for v in peaks_p) / n,
        "obs_fit": max(0, p["hold_beds"] - need_h),
        "last_or_mean": sum(last_or) / n,
        "last_or_p95": percentile(last_or, sl),
        "last_pacu_p95": percentile(last_pacu, sl),
        "hold_empty_after": T0 + (busy[-1] + 1) * BIN if busy else None,
        "p95_hold": p95_h,
        "p95_pacu": p95_p,
        "p50_hold": p50_h,
        "p50_pacu": p50_p,
        "service_level": sl,
        # share of days each stage would run over with N beds, N = 0 .. (busiest day + 1, at least 30)
        "curve_hold": [sum(v > b for v in peaks_h) / n for b in range(curve_len(peaks_h, peaks_p))],
        "curve_pacu": [sum(v > b for v in peaks_p) / n for b in range(curve_len(peaks_h, peaks_p))],
        "elapsed_s": time.perf_counter() - t_start,
        "engine": "pure Python",
    }


def simulate_np(p):
    """Vectorized NumPy engine: same rules, all simulated days at once (about 20x faster in CPython)."""
    import numpy as np
    t_start = time.perf_counter()
    rng = np.random.default_rng(p["seed"])
    R, n = p["reps"], p["n_or"]
    counts = np.array(case_counts(p))
    C = int(counts.max())
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
    # ORs with fewer cases (fractional average): park their unused case slots far in the future with zero length,
    # so they never count toward a peak, a grid interval, an end time or a census.
    active = np.broadcast_to((np.arange(C)[None, :] < counts[:, None])[None], (R, n, C)).reshape(R, -1)
    if not active.all():
        FAR = 1e12
        h_in, h_out, p_in, p_out = (np.where(active, x, FAR) for x in (h_in, h_out, p_in, p_out))

    def peaks(a, b):   # sweep the day's events in time order (departures before arrivals at a tie); max running census
        t = np.concatenate([a, b], axis=1)
        d = np.concatenate([np.ones_like(a), -np.ones_like(b)], axis=1)
        order = np.lexsort((d, t), axis=-1)
        return np.cumsum(np.take_along_axis(d, order, axis=1), axis=1).max(axis=1)

    def grid(a, b):
        """Patients touching each 15-min interval (Excel grid rule), via +1/-1 marks and a running sum,
        so memory stays small even with many ORs and cases."""
        lo = np.clip(np.ceil((a - T0 - BIN + 1 / 60) / BIN), 0, NB).astype(int)
        hi = np.clip(np.ceil((b - T0) / BIN) - 1, -1, NB - 1).astype(int)
        ok = hi >= lo
        rows = np.broadcast_to(np.arange(a.shape[0])[:, None], a.shape)
        marks = np.zeros((a.shape[0], NB + 1), int)
        np.add.at(marks, (rows[ok], lo[ok]), 1)
        np.add.at(marks, (rows[ok], hi[ok] + 1), -1)
        return np.cumsum(marks, axis=1)[:, :NB]

    def census(a, b):   # per day: patient-minutes / (last departure - first arrival)
        window = np.where(active, b, -np.inf).max(axis=1) - np.where(active, a, np.inf).min(axis=1)
        return np.where(window > 0, (b - a).sum(axis=1) / np.where(window > 0, window, 1), 0.0)

    pk_h, pk_p = peaks(h_in, h_out), peaks(p_in, p_out)
    sl = p["service_level"]
    g_h, g_p = grid(h_in, h_out), grid(p_in, p_out)
    p95_h = np.percentile(g_h, 100 * sl, axis=0)       # busy day at the service level; linear = Excel PERCENTILE
    p95_p = np.percentile(g_p, 100 * sl, axis=0)
    p50_h, p50_p = np.percentile(g_h, 50, axis=0), np.percentile(g_p, 50, axis=0)   # typical day
    last_or, last_pacu = np.where(active, p_in, -np.inf).max(axis=1), np.where(active, p_out, -np.inf).max(axis=1)
    avail = max(0, p["hold_beds"] - p["obs"])
    need_h = ceil_beds(np.percentile(pk_h, 100 * sl))
    need_p = ceil_beds(np.percentile(pk_p, 100 * sl))
    busy = np.nonzero(p95_h > 0)[0]
    beds = np.arange(curve_len(pk_h.tolist(), pk_p.tolist()))
    return {
        "params": p, "starts": starts.tolist(), "avail": avail,
        "need_hold": need_h, "need_pacu": need_p,
        "mean_hold": float(pk_h.mean()), "mean_pacu": float(pk_p.mean()),
        "avg_census_hold": float(census(h_in, h_out).mean()), "avg_census_pacu": float(census(p_in, p_out).mean()),
        "max_hold": int(pk_h.max()), "max_pacu": int(pk_p.max()),
        "over_hold": float((pk_h > avail).mean()), "over_pacu": float((pk_p > p["pacu_beds"]).mean()),
        "obs_fit": max(0, p["hold_beds"] - need_h),
        "last_or_mean": float(last_or.mean()), "last_or_p95": float(np.percentile(last_or, 100 * sl)),
        "last_pacu_p95": float(np.percentile(last_pacu, 100 * sl)),
        "hold_empty_after": int(T0 + (busy[-1] + 1) * BIN) if busy.size else None,
        "p95_hold": p95_h.tolist(), "p95_pacu": p95_p.tolist(),
        "p50_hold": p50_h.tolist(), "p50_pacu": p50_p.tolist(), "service_level": sl,
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


def occupancy(avg_census, beds):
    """Average share of beds filled while the unit is in use (None when there are no beds)."""
    return avg_census / beds if beds > 0 else None


def fits(r, stages=("hold", "pacu"), end_by=None):
    """Does this run meet the target? Beds needed <= beds available for each stage checked,
    and (optionally) the last case is out of the OR by end_by (minutes after midnight) on the service-level share of days."""
    ok = True
    if "hold" in stages:
        ok = ok and r["need_hold"] <= r["avail"]
    if "pacu" in stages:
        ok = ok and r["need_pacu"] <= r["params"]["pacu_beds"]
    if end_by is not None:
        ok = ok and r["last_or_p95"] <= end_by
    return ok


def find_limit(params, key, values, goal="max", stages=("hold", "pacu"), end_by=None, engine="auto"):
    """Goal-seek one input. Runs the scenario at each value (in order) with everything else held fixed.
    goal="max": the largest value such that it and every smaller value tried meet the target (e.g. most cases per OR).
    goal="min": the first value that meets the target (e.g. fewest start waves).
    Returns (best value or None, [(value, result), ...])."""
    runs = [(v, simulate({**params, key: v}, engine)) for v in values]
    best = None
    for v, r in runs:
        if fits(r, stages, end_by):
            best = v
            if goal == "min":
                break
        elif goal == "max":
            break
    return best, runs


def run_json(params_json):
    """Entry point for the browser page: JSON in, JSON out."""
    return json.dumps(simulate(json.loads(params_json), engine="python"))


if __name__ == "__main__":
    for eng in ("numpy", "python"):
        r = simulate(engine=eng)
        print(eng, {k: r[k] for k in ("need_hold", "need_pacu", "mean_hold", "mean_pacu", "over_pacu", "obs_fit", "elapsed_s")})
