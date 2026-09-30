"""Periop Patient Flow and Capacity Planning Simulator (Streamlit).  Run:  streamlit run app.py"""
from datetime import time as dtime

import altair as alt
import pandas as pd
import streamlit as st

import sim_core

st.set_page_config(page_title="Periop Patient Flow and Capacity Planning Simulator", layout="wide")
first_visit = "seen" not in st.session_state   # open the how-to on a visitor's first load
st.session_state.seen = True

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
    m = int(round(m)) % 1440
    h, mi = divmod(m, 60)
    return f"{(h % 12) or 12}:{mi:02d} {'AM' if h < 12 else 'PM'}"


# ---------- inputs ----------
st.sidebar.title("Inputs")
preset = st.sidebar.selectbox("Start from a what-if", list(PRESETS))
d = {**sim_core.DEFAULTS, "wave_gap": 45, **PRESETS[preset]}

# Inputs sit in a form: changing a box no longer re-runs the app; press "Run simulation" to apply all changes at once.
with st.sidebar.form("inputs"):
    service_level = st.radio("Size beds to be enough on", [0.90, 0.95, 0.99], index=[0.90, 0.95, 0.99].index(d["service_level"]),
                             format_func=lambda x: f"{x:.0%} of days", horizontal=True,
                             help="The planning standard. 95% means the beds cover the whole day, busiest moment included, on 95 of 100 simulated days.")
    with st.expander("Schedule", expanded=True):
        cases = st.slider("Cases per OR per day", 1, 8, d["cases"], key=f"cases_{preset}")
        n_or = st.number_input("Number of ORs", 1, 11, d["n_or"])
        first_t = st.time_input("First case in", dtime(7, 30))
        waves = st.selectbox("Start waves", [1, 2, 3], index=d["waves"] - 1, key=f"waves_{preset}")
        wave_gap = st.number_input("Minutes between waves", 0, 120, d["wave_gap"], step=15)
        turnover = st.number_input("OR turnover (min)", 0, 120, d["turnover"])
    with st.expander("Times · normal (mean, sd), minutes"):
        c1, c2 = st.columns(2)
        pre_m = c1.number_input("Pre-op mean", 0, 600, d["pre_m"]); pre_s = c2.number_input("Pre-op sd", 0, 300, d["pre_s"])
        or_m = c1.number_input("OR mean", 0, 600, d["or_m"]); or_s = c2.number_input("OR sd", 0, 300, d["or_s"])
        pacu_m = c1.number_input("PACU mean", 0, 600, d["pacu_m"]); pacu_s = c2.number_input("PACU sd", 0, 300, d["pacu_s"])
    with st.expander("Beds", expanded=True):
        hold_beds = st.number_input("Holding Room beds", 0, 60, d["hold_beds"])
        obs = st.number_input("Obs patients in them", 0, 60, d["obs"])
        pacu_beds = st.number_input("PACU beds", 0, 40, d["pacu_beds"], key=f"pacu_{preset}")
    with st.expander("Early arrival before pre-op (minutes)", expanded=True):
        buf_min = st.number_input("Cushion min", 0, 120, d["buf_min"], key=f"bmin_{preset}")
        buf_max = st.number_input("Cushion max", 0, 120, d["buf_max"], key=f"bmax_{preset}")
    with st.expander("Simulation"):
        reps = st.select_slider("Simulated days", [100, 500, 1000, 2000], value=100)
        seed = st.number_input("Random seed", value=6473, step=1)
    submitted = st.form_submit_button("Run simulation", type="primary", width="stretch")

params = dict(cases=cases, n_or=int(n_or), first=first_t.hour * 60 + first_t.minute, waves=int(waves), wave_gap=int(wave_gap),
              turnover=int(turnover), pre_m=pre_m, pre_s=pre_s, or_m=or_m, or_s=or_s, pacu_m=pacu_m, pacu_s=pacu_s,
              hold_beds=int(hold_beds), obs=int(obs), pacu_beds=int(pacu_beds), buf_min=int(buf_min),
              buf_max=max(int(buf_min), int(buf_max)), reps=int(reps), seed=int(seed), service_level=float(service_level))


@st.cache_data(show_spinner="Simulating…", max_entries=64)
def run(p_items):
    return sim_core.simulate(dict(p_items))


# Results only change when "Run simulation" is pressed; the first visit shows the case baseline.
BASELINE = {**sim_core.DEFAULTS, "wave_gap": 45}
if "result" not in st.session_state:
    st.session_state.result, st.session_state.result_label = run(tuple(sorted(BASELINE.items()))), "Case baseline · 88/day"
