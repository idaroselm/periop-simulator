"""Validation tests for sim_core.py (both engines).  Run from the project folder:  pytest -q

What is checked
 1. Hand-calculated answers: with no randomness (sd = 0) the results must equal what you can work out on paper.
 2. The Excel workbook: fed the exact random draws from 50 Excel days (tests/excel_days.json),
    each engine must reproduce Excel's peak census, last OR / PACU times and the full 15-minute grids.
 3. An independent brute-force model (minute-by-minute census) on 200 random days.
 4. Queueing theory: mid-day average census must match Little's Law (L = arrival rate x time in stage).
 5. The two engines agree statistically, and every result is internally consistent.
"""
import json
import math
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import sim_core  # noqa: E402

ENGINES = ["python", "numpy"]
EXCEL_DAYS = json.loads((pathlib.Path(__file__).parent / "excel_days.json").read_text())


# ---------------------------------------------------------------- helpers: feed fixed draws into an engine
def run_with_draws(engine, monkeypatch, pre, ort, pac, cases, n_or=11, cushion=0, **extra):
    """Run one simulated day where the 'random' times are the given lists (patient order: OR 1 cases 1..n, OR 2, ...)."""
    params = dict(reps=1, cases=cases, n_or=n_or, buf_min=cushion, buf_max=cushion, wave_gap=30, **extra)
    if engine == "python":
        seq = iter([v for trio in zip(pre, ort, pac) for v in trio])

        class FakeRandom:                       # stands in for random.Random
            def __init__(self, seed): pass
            def gauss(self, m, s): return next(seq)
            def randint(self, a, b): return a

        monkeypatch.setattr(sim_core.random, "Random", FakeRandom)
    else:
        arrays = iter([np.array(x, float).reshape(1, n_or, cases) for x in (pre, ort, pac)])

        class FakeGenerator:                    # stands in for numpy.random.default_rng(seed)
            def normal(self, m, s, shape): return next(arrays)
            def integers(self, lo, hi, shape): return np.full(shape, lo)

        monkeypatch.setattr(np.random, "default_rng", lambda seed: FakeGenerator())
    return sim_core.simulate(params, engine=engine)


def reference_day(pre, ort, pac, cases, n_or=11, first=450, turnover=30, cushion=0):
    """Independent brute-force model: build every patient's times, then count census minute by minute."""
    h_in, h_out, p_in, p_out = [], [], [], []
    for o in range(n_or):
        t = first
        for c in range(cases):
            i = o * cases + c
            or_in = t
            or_out = or_in + ort[i]
            h_in.append(or_in - pre[i] - cushion); h_out.append(or_in)
            p_in.append(or_out); p_out.append(or_out + pac[i])
            t = or_out + turnover
    minutes = np.arange(0, 3 * 1440)
    census = lambda a, b: ((np.array(a)[:, None] <= minutes) & (np.array(b)[:, None] > minutes)).sum(axis=0)
    starts = sim_core.T0 + sim_core.BIN * np.arange(sim_core.NB)
    grid = lambda a, b: [int(sum(1 for x, y in zip(a, b) if x <= s + sim_core.BIN - 1 / 60 and y > s)) for s in starts]
    ch, cp = census(h_in, h_out), census(p_in, p_out)
    return dict(peak_hold=int(ch.max()), peak_pacu=int(cp.max()), last_or=max(p_in), last_pacu=max(p_out),
                grid_hold=grid(h_in, h_out), grid_pacu=grid(p_in, p_out), census_hold=ch, census_pacu=cp)


def random_draws(rng, n):
    f = lambda m, s: np.abs(np.floor(rng.normal(m, s, n))).tolist()     # ABS(INT(NORM.INV(RAND(), m, s)))
    return f(60, 30), f(60, 20), f(90, 40)


# ---------------------------------------------------------------- 1. hand-calculated answers (no randomness)
NO_VARIATION = dict(pre_s=0, or_s=0, pacu_s=0, reps=200)


