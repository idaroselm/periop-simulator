"""Periop Patient Flow and Capacity Planning Simulator (Streamlit).  Run:  streamlit run app.py"""
from datetime import time as dtime

import altair as alt
import pandas as pd
import streamlit as st

import importlib
import os

import sim_core

# Streamlit re-runs app.py when it changes, but keeps an already-imported sim_core.py in memory. After a git push
# that changes both files, the app would call the new code against the old model. Reload the model whenever its file changes.
_model_mtime = os.path.getmtime(sim_core.__file__)
if getattr(sim_core, "_loaded_mtime", None) != _model_mtime:
    sim_core = importlib.reload(sim_core)
    sim_core._loaded_mtime = _model_mtime

st.set_page_config(page_title="Periop Patient Flow and Capacity Planning Simulator", layout="wide")
first_visit = "seen" not in st.session_state   # open the how-to on a visitor's first load
st.session_state.seen = True

CUSTOM = "Custom · edit any input"
PRESETS = {
    "Case baseline · 88/day": {},
    "44 cases/day": {"cases": 4},
    "Stagger starts · 3 waves": {"waves": 3, "wave_gap": 45},
    "Patients arrive 10–45 min early": {"buf_min": 10, "buf_max": 45},
    "PACU with 18 beds": {"pacu_beds": 18},
}


def clock(m):
    if m is None:
        return "–"
    m = int(round(m))
    day, m = divmod(m, 1440)
    h, mi = divmod(m, 60)
    return f"{(h % 12) or 12}:{mi:02d} {'AM' if h < 12 else 'PM'}" + (" (next day)" if day >= 1 else "")


def pct(x, digits=1):
    """0.95 -> '95%', 0.975 -> '97.5%'."""
    return f"{x * 100:.{digits}f}".rstrip("0").rstrip(".") + "%"


# ---------- inputs ----------
# Every input lives in st.session_state under "in_<name>". Picking a preset fills in its scenario;
# picking Custom leaves the inputs exactly as they are, so any combination can be built and run.
BASELINE = dict(sim_core.DEFAULTS)          # the case baseline, 1,000 simulated days
SCENARIO_KEYS = ["cases", "n_or", "first", "waves", "wave_gap", "turnover", "pre_m", "pre_s", "or_m", "or_s",
                 "pacu_m", "pacu_s", "hold_beds", "obs", "pacu_beds", "buf_min", "buf_max"]
RUN_KEYS = ["reps", "seed", "service_level"]          # presets never change these