if submitted:
    matches_preset = params == {**BASELINE, **PRESETS[preset], "reps": params["reps"], "seed": params["seed"],
                                "service_level": params["service_level"]}
    st.session_state.result = run(tuple(sorted(params.items())))
    st.session_state.result_label = preset if matches_preset else "Custom scenario"
r = st.session_state.result
rp = r["params"]                     # the inputs the shown results were run with
stale = {k: rp[k] for k in params} != params
LEVEL = f"{rp['service_level']:.0%}"   # e.g. "95%"

# ---------- header + KPIs ----------
st.caption("MGT 6473 · Final project · What-if lab")
st.title("Periop Patient Flow and Capacity Planning Simulator")
st.write("Holding Room (pre-op) → ORs → PACU, with the same logic as the Excel workbook. "
         f"“Beds needed” means enough beds on {LEVEL} of simulated days (change this at the top of the sidebar).")

with st.expander("How to use the simulator", expanded=first_visit):
    st.markdown("""
**1. Pick a starting point.** Choose a what-if under *Start from a what-if* in the sidebar
(case baseline, 44 cases/day, staggered start waves, early arrival, or 18 PACU beds). This fills in the inputs.

**2. Adjust the inputs.** Change anything in the sidebar:
- *Schedule*: cases per OR, number of ORs, first-case time, start waves and the minutes between them, OR turnover.
- *Times*: mean and standard deviation (minutes) for pre-op, OR and PACU.
- *Beds*: Holding Room beds, how many hold Obs patients, and PACU beds.
- *Early arrival*: extra minutes patients arrive before pre-op must start (0–0 = just in time, the best case).
- *Size beds to be enough on*: the planning standard, 90%, 95% (default) or 99% of simulated days.
- *Simulation*: number of simulated days and the random seed.

**3. Press Run simulation.** Nothing changes until you do. A blue note reminds you when the inputs differ from the results shown.

**4. Read the results.**
- *Pre-op beds needed* and *PACU beds needed*: beds that are enough on the chosen share of simulated days (95% by default), compared with the beds available.
- *Obs patients that fit all day*: Holding Room beds left after surgical patients (23 − pre-op beds needed).
- *Days PACU runs over*: share of simulated days PACU would need more beds than it has.
- *Last case out of the OR*: when the latest OR finishes, on average and on the chosen share of days.
- *Beds in use by time of day*: a typical day (the median, grey) and a busy day (the chosen percentile, gold), with capacity as a red dashed line.
- *How many beds would be enough?*: how often each stage runs over for any number of beds; aim for the dashed line (5% of days at the 95% standard).

**5. Compare scenarios.** Press *Pin last run*, change the inputs, run again, and pin that too. The table lines them up.
Keep the same seed when comparing so differences come from your change, not from luck.

**Tips.** Try a different random seed to check how stable a result is: answers can shift by about 1 bed between seeds.
More simulated days give steadier answers. The model counts beds needed; it doesn't make patients wait when PACU is full.
""")

if stale:
    st.info("You changed the inputs. The results below are still from the last run. Press **Run simulation** in the sidebar to update them.")