@pytest.mark.parametrize("engine", ENGINES)
def test_no_variation_88_cases(engine):
    r = sim_core.simulate(dict(NO_VARIATION, cases=8), engine=engine)
    # 11 first-case patients sit in pre-op 6:30-7:30; every later patient replaces one exactly -> 11 at once
    assert (r["need_hold"], r["need_pacu"]) == (11, 11)
    assert r["last_or_mean"] == 7.5 * 60 + 7 * 90 + 60          # 7:30 + 7 x (60 + 30) + 60 = 7:00 PM
    assert r["last_pacu_p95"] == r["last_or_mean"] + 90          # 8:30 PM
    assert r["obs_fit"] == 23 - 11
    assert (r["over_hold"], r["over_pacu"]) == (1.0, 0.0)        # 11 > 9 free beds; 11 <= 12 PACU beds
    assert r["hold_empty_after"] == 18 * 60                      # last patient leaves pre-op at 6:00 PM


@pytest.mark.parametrize("engine", ENGINES)
def test_no_variation_44_cases(engine):
    r = sim_core.simulate(dict(NO_VARIATION, cases=4), engine=engine)
    assert (r["need_hold"], r["need_pacu"]) == (11, 11)
    assert r["last_or_mean"] == 7.5 * 60 + 3 * 90 + 60           # 1:00 PM
    assert r["hold_empty_after"] == 12 * 60                      # noon


@pytest.mark.parametrize("engine", ENGINES)
def test_no_variation_early_arrival(engine):
    # arriving 45 min early makes each pre-op stay 105 min, so consecutive patients of an OR overlap for 15 min
    r = sim_core.simulate(dict(NO_VARIATION, cases=8, buf_min=45, buf_max=45), engine=engine)
    assert r["need_hold"] == 22
    assert r["need_pacu"] == 11                                  # PACU is unaffected


@pytest.mark.parametrize("engine", ENGINES)
def test_no_variation_staggered_waves(engine):
    # waves split 11 ORs 4 / 4 / 3; the last wave starts 90 min later, so the day ends 90 min later
    r = sim_core.simulate(dict(NO_VARIATION, cases=8, waves=3, wave_gap=45), engine=engine)
    assert sim_core.wave_starts(dict(sim_core.DEFAULTS, waves=3, wave_gap=45)) == [450] * 4 + [495] * 4 + [540] * 3
    assert r["last_or_mean"] == 19 * 60 + 90


# ---------------------------------------------------------------- 2. the Excel workbook, draw for draw
@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("day", range(len(EXCEL_DAYS)))
def test_matches_excel(engine, day, monkeypatch):
    x = EXCEL_DAYS[day]
    r = run_with_draws(engine, monkeypatch, x["pre"], x["or"], x["pacu"], x["cases"])
    assert r["need_hold"] == x["peak_hold"]
    assert r["need_pacu"] == x["peak_pacu"]
    assert r["last_or_mean"] == pytest.approx(x["last_or"], abs=1e-6)
    assert r["last_pacu_p95"] == pytest.approx(x["last_pacu"], abs=1e-6)
    # Excel's grid covers 24 hours (96 intervals); the model's runs 48 hours, and the extra 24 must be empty
    assert [int(v) for v in r["p95_hold"][:96]] == x["grid_hold"] and not any(r["p95_hold"][96:])
    assert [int(v) for v in r["p95_pacu"][:96]] == x["grid_pacu"] and not any(r["p95_pacu"][96:])