def to_widget(k, v):
    if k == "first":
        return dtime(int(v) // 60, int(v) % 60)
    return round(v * 100, 1) if k == "service_level" else v      # the slider shows percent


def scenario_of(name):
    return {**{k: BASELINE[k] for k in SCENARIO_KEYS}, **PRESETS[name]}


def apply_preset():
    name = st.session_state.preset
    if name != CUSTOM:
        for k, v in scenario_of(name).items():
            st.session_state[f"in_{k}"] = to_widget(k, v)


def read_inputs():
    g = lambda k: st.session_state[f"in_{k}"]
    first = g("first")
    p = {k: g(k) for k in SCENARIO_KEYS + RUN_KEYS if k != "first"}
    p["first"] = first.hour * 60 + first.minute
    p = {k: (round(float(v) / 100, 4) if k == "service_level" else int(v)) for k, v in p.items()}
    p["buf_max"] = max(p["buf_min"], p["buf_max"])
    return p


def on_run():
    """If the inputs no longer match the chosen preset, show Custom in the what-if list."""
    name = st.session_state.preset
    if name != CUSTOM:
        now = read_inputs()
        if any(now[k] != v for k, v in scenario_of(name).items() if k != "buf_max") or now["buf_max"] != scenario_of(name)["buf_max"]:
            st.session_state.preset = CUSTOM
    st.session_state.run_now = True


if "in_cases" not in st.session_state:                     # first visit: load the case baseline
    for k in SCENARIO_KEYS + RUN_KEYS:
        st.session_state[f"in_{k}"] = to_widget(k, BASELINE[k])

st.sidebar.title("Inputs")
preset = st.sidebar.selectbox("Start from a what-if", [*PRESETS, CUSTOM], key="preset", on_change=apply_preset,
                              help="A preset fills in the inputs below. Custom keeps whatever you have entered.")

# Inputs sit in a form: changing a box doesn't re-run the app; press "Run simulation" to apply all changes at once.
with st.sidebar.form("inputs"):
    st.slider("Size beds to be enough on (% of days)", 50.0, 99.5, step=0.5, format="%.1f%%", key="in_service_level",
              help="Your planning standard. 95% means the beds cover the whole day, busiest moment included, on 95 of every "
                   "100 days, and you accept running short on the other 5. Higher = safer but more beds. "
                   "Above 99%, use 1,000+ simulated days so the answer isn't resting on one or two days.")
    with st.expander("Schedule", expanded=True):
        st.number_input("Cases per OR per day", 1, 20, key="in_cases",
                        help="Up to 20. Long days run past midnight; the model tracks 48 hours from 4:00 AM.")
        st.number_input("Number of ORs", 1, 40, key="in_n_or")
        st.time_input("First case in", key="in_first", step=900,
                      help="The case: all ORs start at 7:30 AM. The charts start at 4:00 AM, so keep the first case after about 6:00 AM.")
        st.number_input("Start waves", 1, 6, key="in_waves", help="1 = every OR starts at the first-case time. ORs are split as evenly as possible.")
        st.number_input("Minutes between waves", 0, 180, step=15, key="in_wave_gap")
        st.number_input("OR turnover (min)", 0, 240, key="in_turnover")
    with st.expander("Times · normal (mean, sd), minutes"):
        c1, c2 = st.columns(2)
        c1.number_input("Pre-op mean", 0, 600, key="in_pre_m"); c2.number_input("Pre-op sd", 0, 300, key="in_pre_s")
        c1.number_input("OR mean", 0, 600, key="in_or_m"); c2.number_input("OR sd", 0, 300, key="in_or_s")
        c1.number_input("PACU mean", 0, 600, key="in_pacu_m"); c2.number_input("PACU sd", 0, 300, key="in_pacu_s")
    with st.expander("Beds", expanded=True):
        st.number_input("Holding Room beds", 0, 200, key="in_hold_beds")
        st.number_input("Obs patients in them", 0, 200, key="in_obs")
        st.number_input("PACU beds", 0, 200, key="in_pacu_beds")
    with st.expander("Early arrival before pre-op (minutes)", expanded=True):
        st.number_input("Cushion min", 0, 240, key="in_buf_min")
        st.number_input("Cushion max", 0, 240, key="in_buf_max")
    with st.expander("Simulation"):
        st.select_slider("Simulated days", [100, 500, 1000, 2000], key="in_reps",
                         help="1,000 (the default) gives a steady answer. 100 matches the size of the Excel log, "
                              "but answers can shift by a bed from one random seed to the next.")
        st.number_input("Random seed", step=1, key="in_seed")
    st.form_submit_button("Run simulation", type="primary", width="stretch", on_click=on_run)

params = read_inputs()


@st.cache_data(show_spinner="Simulating…", max_entries=64)
def run(p_items, model_version):
    """model_version (the model file's timestamp) keeps results cached from an older model from being reused."""
    return sim_core.simulate(dict(p_items))


# Results only change when "Run simulation" is pressed; the first visit shows the case baseline.
if "result" not in st.session_state:
    st.session_state.result, st.session_state.result_label = run(tuple(sorted(BASELINE.items())), _model_mtime), "Case baseline · 88/day"
if st.session_state.pop("run_now", False):
    st.session_state.result = run(tuple(sorted(params.items())), _model_mtime)
    st.session_state.result_label = "Custom scenario" if st.session_state.preset == CUSTOM else st.session_state.preset
r = st.session_state.result
rp = r["params"]                     # the inputs the shown results were run with
stale = {k: rp[k] for k in params} != params
LEVEL = pct(rp["service_level"])   # e.g. "95%"
SHORT = pct(1 - rp["service_level"])  # e.g. "5%"
occ_now_h = sim_core.occupancy(r["avg_census_hold"], r["avail"])
occ_now_p = sim_core.occupancy(r["avg_census_pacu"], rp["pacu_beds"])
occ_need_h = sim_core.occupancy(r["avg_census_hold"], r["need_hold"])
occ_need_p = sim_core.occupancy(r["avg_census_pacu"], r["need_pacu"])
show = lambda x: "–" if x is None else f"{x:.0%}"

# ---------- header + KPIs ----------
st.caption("MGT 6473 · Final project · What-if lab")
st.title("Periop Patient Flow and Capacity Planning Simulator")
st.write("Holding Room (pre-op) → ORs → PACU, with the same logic as the Excel workbook. "
         "Set up a scenario in the sidebar, press **Run simulation**, and read the answer below.")
if first_visit:
    st.info("New here? The **Guide** tab explains every input and result in plain language.")

# Keyed so the open tab survives reruns (e.g. pressing "Find it" keeps you on Find the limit)
tab_res, tab_case, tab_table, tab_goal, tab_guide = st.tabs(["Results", "Case questions", "Output table", "Find the limit", "Guide"],
                                                  key="tab", on_change="rerun")

with tab_res:
    if stale:
        st.info("You changed the inputs. The results below are still from the last run. Press **Run simulation** in the sidebar to update them.")
    st.markdown(f"**Showing:** {st.session_state.result_label}")
    k = st.columns(5)
    k[0].metric("Pre-op beds needed", r["need_hold"], help=f"Enough on {LEVEL} of simulated days", delta=f"{r['need_hold'] - r['avail']:+d} vs {r['avail']} free", delta_color="inverse")
    k[1].metric("Obs patients that fit all day", r["obs_fit"], f"{r['obs_fit'] - rp['obs']:+d} vs today's {rp['obs']}",
                help="Holding Room beds minus pre-op beds needed. Assumes Obs patients are in their beds while surgical patients "
                     "use pre-op, as the case's data slide treats the 14 Obs beds as unavailable. Obs patients are evening/overnight, "
                     "so once pre-op empties, every Holding Room bed is free for them.")
    k[2].metric("PACU beds needed", r["need_pacu"], help=f"Enough on {LEVEL} of simulated days", delta=f"{r['need_pacu'] - rp['pacu_beds']:+d} vs {rp['pacu_beds']} beds", delta_color="inverse")
    k[3].metric("Days PACU runs over", f"{r['over_pacu']:.0%}", help=f"Share of simulated days PACU needed more than its {rp['pacu_beds']} beds at some point.")
    k[4].metric("Last case out of the OR", clock(r["last_or_mean"]), f"{LEVEL} of days by {clock(r['last_or_p95'])}", delta_color="off")
    st.caption(f"{r['engine']} simulated {rp['reps']:,} days in {r['elapsed_s']:.2f} s · seed {rp['seed']} · pre-op empty after {clock(r['hold_empty_after'])}")

    # ---------- what this means, in plain words ----------
    def stage_line(name, need, have, have_label, over):
        if need <= have:
            return (f"**{name}:** the {have} {have_label} are enough on {LEVEL} of days (it needs {need}). "
                    f"It runs short on {over:.0%} of days.")
        return (f"**{name}:** needs **{need} beds** to be covered on {LEVEL} of days, **{need - have} more** than the "
                f"{have} {have_label}. With today's beds it runs short on {over:.0%} of days.")

    lines = [
        stage_line("Pre-op", r["need_hold"], r["avail"], "beds free after Obs patients", r["over_hold"]),
        (f"**Obs patients:** sized for pre-op, the Holding Room can keep **{r['obs_fit']}** Obs patients all day "
         f"(today: {rp['obs']}). Pre-op is empty after **{clock(r['hold_empty_after'])}** on {LEVEL} of days; after that "
         f"all {rp['hold_beds']} Holding Room beds are free for evening/overnight Obs patients."),
        stage_line("PACU", r["need_pacu"], rp["pacu_beds"], "PACU beds", r["over_pacu"]),
        (f"**OR day:** the last case leaves the OR around **{clock(r['last_or_mean'])}** on an average day, "
         f"and by {clock(r['last_or_p95'])} on {LEVEL} of days."),
    ]
    with st.container(border=True):
        st.markdown("##### What this means")
        st.markdown("\n".join(f"- {l}" for l in lines))

    # ---------- occupancy: how full the beds are on average ----------
    st.markdown("##### How full are the beds on average?")
    o = st.columns(4)
    occ_help = ("Average patients present ÷ beds, while the unit has patients (first arrival to last departure). "
                "Over 100% means more patients than beds on average.")
    o[0].metric(f"Pre-op · {r['avail']} free beds today", show(occ_now_h), help=occ_help)
    o[1].metric(f"Pre-op · {r['need_hold']} beds needed", show(occ_need_h), help=occ_help)
    o[2].metric(f"PACU · {rp['pacu_beds']} beds today", show(occ_now_p), help=occ_help)
    o[3].metric(f"PACU · {r['need_pacu']} beds needed", show(occ_need_p), help=occ_help)
    st.caption(f"Beds needed covers the **peak** on {LEVEL} of days; occupancy is the **average**. They pull in opposite "
               "directions: beds sized for busy days sit partly empty on an average day, and that spare room is what "
               "absorbs the peaks. A common rule of thumb is that average occupancy above about 85% means regular overflow, but bunched arrivals (like every OR finishing its first case at once) can cause overflow well below that.")

    # ---------- charts ----------
    times = [clock(sim_core.T0 + i * sim_core.BIN) for i in range(sim_core.NB)]
    HOUR_LABEL = ("(floor((240 + datum.value * 15) / 60) % 12 == 0 ? 12 : floor((240 + datum.value * 15) / 60) % 12)"
                  " + ((floor((240 + datum.value * 15) / 60) % 24) < 12 ? ' AM' : ' PM')")


    def busy_window(values, pad=2):
        """Interval range with patients present, padded 30 min and snapped to whole hours (4 intervals = 1 hour)."""
        busy = [i for i, v in enumerate(values) if v > 0]
        if not busy:
            return 0, sim_core.NB - 1
        lo = max(0, (busy[0] - pad) // 4 * 4)
        hi = min(sim_core.NB, -(-(busy[-1] + 1 + pad) // 4) * 4)
        return lo, hi


    c1, c2 = st.columns(2)
    # Two lines per stage: a typical day (median of the simulated days) and a busy day (the service-level percentile),
    # each worked out interval by interval. Each axis shows only the hours with patients (the grid covers 48 hours).
    SERIES = alt.Scale(domain=["Typical day (median)", f"Busy day ({LEVEL} of days at or below)"], range=["#8C8C8C", "#946E24"])
    for col, stage, cap, title, trim in ((c1, "hold", r["avail"], "Holding Room (pre-op)", True),
                                         (c2, "pacu", rp["pacu_beds"], "PACU", True)):
        typical, busy = r[f"p50_{stage}"], r[f"p95_{stage}"]
        lo, hi = busy_window(busy)
        wide = pd.DataFrame({"i": range(sim_core.NB), "time": times, "typical": typical, "busy": busy}).iloc[lo:hi + 1]
        long = wide.melt(id_vars=["i", "time"], value_vars=["typical", "busy"], var_name="k", value_name="beds")
        long["series"] = long["k"].map({"typical": SERIES.domain[0], "busy": SERIES.domain[1]})
        span = hi - lo
        step = 4 if span <= 40 else 8 if span <= 72 else 16 if span <= 112 else 24   # labels every 1, 2, 4 or 6 hours
        x = alt.X("i:Q", title="Time of day", scale=alt.Scale(domain=[lo, hi], nice=False),
                  axis=alt.Axis(values=list(range(lo, hi + 1, step)), labelExpr=HOUR_LABEL))
        band = alt.Chart(wide).mark_area(interpolate="step-after", opacity=.15, color="#946E24").encode(
            x=x, y=alt.Y("typical:Q", title="Beds occupied"), y2="busy:Q")
        lines = alt.Chart(long).mark_line(interpolate="step-after", strokeWidth=2.2).encode(
            x=x, y="beds:Q", color=alt.Color("series:N", scale=SERIES, legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["time", "series", "beds"])
        rule = alt.Chart(pd.DataFrame({"cap": [cap]})).mark_rule(color="#A52A24", strokeDash=[6, 4]).encode(y="cap:Q")
        col.subheader(title)
        window = f"Showing {clock(sim_core.T0 + lo * sim_core.BIN)} to {clock(sim_core.T0 + hi * sim_core.BIN)}, the hours with patients. "
        col.caption(window + f"Red dashed line: {'beds free after Obs patients' if stage == 'hold' else 'PACU beds'}. "
                    "A patient counts in every 15-minute interval they're in for any part of. Each interval is summarized "
                    "on its own, and the busiest moment falls at different times on different days, so the gold line's peak "
                    "can sit a bed or two below “beds needed”, which sizes each day's busiest moment.")
        col.altair_chart((band + lines + rule).properties(height=270), width="stretch")

    st.subheader("How many beds would be enough?")
    # Show the bed counts where the answer changes: from well below the need to a couple past it.
    b_lo = max(0, min(r["need_hold"], r["need_pacu"]) - 12)
    b_hi = min(len(r["curve_hold"]) - 1, max(r["need_hold"], r["need_pacu"], r["avail"], rp["pacu_beds"]) + 4)
    bed_range = list(range(b_lo, b_hi + 1))
    curve = pd.DataFrame({"beds": bed_range * 2,
                          "stage": ["Pre-op (surgical beds)"] * len(bed_range) + ["PACU"] * len(bed_range),
                          "days_over": [r["curve_hold"][b] for b in bed_range] + [r["curve_pacu"][b] for b in bed_range],
                          "occupancy": [sim_core.occupancy(r["avg_census_hold"], b) for b in bed_range]
                                       + [sim_core.occupancy(r["avg_census_pacu"], b) for b in bed_range]})
    ch = alt.Chart(curve).mark_line(point=True).encode(
        x=alt.X("beds:Q", title="Beds"), y=alt.Y("days_over:Q", title="Share of days over capacity", axis=alt.Axis(format="%")),
        color=alt.Color("stage:N", scale=alt.Scale(range=["#946E24", "#7FA3AA"])), tooltip=["stage", "beds", alt.Tooltip("days_over:Q", title="Days over capacity", format=".0%"),
                 alt.Tooltip("occupancy:Q", title="Average occupancy", format=".0%")])
    five = alt.Chart(pd.DataFrame({"y": [1 - rp["service_level"]]})).mark_rule(strokeDash=[5, 4], color="#5E5E5E").encode(y="y:Q")
    st.caption(f"Dashed line: {SHORT} of days over capacity, the {LEVEL} planning standard. "
               "The first bed count at or below it is “beds needed”. Hover a point to see the average occupancy at that bed count.")
    st.altair_chart((ch + five).properties(height=280), width="stretch")

    # ---------- pinned scenarios ----------
    if "pins" not in st.session_state:
        st.session_state.pins = []
    if st.button("Pin last run"):
        st.session_state.pins.append({"Scenario": st.session_state.result_label,
                                      "Pre-op beds needed": r["need_hold"], "Pre-op beds free": r["avail"], "Obs fit": r["obs_fit"],
                                      "PACU beds needed": r["need_pacu"], "PACU beds": rp["pacu_beds"], "Days PACU over": f"{r['over_pacu']:.0%}", "PACU occupancy today": show(occ_now_p),
                                      "Last case out": clock(r["last_or_mean"]), "Standard": f"{LEVEL} of days"})
    if st.session_state.pins:
        st.subheader("Pinned scenarios")
        st.dataframe(pd.DataFrame(st.session_state.pins), width="stretch", hide_index=True)

# ---------- case questions (slides 5 and 10), for the run on screen vs the other volume ----------
with tab_case:
    alt_cases = 4 if rp["cases"] != 4 else 8          # the case compares 88 vs 44 cases/day: 8 vs 4 cases per OR
    ra = run(tuple(sorted({**rp, "cases": alt_cases}.items())), _model_mtime)
    vol, vol_alt = rp["n_or"] * rp["cases"], rp["n_or"] * alt_cases

    def shortfalls(x):
        out = []
        if x["need_hold"] > x["avail"]:
            out.append("pre-op")
        if x["need_pacu"] > x["params"]["pacu_beds"]:
            out.append("PACU")
        return out

    def beds_cell(x):
        return f"Pre-op **{x['need_hold']}** vs {x['avail']} free · PACU **{x['need_pacu']}** vs {x['params']['pacu_beds']}"

    def obs_cell(x):
        return f"**{x['obs_fit']}** all day · all {x['params']['hold_beds']} beds free after {clock(x['hold_empty_after'])}"

    def load_cell(x):
        return (f"PACU over on **{x['over_pacu']:.0%}** of days, busy until {clock(x['last_pacu_p95'])} · "
                f"last case out ~**{clock(x['last_or_mean'])}**")

    def day_cell(x):
        return f"Last case out ~{clock(x['last_or_mean'])} · pre-op empty after {clock(x['hold_empty_after'])}"

    sh, sha = shortfalls(r), shortfalls(ra)
    if sh and sha:
        a1 = "**No.** " + ("Both stages fall short" if len(sh) == 2 and len(sha) == 2 else "Beds fall short") + " at either volume."
    elif sh:
        a1 = f"**No** at {vol} cases/day ({' and '.join(sh)}); enough at {vol_alt}."
    elif sha:
        a1 = f"**Yes** at {vol} cases/day; not at {vol_alt} ({' and '.join(sha)})."
    else:
        a1 = "**Yes** at either volume."
    lo, hi = sorted((r["obs_fit"], ra["obs_fit"]))
    a2 = (f"**{lo}{'' if lo == hi else f'–{hi}'}** Obs patients all day (today: {rp['obs']}). "
          "They're evening/overnight patients, so more fit once pre-op empties.")
    a3 = (f"**Yes, in {' and '.join(sh)}.** The ORs can do the cases; the beds around them can't keep up." if sh
          else "**No.** Pre-op and PACU have enough beds on most days.")
    d_beds = max(abs(r["need_hold"] - ra["need_hold"]), abs(r["need_pacu"] - ra["need_pacu"]))
    d_hours = abs(r["last_or_mean"] - ra["last_or_mean"]) / 60
    a4 = (("**Barely for beds" if d_beds <= 1 else f"**Beds change by up to {d_beds}") +
          f"; a lot for timing.** The OR day is about {d_hours:.0f} hours {'shorter' if alt_cases < rp['cases'] else 'longer'} at {vol_alt} cases/day."
          if d_hours >= 1 else
          ("**Barely.**" if d_beds <= 1 else f"**Beds change by up to {d_beds}.**"))

    st.markdown(f"Answers for the run on screen (**{st.session_state.result_label}**, {vol} cases/day), compared with the "
                f"same inputs at {vol_alt} cases/day ({alt_cases} per OR). Beds needed are enough on {LEVEL} of days.")
    if stale:
        st.info("You changed the inputs. These answers are still from the last run. Press **Run simulation** to update them.")
    st.markdown(f"""
| Case question (slides 5 and 10) | Answer | {vol} cases/day (this run) | {vol_alt} cases/day |
|---|---|---|---|
| 1. Do we have enough pre- and post-op beds for higher volume and shorter case lengths? | {a1} | {beds_cell(r)} | {beds_cell(ra)} |
| 2. How many 23-hr Obs patients can we continue to hold in pre-op? | {a2} | {obs_cell(r)} | {obs_cell(ra)} |
| 3. Is the expected increase in OR case volume going to overwhelm our capacity? | {a3} | {load_cell(r)} | {load_cell(ra)} |
| 4. Will the answers change at {vol_alt} instead of {vol} cases/day? | {a4} | {day_cell(r)} | {day_cell(ra)} |
""")
    why = ("Bed needs barely move with volume because the peak comes from every OR starting at the same time, which happens "
           "at either volume. Volume mainly changes how long the day runs. " if rp["waves"] == 1 else "")
    st.caption(why + f"Pre-op beds free = Holding Room beds − Obs patients. Times marked ~ are averages; “busy until” and "
               f"“empty after” are on {LEVEL} of days. A 1-bed difference between runs can be random noise.")

# ---------- output table: every metric, this run next to each what-if ----------
def metric_rows(x):
    """(section, metric, value) for one run, formatted for reading."""
    p = x["params"]
    occ = lambda c, b: show(sim_core.occupancy(c, b))
    return [
        ("Scenario", "Cases per day", f"{p['n_or'] * p['cases']} ({p['n_or']} ORs × {p['cases']})"),
        ("Scenario", "Start waves", f"{p['waves']}" + (f" ({p['wave_gap']} min apart)" if p["waves"] > 1 else "")),
        ("Scenario", "Early-arrival cushion (min)", f"{p['buf_min']}–{p['buf_max']}"),
        ("Pre-op", "Beds free for surgical patients", f"{x['avail']} ({p['hold_beds']} − {p['obs']} Obs)"),
        ("Pre-op", "Beds needed", x["need_hold"]),
        ("Pre-op", "Short by", max(0, x["need_hold"] - x["avail"])),
        ("Pre-op", "Busiest moment, average day", f"{x['mean_hold']:.1f}"),
        ("Pre-op", "Busiest moment, worst day", x["max_hold"]),
        ("Pre-op", "Days over capacity", f"{x['over_hold']:.0%}"),
        ("Pre-op", "Average occupancy of free beds", occ(x["avg_census_hold"], x["avail"])),
        ("Pre-op", "Obs patients that fit all day", f"{x['obs_fit']} (today {p['obs']})"),
        ("Pre-op", "Empty after", clock(x["hold_empty_after"])),
        ("OR", "Last case out, average day", clock(x["last_or_mean"])),
        ("OR", "Last case out, by (service level)", clock(x["last_or_p95"])),
        ("PACU", "Beds", p["pacu_beds"]),
        ("PACU", "Beds needed", x["need_pacu"]),
        ("PACU", "Short by", max(0, x["need_pacu"] - p["pacu_beds"])),
        ("PACU", "Busiest moment, average day", f"{x['mean_pacu']:.1f}"),
        ("PACU", "Busiest moment, worst day", x["max_pacu"]),
        ("PACU", "Days over capacity", f"{x['over_pacu']:.0%}"),
        ("PACU", "Average occupancy, current beds", occ(x["avg_census_pacu"], p["pacu_beds"])),
        ("PACU", "Average occupancy, beds needed", occ(x["avg_census_pacu"], x["need_pacu"])),
        ("PACU", "Last patient out, by (service level)", clock(x["last_pacu_p95"])),
    ]


with tab_table:
    run_keys = {k: rp[k] for k in RUN_KEYS}           # same days, seed and service level for every column
    cols = {}
    this = st.session_state.result_label
    is_preset = this in PRESETS and {k: rp[k] for k in SCENARIO_KEYS} == scenario_of(this)
    if not is_preset:                                  # a custom run gets its own first column
        cols[f"▶ This run ({this})"] = r
    for name in PRESETS:
        res = run(tuple(sorted({**BASELINE, **PRESETS[name], **run_keys}.items())), _model_mtime)
        cols[("▶ " if is_preset and name == this else "") + name] = res
    base = metric_rows(r)
    df = pd.DataFrame({"Area": [a for a, _, _ in base], "Metric": [m for _, m, _ in base]})
    for label, res in cols.items():
        df[label] = [str(v) for _, _, v in metric_rows(res)]
    st.markdown(f"Every metric in one place: the run on screen (marked ▶) next to each what-if preset. All columns use "
                f"the same {rp['reps']:,} simulated days, seed {rp['seed']} and service level ({LEVEL} of days).")
    if stale:
        st.info("You changed the inputs. This table is still from the last run. Press **Run simulation** to update it.")
    st.dataframe(df, width="stretch", hide_index=True, height=35 * (len(df) + 1) + 3,
                 column_config={"Area": st.column_config.TextColumn(width="small"),
                                "Metric": st.column_config.TextColumn(width="medium")})
    st.download_button("Download table (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="periop_output_table.csv", mime="text/csv")
    st.caption(f"Beds needed: enough beds on {LEVEL} of days, busiest moment included. Busiest moment: the most patients "
               "present at once that day. Days over capacity: share of days that moment exceeded the beds available. "
               "Average occupancy: average patients present ÷ beds, while the unit has patients. "
               "Times marked “by” hold on the service level's share of days.")

# ---------- find the limit (goal-seek) ----------
GOALS = {   # label: (input, values tried, "max" or "min", unit for the sentence)
    "Most cases per OR": ("cases", range(1, 21), "max", "cases per OR"),
    "Most ORs running": ("n_or", range(1, 41), "max", "ORs"),
    "Fewest start waves": ("waves", range(1, 7), "min", "start waves"),
}
SINGULAR = {"cases per OR": "case per OR", "ORs": "OR", "start waves": "start wave"}
unit_of = lambda n, unit: SINGULAR[unit] if n == 1 else unit
MUST = {"Pre-op and PACU beds": ("hold", "pacu"), "Pre-op beds only": ("hold",), "PACU beds only": ("pacu",)}


def use_best():
    key, best = st.session_state.goal["key"], st.session_state.goal["best"]
    st.session_state[f"in_{key}"] = best
    st.session_state.preset = CUSTOM


@st.cache_data(show_spinner=False, max_entries=32)
def limit(p_items, label, must, end_by, model_version):
    key, values, direction, _ = GOALS[label]
    return sim_core.find_limit(dict(p_items), key, list(values), direction, MUST[must], end_by)


with tab_goal:
    st.markdown("Pick what to solve for and the target to hit, then press **Find it**. The tool tries every value, "
                "holding the rest of the sidebar inputs fixed (beds, times, service level), and reports the limit.")
    st.caption("To change those inputs, edit the sidebar and press **Run simulation**: sidebar changes only take effect "
               "when you press it. The answer here then updates on its own.")
    with st.form("goal_form"):
        g1, g2 = st.columns(2)
        goal_label = g1.selectbox("Find", list(GOALS), key="goal_find")
        must_label = g2.selectbox("While fitting in", list(MUST), key="goal_must",
                                  help="Beds needed (at your service level) must be at or below the beds you have: "
                                       "pre-op beds free after Obs patients, and PACU beds.")
        end_on = st.checkbox("…and the last case is out of the OR by", key="goal_end_on", help=f"Checked on the same share of days as your service level.")
        end_t = st.time_input("Latest OR finish", dtime(19, 0), step=900, label_visibility="collapsed")
        go = st.form_submit_button("Find it", type="primary")
    if go:   # remember the question; the answer is recomputed below from the sidebar inputs in effect
        st.session_state.goal_spec = dict(label=goal_label, must=must_label,
                                          end_by=end_t.hour * 60 + end_t.minute if end_on else None)
    spec = st.session_state.get("goal_spec")
    if spec:
        key, values, direction, unit = GOALS[spec["label"]]
        with st.spinner(f"Trying {len(values)} settings…"):
            best, runs = limit(tuple(sorted(params.items())), spec["label"], spec["must"], spec["end_by"], _model_mtime)
        st.session_state.goal = dict(key=key, best=best, runs=runs, direction=direction, unit=unit, label=spec["label"],
                                     must=spec["must"], end_by=spec["end_by"], params=params)
        st.caption(f"Using the sidebar inputs in effect: {params['n_or']} ORs × {params['cases']} cases, "
                   f"{params['waves']} start wave{'s' if params['waves'] != 1 else ''}, "
                   f"{max(0, params['hold_beds'] - params['obs'])} free pre-op beds ({params['hold_beds']} − {params['obs']} Obs), "
                   f"{params['pacu_beds']} PACU beds, enough on {pct(params['service_level'])} of days, {params['reps']:,} simulated days "
                   f"(the value being solved for is varied).")
    g = st.session_state.get("goal")
    if g:
        gp, runs = g["params"], g["runs"]
        target = f"{gp['hold_beds'] - gp['obs']} free pre-op beds" if g["must"] == "Pre-op beds only" else \
                 f"{gp['pacu_beds']} PACU beds" if g["must"] == "PACU beds only" else \
                 f"{max(0, gp['hold_beds'] - gp['obs'])} free pre-op beds and {gp['pacu_beds']} PACU beds"
        when = f", with the last case out by {clock(g['end_by'])}" if g["end_by"] is not None else ""
        lvl = pct(gp["service_level"])
        if g["best"] is not None:
            st.success(f"**{g['best']} {unit_of(g['best'], g['unit'])}** is the {'most' if g['direction'] == 'max' else 'fewest'} that fits in "
                       f"{target}{when}, on {lvl} of days.")
            st.button(f"Use {g['best']} {unit_of(g['best'], g['unit'])} in the sidebar", on_click=use_best,
                      help="Copies this value into the sidebar (the what-if switches to Custom). Then press Run simulation.")
        else:
            # Say what stood in the way at the most favourable setting tried
            def shortfall(r):   # beds short (plus an hour-for-a-bed for running late) across the checked targets
                st_ = MUST[g["must"]]
                late = max(0, r["last_or_p95"] - g["end_by"]) / 60 if g["end_by"] is not None else 0
                return (max(0, r["need_hold"] - r["avail"]) if "hold" in st_ else 0) + \
                       (max(0, r["need_pacu"] - gp["pacu_beds"]) if "pacu" in st_ else 0) + late
            r0 = min((r for _, r in runs), key=shortfall)
            why = []
            if "hold" in MUST[g["must"]] and r0["need_hold"] > r0["avail"]:
                why.append(f"pre-op still needs {r0['need_hold']} beds (vs {r0['avail']} free)")
            if "pacu" in MUST[g["must"]] and r0["need_pacu"] > gp["pacu_beds"]:
                why.append(f"PACU still needs {r0['need_pacu']} beds (vs {gp['pacu_beds']})")
            if g["end_by"] is not None and r0["last_or_p95"] > g["end_by"]:
                why.append(f"the last case runs to {clock(r0['last_or_p95'])}")
            tried = f"{runs[0][0]}–{runs[-1][0]} {g['unit']}"
            st.warning(f"No setting from {tried} fits in {target}{when} on {lvl} of days. "
                       f"At the closest setting, {' and '.join(why) or 'the target is missed'}. "
                       "Try more beds, a lower service level, or a different lever.")
        tbl = pd.DataFrame([{g["unit"][0].upper() + g["unit"][1:]: v,
                             "Pre-op beds needed": r["need_hold"], "Pre-op beds free": r["avail"],
                             "PACU beds needed": r["need_pacu"], "PACU beds": gp["pacu_beds"],
                             f"Last case out ({lvl} of days)": clock(r["last_or_p95"]),
                             "Fits": "✓" if sim_core.fits(r, MUST[g["must"]], g["end_by"]) else ""} for v, r in runs])
        long = pd.concat([pd.DataFrame({"value": [v for v, _ in runs], "beds": [r["need_hold"] for _, r in runs], "stage": "Pre-op beds needed"}),
                          pd.DataFrame({"value": [v for v, _ in runs], "beds": [r["need_pacu"] for _, r in runs], "stage": "PACU beds needed"})])
        stages = MUST[g["must"]]
        long = long[long["stage"].isin([s_ for s_, k_ in (("Pre-op beds needed", "hold"), ("PACU beds needed", "pacu")) if k_ in stages])]
        colors = alt.Scale(domain=["Pre-op beds needed", "PACU beds needed"], range=["#946E24", "#7FA3AA"])
        lines = alt.Chart(long).mark_line(point=True).encode(
            x=alt.X("value:Q", title=g["unit"][0].upper() + g["unit"][1:], axis=alt.Axis(tickMinStep=1)),
            y=alt.Y("beds:Q", title="Beds needed"), color=alt.Color("stage:N", scale=colors, legend=alt.Legend(orient="bottom", title=None)),
            tooltip=[alt.Tooltip("value:Q", title=g["unit"]), "stage", "beds"])
        caps = pd.DataFrame([{"beds": max(0, gp["hold_beds"] - gp["obs"]), "stage": "Pre-op beds needed"},
                             {"beds": gp["pacu_beds"], "stage": "PACU beds needed"}])
        caps = caps[caps["stage"].isin(long["stage"].unique())]
        rules = alt.Chart(caps).mark_rule(strokeDash=[6, 4]).encode(y="beds:Q", color=alt.Color("stage:N", scale=colors, legend=None))
        layers = lines + rules
        if g["best"] is not None:
            layers += alt.Chart(pd.DataFrame({"value": [g["best"]]})).mark_rule(color="#1C1C1C", strokeWidth=1.5).encode(x="value:Q")
        st.altair_chart(layers.properties(height=300), width="stretch")
        st.caption("Dashed lines: beds you have. Solid black line: the answer. Each point is its own simulation, "
                   "so a line can wobble by a bed.")
        st.dataframe(tbl, width="stretch", hide_index=True)

# ---------- guide ----------
with tab_guide:
    st.markdown("""
#### The case

An 11-OR onsite site is being converted to a low-acuity surgical center, and offsite services are moving onsite. The ORs do about **2.5 cases per OR per day** today; the plan is **up to 88 cases a day** (8 per OR) with shorter cases. Patients flow **Holding Room (23 pre-op beds) → 11 ORs → PACU (12 recovery beds)**. Up to **14 of the 23 pre-op beds** hold evening/overnight 23-hour observation (Obs) patients, transferred in from PACU, which leaves 9 for surgical patients.

| Case question (slides 5 and 10) | Where the app answers it |
|---|---|
| 1. Do we have enough pre- and post-op beds for higher volume and shorter case lengths? | *Pre-op beds needed* and *PACU beds needed*, compared with the beds you have. |
| 2. How many 23-hr Obs patients can we continue to hold in pre-op? | *Obs patients that fit all day*, plus the time pre-op empties for evening Obs patients. |
| 3. Is the expected increase in OR case volume going to overwhelm our capacity? | *Days PACU runs over*, the time-of-day charts, and *Last case out of the OR*. |
| 4. Will the answers change at 44 instead of 88 cases a day? | The **Case questions** tab answers all four for your run and reruns it at the other volume. You can also pin both presets and compare. |

#### How to use the simulator

1. **Pick a starting point.** In the sidebar, *Start from a what-if* fills in a ready-made scenario: the case baseline (88 cases a day), 44 cases a day, staggered start waves, patients arriving early, or 18 PACU beds. Pick **Custom** to model your own environment; editing a preset and pressing Run also switches to Custom.
2. **Change the inputs.** Every box in the sidebar can be edited. Nothing changes on screen until you press **Run simulation**, and a blue note reminds you when the results are out of date.
3. **Read the Results tab.** Start with *What this means*, then the numbers and charts. The **Case questions** tab answers the four case questions for the same run, and the **Output table** tab puts every metric for this run and each what-if side by side (with a CSV download).
4. **Find a limit.** The **Find the limit** tab answers "how far can we push it?" questions, like the most cases per OR your beds can handle.
5. **Compare.** Press *Pin last run* after each scenario to line them up in one table. Keep the same random seed so differences come from your change, not from luck.

In **Find the limit**, the *Fits* column marks each setting that meets your target (✓) or misses it (blank). For "most" goals the answer is the last ✓ before the first blank; for "fewest start waves" it's the first ✓.

#### The inputs

| Input | What it means |
|---|---|
| Service level (% of days) | Your planning standard. At 95%, beds are sized to cover the busiest moment of the day on 95 of every 100 days; you accept running short on the other 5. |
| Cases per OR | Surgeries each OR does in a day, back to back. |
| Number of ORs | Operating rooms running that day. |
| First case in | When the first patient of the day enters the OR. |
| Start waves | Split the ORs into groups that start at different times. 1 = everyone starts together. Staggering spreads out the morning pre-op rush but makes the day end later. |
| Minutes between waves | Gap between one wave's start and the next. |
| OR turnover | Minutes to clean and set up the OR between cases. |
| Times (mean, sd) | How long each step takes, in minutes: the average and how much it varies day to day (standard deviation). |
| Holding Room beds / Obs patients | Total pre-op beds, and how many are taken by 23-hour observation patients. Surgical patients can only use the rest. |
| PACU beds | Recovery beds after surgery. |
| Early arrival cushion | Extra minutes patients arrive before pre-op has to start. 0 = just in time (the best case); real patients often come earlier. |
| Simulated days | How many random days to run. 1,000 (the default) gives steady answers; 100 matches the Excel log's size but can shift by a bed between seeds. |
| Random seed | Fixes the random draws so a run can be repeated exactly. |

#### The results

| Result | What it means |
|---|---|
| Beds needed | The fewest beds that cover the whole day, busiest moment included, on your service level's share of days. This sizes for the **peak**. |
| Obs patients that fit | Holding Room beds left over for Obs patients after setting aside the pre-op beds needed. |
| Days over | Share of simulated days a unit needed more beds than it has at some point in the day (for pre-op, more than the beds free after Obs patients). |
| Average occupancy | Average share of beds filled while the unit has patients. This measures the **average**, not the peak. |
| Typical day / busy day | On the time-of-day charts, for each 15-minute interval: the median across simulated days (grey) and your service level's percentile (gold). A patient counts in every interval they're in for any part of. |
| Last case out | When the last OR case of the day ends, on an average day and on your service level's share of days. |

#### Service level vs occupancy

They answer different questions. **Service level** asks "is there a bed at the busiest moment, on most days?" **Occupancy** asks "how full are the beds on average?" Because demand swings from day to day, beds sized to cover busy days sit partly empty on an average day. In the case baseline, 18 PACU beds cover 95% of days at about 51% average occupancy. Today's 12 beds are about 77% full on average, which looks comfortable, yet PACU runs short on 999 of 1,000 simulated days, because the patients arrive in bunches. That's why the tool sizes beds on the peak and shows occupancy alongside it.

#### What the model assumes

From the case (slides 8 and 9): times are normally distributed (pre-op 60 ± 30, OR 60 ± 20, PACU 90 ± 40 minutes); first cases enter the OR at exactly 7:30 AM; 8 or 4 cases per OR; cases are scheduled in advance in their assigned OR; 30-minute turnover; staffing is not a constraint; no transport time.

Added by the model:

- **The OR is the bottleneck** (the slide 6 hint: Goldratt's *The Goal*), so the model is kept simple, without block schedules, booking patterns or shifts. Patients are brought into pre-op so it ends just as their OR is ready. Each case starts when the previous one ends plus turnover.
- **Random times** are drawn as in the Excel template, ABS(INT(NORM.INV(RAND(), mean, sd))): rounded down to whole minutes, with the rare negative draw flipped to positive.
- **Obs patients** are assumed to be in their Holding Room beds while surgical patients use pre-op, as slide 8 treats the 14 Obs beds as unavailable. Moving patients from PACU to Obs beds isn't modeled; every PACU patient simply leaves.
- **PACU blocking isn't modeled.** The model counts the beds needed. In real life, when PACU is full, patients wait in the OR and later cases start late.
- **Early arrival** is 0 by default (just in time, the best case), because the slides don't give it.
""")

# ---------- the Python behind the results shown ----------
NOTES = {"n_or": "operating rooms", "cases": "cases per OR per day", "first": "first case in, minutes after midnight",
         "waves": "start waves (1 = all ORs start together)", "wave_gap": "minutes between waves",
         "turnover": "OR turnover, minutes", "pre_m": "pre-op mean, minutes", "pre_s": "pre-op sd",
         "or_m": "OR mean, minutes", "or_s": "OR sd", "pacu_m": "PACU mean, minutes", "pacu_s": "PACU sd",
         "hold_beds": "Holding Room beds", "obs": "Obs patients in them", "pacu_beds": "PACU beds",
         "buf_min": "early-arrival cushion min, minutes", "buf_max": "early-arrival cushion max, minutes",
         "reps": "simulated days", "seed": "random seed", "service_level": "size beds to be enough on this share of days"}


def run_script(p, res):
    """A runnable script with the exact inputs behind the results on screen, and the answers it should print."""
    rows = []
    for k in sim_core.DEFAULTS:
        v = p[k]
        note = NOTES[k] + (f" (case baseline: {sim_core.DEFAULTS[k]})" if v != sim_core.DEFAULTS[k] else "")
        if k == "first":
            note += f" = {clock(v)}"
        rows.append(f"    {k!r}: {v!r},".ljust(32) + f"# {note}")
    engine = "numpy" if res["engine"] == "NumPy" else "python"
    lvl = pct(p["service_level"])
    return "\n".join([
        f"# {st.session_state.result_label}: the exact run shown in the app.",
        "# Put this file next to sim_core.py and run:  python run_scenario.py",
        "import sim_core", "", "params = {", *rows, "}", "",
        f'r = sim_core.simulate(params, engine="{engine}")', "",
        f'print("Pre-op beds needed:", r["need_hold"])          # app shows {res["need_hold"]} (enough on {lvl} of days)',
        f'print("Obs patients that fit:", r["obs_fit"])         # app shows {res["obs_fit"]}',
        f'print("PACU beds needed:", r["need_pacu"])            # app shows {res["need_pacu"]}',
        f'print("Days PACU runs over:", f"{{r[\'over_pacu\']:.0%}}")   # app shows {res["over_pacu"]:.0%}',
    ]) + "\n"


with st.expander("View the Python behind these results"):
    script = run_script(rp, r)
    st.markdown("**The exact run shown above.** These are the inputs the results on screen were run with "
                f"({st.session_state.result_label}, {rp['reps']:,} days, seed {rp['seed']}). "
                "Running it with `sim_core.py` gives the same answers. Inputs that differ from the case baseline are marked.")
    if stale:
        st.caption("You've changed inputs since that run. Press Run simulation to update the results and this code.")
    st.code(script, language="python")
    st.download_button("Download run_scenario.py", script, file_name="run_scenario.py", mime="text/x-python")
    st.markdown("**The model (sim_core.py).** The same file the app runs. Its `DEFAULTS` are the case baseline.")
    st.code(open(sim_core.__file__).read(), language="python")
st.caption("Limits: PACU blocking isn't modeled (when PACU is full, real patients wait in the OR). Staffing and transport time are excluded, per the case.")