st.markdown(f"**Showing:** {st.session_state.result_label}")
k = st.columns(5)
k[0].metric("Pre-op beds needed", r["need_hold"], help=f"Enough on {LEVEL} of simulated days", delta=f"{r['need_hold'] - r['avail']:+d} vs {r['avail']} free", delta_color="inverse")
k[1].metric("Obs patients that fit all day", r["obs_fit"], f"{r['obs_fit'] - rp['obs']:+d} vs today's {rp['obs']}")
k[2].metric("PACU beds needed", r["need_pacu"], help=f"Enough on {LEVEL} of simulated days", delta=f"{r['need_pacu'] - rp['pacu_beds']:+d} vs {rp['pacu_beds']} beds", delta_color="inverse")
k[3].metric("Days PACU runs over", f"{r['over_pacu']:.0%}")
k[4].metric("Last case out of the OR", clock(r["last_or_mean"]), f"{LEVEL} of days by {clock(r['last_or_p95'])}", delta_color="off")
st.caption(f"{r['engine']} simulated {rp['reps']:,} days in {r['elapsed_s']:.2f} s · seed {rp['seed']} · pre-op empty after {clock(r['hold_empty_after'])}")

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
# each worked out interval by interval. Pre-op's axis shows only the hours with patients; PACU keeps the full 24 hours.
SERIES = alt.Scale(domain=["Typical day (median)", f"Busy day ({LEVEL} of days at or below)"], range=["#8C8C8C", "#946E24"])
for col, stage, cap, title, trim in ((c1, "hold", r["avail"], "Holding Room (pre-op)", True),
                                     (c2, "pacu", rp["pacu_beds"], "PACU", False)):
    typical, busy = r[f"p50_{stage}"], r[f"p95_{stage}"]
    lo, hi = busy_window(busy) if trim else (0, sim_core.NB)
    wide = pd.DataFrame({"i": range(sim_core.NB), "time": times, "typical": typical, "busy": busy}).iloc[lo:hi + 1]
    long = wide.melt(id_vars=["i", "time"], value_vars=["typical", "busy"], var_name="k", value_name="beds")
    long["series"] = long["k"].map({"typical": SERIES.domain[0], "busy": SERIES.domain[1]})
    span = hi - lo
    step = 4 if span <= 40 else 8 if span <= 72 else 16   # labels every 1, 2 or 4 hours depending on the span
    x = alt.X("i:Q", title="Time of day", scale=alt.Scale(domain=[lo, hi], nice=False),
              axis=alt.Axis(values=list(range(lo, hi + 1, step)), labelExpr=HOUR_LABEL))
    band = alt.Chart(wide).mark_area(interpolate="step-after", opacity=.15, color="#946E24").encode(
        x=x, y=alt.Y("typical:Q", title="Beds occupied"), y2="busy:Q")
    lines = alt.Chart(long).mark_line(interpolate="step-after", strokeWidth=2.2).encode(
        x=x, y="beds:Q", color=alt.Color("series:N", scale=SERIES, legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["time", "series", "beds"])
    rule = alt.Chart(pd.DataFrame({"cap": [cap]})).mark_rule(color="#A52A24", strokeDash=[6, 4]).encode(y="cap:Q")
    col.subheader(title)
    window = f"Showing {clock(sim_core.T0 + lo * sim_core.BIN)} to {clock(sim_core.T0 + hi * sim_core.BIN)}, the hours with pre-op patients. " if trim else ""
    col.caption(window + f"Red dashed line: {'beds free after Obs patients' if trim else 'PACU beds'}. "
                "Each 15-minute interval is summarized on its own, so the gold line's peak can sit a bed below "
                "“beds needed”, which sizes the whole day.")
    col.altair_chart((band + lines + rule).properties(height=270), width="stretch")

st.subheader("How many beds would be enough?")
curve = pd.DataFrame({"beds": list(range(4, 27)) * 2,
                      "stage": ["Pre-op (surgical beds)"] * 23 + ["PACU"] * 23,
                      "days_over": [r["curve_hold"][b] for b in range(4, 27)] + [r["curve_pacu"][b] for b in range(4, 27)]})
ch = alt.Chart(curve).mark_line(point=True).encode(
    x=alt.X("beds:Q", title="Beds"), y=alt.Y("days_over:Q", title="Share of days over capacity", axis=alt.Axis(format="%")),
    color=alt.Color("stage:N", scale=alt.Scale(range=["#946E24", "#7FA3AA"])), tooltip=["stage", "beds", alt.Tooltip("days_over:Q", format=".0%")])
five = alt.Chart(pd.DataFrame({"y": [1 - rp["service_level"]]})).mark_rule(strokeDash=[5, 4], color="#5E5E5E").encode(y="y:Q")
st.caption(f"Dashed line: {1 - rp['service_level']:.0%} of days over capacity, the {LEVEL} planning standard. "
           "The first bed count at or below it is “beds needed”.")
st.altair_chart((ch + five).properties(height=280), width="stretch")

# ---------- pinned scenarios ----------
if "pins" not in st.session_state:
    st.session_state.pins = []
if st.button("Pin last run"):
    st.session_state.pins.append({"Scenario": st.session_state.result_label,
                                  "Pre-op beds needed": r["need_hold"], "Pre-op beds free": r["avail"], "Obs fit": r["obs_fit"],
                                  "PACU beds needed": r["need_pacu"], "PACU beds": rp["pacu_beds"], "Days PACU over": f"{r['over_pacu']:.0%}",
                                  "Last case out": clock(r["last_or_mean"]), "Standard": f"{LEVEL} of days"})
if st.session_state.pins:
    st.subheader("Pinned scenarios")
    st.dataframe(pd.DataFrame(st.session_state.pins), width="stretch", hide_index=True)

with st.expander("View the Python model"):
    st.code(open(sim_core.__file__).read(), language="python")
st.caption("Limits: PACU blocking isn't modeled (when PACU is full, real patients wait in the OR). Staffing and transport time are excluded, per the case.")