# ---------------------------------------------------------------- 3. an independent brute-force model
@pytest.mark.parametrize("engine", ENGINES)
def test_matches_brute_force_model(engine, monkeypatch):
    rng = np.random.default_rng(2026)
    for _ in range(100):
        cases = int(rng.integers(1, 9))
        cushion = int(rng.integers(0, 46))
        pre, ort, pac = random_draws(rng, 11 * cases)
        ref = reference_day(pre, ort, pac, cases, cushion=cushion)
        r = run_with_draws(engine, monkeypatch, pre, ort, pac, cases, cushion=cushion)
        assert (r["need_hold"], r["need_pacu"]) == (ref["peak_hold"], ref["peak_pacu"])
        assert r["last_or_mean"] == ref["last_or"] and r["last_pacu_p95"] == ref["last_pacu"]
        assert [int(v) for v in r["p95_hold"]] == ref["grid_hold"]
        assert [int(v) for v in r["p95_pacu"]] == ref["grid_pacu"]


# ---------------------------------------------------------------- 4. Little's Law
def test_littles_law_midday():
    """Mid-day (11 AM-5 PM) each OR sends one patient per OR case + turnover (about 90 min).
    L = arrivals per minute x average minutes in the stage."""
    rng = np.random.default_rng(7)
    ch, cp, e_pre, e_pac, e_cycle = [], [], [], [], []
    for _ in range(1500):
        pre, ort, pac = random_draws(rng, 88)
        ref = reference_day(pre, ort, pac, 8)
        ch.append(ref["census_hold"][660:1020].mean()); cp.append(ref["census_pacu"][660:1020].mean())
        e_pre += pre; e_pac += pac; e_cycle += [o + 30 for o in ort]
    rate = 11 / np.mean(e_cycle)                                  # patients per minute into each stage
    assert np.mean(cp) == pytest.approx(rate * np.mean(e_pac), abs=0.25)   # about 11 in PACU
    assert np.mean(ch) == pytest.approx(rate * np.mean(e_pre), abs=0.25)   # about 7.3 in pre-op


# ---------------------------------------------------------------- 5. engines agree; results are consistent
def test_engines_agree_statistically():
    for params in (dict(cases=8), dict(cases=4), dict(cases=8, waves=3, wave_gap=45), dict(cases=8, buf_min=10, buf_max=45)):
        a = sim_core.simulate(dict(params, reps=4000, seed=11), engine="python")
        b = sim_core.simulate(dict(params, reps=4000, seed=12), engine="numpy")
        assert a["mean_hold"] == pytest.approx(b["mean_hold"], abs=0.15)
        assert a["mean_pacu"] == pytest.approx(b["mean_pacu"], abs=0.15)
        assert abs(a["need_hold"] - b["need_hold"]) <= 1 and abs(a["need_pacu"] - b["need_pacu"]) <= 1
        assert a["last_or_mean"] == pytest.approx(b["last_or_mean"], abs=5)


@pytest.mark.parametrize("engine", ENGINES)
def test_internal_consistency(engine):
    rng = np.random.default_rng(99)
    for _ in range(25):
        p = dict(cases=int(rng.integers(1, 9)), n_or=int(rng.integers(1, 12)), waves=int(rng.integers(1, 4)),
                 wave_gap=int(rng.choice([0, 15, 30, 45, 60])), buf_min=0, buf_max=int(rng.integers(0, 46)),
                 hold_beds=int(rng.integers(10, 30)), obs=int(rng.integers(0, 15)), pacu_beds=int(rng.integers(6, 20)),
                 reps=150, seed=int(rng.integers(0, 10**6)))
        r = sim_core.simulate(p, engine=engine)
        assert r["avail"] == max(0, p["hold_beds"] - p["obs"])
        assert r["obs_fit"] == max(0, p["hold_beds"] - r["need_hold"])
        assert r["need_hold"] <= r["max_hold"] and r["need_pacu"] <= r["max_pacu"]
        assert r["over_pacu"] == pytest.approx(r["curve_pacu"][min(p["pacu_beds"], len(r["curve_pacu"]) - 1)])
        assert r["over_hold"] == pytest.approx(r["curve_hold"][min(r["avail"], len(r["curve_hold"]) - 1)])
        for c in (r["curve_hold"], r["curve_pacu"]):
            assert all(x >= y for x, y in zip(c, c[1:])), "more beds can never mean more days over"
        assert r["last_pacu_p95"] >= r["last_or_p95"] - 1e-9
        assert json.loads(sim_core.run_json(json.dumps(p)))["need_hold"] >= 0      # browser entry point works


def test_percentile_matches_excel():
    # Excel: PERCENTILE({1,2,3,4}, 0.95) = 3.85 and PERCENTILE({5,1,9}, 0.5) = 5
    assert sim_core.percentile([1, 2, 3, 4], 0.95) == pytest.approx(3.85)
    assert sim_core.percentile([5, 1, 9], 0.5) == 5
    assert float(np.percentile([1, 2, 3, 4], 95)) == pytest.approx(3.85)


# ---------------------------------------------------------------- 6. service level and typical-day lines
@pytest.mark.parametrize("engine", ENGINES)
def test_service_level_is_monotone(engine):
    """A stricter planning standard can never need fewer beds."""
    r90, r95, r99 = (sim_core.simulate(dict(reps=500, service_level=s), engine=engine) for s in (0.90, 0.95, 0.99))
    assert r90["need_hold"] <= r95["need_hold"] <= r99["need_hold"]
    assert r90["need_pacu"] <= r95["need_pacu"] <= r99["need_pacu"]
    # "beds needed" is the first bed count whose share of days over is within the standard
    for r, s in ((r90, 0.90), (r95, 0.95), (r99, 0.99)):
        assert r["curve_pacu"][r["need_pacu"]] <= 1 - s + 1e-9
        assert r["curve_pacu"][r["need_pacu"] - 1] > 1 - s - 0.01


@pytest.mark.parametrize("engine", ENGINES)
def test_typical_day_never_above_busy_day(engine):
    r = sim_core.simulate(dict(reps=300), engine=engine)
    for stage in ("hold", "pacu"):
        assert all(t <= b + 1e-9 for t, b in zip(r[f"p50_{stage}"], r[f"p95_{stage}"]))


# ---------------------------------------------------------------- 7. bigger environments
@pytest.mark.parametrize("engine", ENGINES)
def test_large_environment_runs_and_matches_brute_force(engine, monkeypatch):
    """20 ORs x 14 cases: the day runs past midnight and the 36-hour grid still holds every patient."""
    rng = np.random.default_rng(5)
    pre, ort, pac = random_draws(rng, 20 * 14)
    ref = reference_day(pre, ort, pac, 14, n_or=20)
    r = run_with_draws(engine, monkeypatch, pre, ort, pac, 14, n_or=20)
    assert (r["need_hold"], r["need_pacu"]) == (ref["peak_hold"], ref["peak_pacu"])
    assert [int(v) for v in r["p95_pacu"]] == ref["grid_pacu"]
    assert ref["last_pacu"] < sim_core.T0 + sim_core.NB * sim_core.BIN      # nobody falls off the end of the grid


# ---------- occupancy and goal-seek ----------
def test_avg_census_hand_calculation():
    """1 OR, 2 cases, no variation: pre-op 6:30-7:30 and 8:00-9:00 -> 120 patient-min over 150 min = 0.8;
    PACU 8:30-10:00 and 10:00-11:30 -> 180 over 180 = 1.0."""
    p = dict(n_or=1, cases=2, pre_s=0, or_s=0, pacu_s=0, reps=3)
    for eng in ("numpy", "python"):
        r = sim_core.simulate(p, engine=eng)
        assert r["avg_census_hold"] == pytest.approx(0.8)
        assert r["avg_census_pacu"] == pytest.approx(1.0)


def test_avg_census_engines_agree_and_below_peak():
    a, b = sim_core.simulate(engine="numpy"), sim_core.simulate(engine="python")
    assert a["avg_census_pacu"] == pytest.approx(b["avg_census_pacu"], rel=0.02)
    assert a["avg_census_hold"] == pytest.approx(b["avg_census_hold"], rel=0.02)
    assert a["avg_census_pacu"] < a["mean_pacu"] and a["avg_census_hold"] < a["mean_hold"]


def test_occupancy():
    assert sim_core.occupancy(9, 12) == pytest.approx(0.75)
    assert sim_core.occupancy(9, 0) is None


def test_fits_checks_each_target():
    r = {"need_hold": 10, "avail": 9, "need_pacu": 12, "params": {"pacu_beds": 12}, "last_or_p95": 1200}
    assert not sim_core.fits(r)
    assert sim_core.fits(r, ("pacu",))
    assert not sim_core.fits(r, ("pacu",), end_by=1140)
    assert sim_core.fits(r, ("pacu",), end_by=1200)


def test_find_limit_max_and_min():
    p = {**sim_core.DEFAULTS, "reps": 100}
    best, runs = sim_core.find_limit(p, "n_or", range(1, 12))
    assert best is not None
    for v, r in runs:                       # everything up to the answer fits; the next one doesn't
        if v <= best:
            assert sim_core.fits(r)
    if best < 11:
        assert not sim_core.fits(dict(runs)[best + 1])
    # plenty of beds -> every value fits, max returns the last value tried
    big = {**p, "hold_beds": 200, "obs": 0, "pacu_beds": 200}
    assert sim_core.find_limit(big, "cases", range(1, 6))[0] == 5
    # min returns the first value that fits
    assert sim_core.find_limit(big, "waves", range(1, 4), goal="min")[0] == 1
    # impossible target -> None
    assert sim_core.find_limit({**p, "pacu_beds": 0}, "cases", range(1, 4))[0] is None


# ---------- fractional cases per OR (today's 2.5 cases per OR) ----------
def test_case_counts_spread_evenly():
    assert sim_core.case_counts({"n_or": 11, "cases": 2.5}) == [3] * 6 + [2] * 5      # 27.5 -> 28 cases
    assert sim_core.total_cases({"n_or": 11, "cases": 8}) == 88
    assert sim_core.case_counts({"n_or": 4, "cases": 1.25}) == [2, 1, 1, 1]


@pytest.mark.parametrize("engine", ["numpy", "python"])
def test_fractional_cases_hand_calculation(engine):
    """2 ORs, 1.5 cases each = 3 cases: OR 1 does 2, OR 2 does 1. No variation:
    OR 1: 7:30-8:30, 9:00-10:00; OR 2: 7:30-8:30. Pre-op peak 2 (6:30-7:30), PACU: 8:30-10:00 x2 and 10:00-11:30
    -> peak 2; last case out of the OR 10:00; last PACU out 11:30."""
    r = sim_core.simulate(dict(n_or=2, cases=1.5, pre_s=0, or_s=0, pacu_s=0, reps=5), engine=engine)
    assert (r["need_hold"], r["need_pacu"]) == (2, 2)
    assert r["last_or_mean"] == 600 and r["last_pacu_p95"] == 690
    # census: pre-op 180 patient-min over 6:30-9:00 (150 min) = 1.2; PACU 270 over 8:30-11:30 (180 min) = 1.5
    assert r["avg_census_hold"] == pytest.approx(1.2) and r["avg_census_pacu"] == pytest.approx(1.5)


def test_fractional_cases_engines_agree_and_sit_between_whole_numbers():
    a = sim_core.simulate(dict(cases=2.5, reps=3000, seed=1), engine="numpy")
    b = sim_core.simulate(dict(cases=2.5, reps=3000, seed=2), engine="python")
    assert abs(a["mean_pacu"] - b["mean_pacu"]) < 0.15 and abs(a["mean_hold"] - b["mean_hold"]) < 0.15
    lo, hi = (sim_core.simulate(dict(cases=c, reps=3000, seed=1)) for c in (2, 3))
    assert lo["last_or_mean"] < a["last_or_mean"] < hi["last_or_mean"]
    assert lo["mean_pacu"] <= a["mean_pacu"] + 0.05 and a["mean_pacu"] <= hi["mean_pacu"] + 0.05
