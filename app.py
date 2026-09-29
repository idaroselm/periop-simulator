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
        reps = st.select_slider("Simulated days", [100, 500, 1000, 2000], value=1000)
        seed = st.number_input("Random seed", value=6473, step=1)
    submitted = st.form_submit_button("Run simulation", type="primary", width="stretch")

params = dict(cases=cases, n_or=int(n_or), first=first_t.hour * 60 + first_t.minute, waves=int(waves), wave_gap=int(wave_gap),
              turnover=int(turnover), pre_m=pre_m, pre_s=pre_s, or_m=or_m, or_s=or_s, pacu_m=pacu_m, pacu_s=pacu_s,
              hold_beds=int(hold_beds), obs=int(obs), pacu_beds=int(pacu_beds), buf_min=int(buf_min),
              buf_max=max(int(buf_min), int(buf_max)), reps=int(reps), seed=int(seed))


@st.cache_data(show_spinner="Simulating…", max_entries=64)
def run(p_items):
    return sim_core.simulate(dict(p_items))


# Results only change when "Run simulation" is pressed; the first visit shows the case baseline.
BASELINE = {**sim_core.DEFAULTS, "wave_gap": 45}
if "result" not in st.session_state:
    st.session_state.result, st.session_state.result_label = run(tuple(sorted(BASELINE.items()))), "Case baseline · 88/day"
if submitted:
    matches_preset = params == {**BASELINE, **PRESETS[preset], "reps": params["reps"], "seed": params["seed"]}
    st.session_state.result = run(tuple(sorted(params.items())))
    st.session_state.result_label = preset if matches_preset else "Custom scenario"
r = st.session_state.result
rp = r["params"]                     # the inputs the shown results were run with
stale = {k: rp[k] for k in params} != params

# ---------- header + KPIs ----------
st.caption("MGT 6473 · Final project · What-if lab")
st.title("Periop Patient Flow and Capacity Planning Simulator")
st.write("Holding Room (pre-op) → ORs → PACU, with the same logic as the Excel workbook. "
         "“Beds needed” means enough beds on 95% of simulated days.")

with st.expander("How to use the simulator", expanded=first_visit):
    st.markdown("""
**1. Pick a starting point.** Choose a what-if under *Start from a what-if* in the sidebar
(case baseline, 44 cases/day, staggered start waves, early arrival, or 18 PACU beds). This fills in the inputs.

**2. Adjust the inputs.** Change anything in the sidebar:
- *Schedule*: cases per OR, number of ORs, first-case time, start waves and the minutes between them, OR turnover.
- *Times*: mean and standard deviation (minutes) for pre-op, OR and PACU.
- *Beds*: Holding Room beds, how many hold Obs patients, and PACU beds.
- *Early arrival*: extra minutes patients arrive before pre-op must start (0–0 = just in time, the best case).
- *Simulation*: number of simulated days and the random seed.

**3. Press Run simulation.** Nothing changes until you do. A blue note reminds you when the inputs differ from the results shown.

**4. Read the results.**
- *Pre-op beds needed* and *PACU beds needed*: beds that are enough on 95% of simulated days, compared with the beds available.
- *Obs patients that fit all day*: Holding Room beds left after surgical patients (23 − pre-op beds needed).
- *Days PACU runs over*: share of simulated days PACU would need more beds than it has.
- *Last case out of the OR*: when the latest OR finishes, on average and on 95% of days.
- *Charts*: beds in use by time of day (red dashed line = capacity), and how often each stage runs over for any number of beds (aim for the 5% line).

**5. Compare scenarios.** Press *Pin last run*, change the inputs, run again, and pin that too. The table lines them up.
Keep the same seed when comparing so differences come from your change, not from luck.

**Tips.** Try a different random seed to check how stable a result is: answers can shift by about 1 bed between seeds.
More simulated days give steadier answers. The model counts beds needed; it doesn't make patients wait when PACU is full.
""")

if stale:
    st.info("You changed the inputs. The results below are still from the last run. Press **Run simulation** in the sidebar to update them.")
st.markdown(f"**Showing:** {st.session_state.result_label}")
k = st.columns(5)
k[0].metric("Pre-op beds needed", r["need_hold"], f"{r['need_hold'] - r['avail']:+d} vs {r['avail']} free", delta_color="inverse")
k[1].metric("Obs patients that fit all day", r["obs_fit"], f"{r['obs_fit'] - rp['obs']:+d} vs today's {rp['obs']}")
k[2].metric("PACU beds needed", r["need_pacu"], f"{r['need_pacu'] - rp['pacu_beds']:+d} vs {rp['pacu_beds']} beds", delta_color="inverse")
k[3].metric("Days PACU runs over", f"{r['over_pacu']:.0%}")
k[4].metric("Last case out of the OR", clock(r["last_or_mean"]), f"95% of days by {clock(r['last_or_p95'])}", delta_color="off")
st.caption(f"{r['engine']} simulated {rp['reps']:,} days in {r['elapsed_s']:.2f} s · seed {rp['seed']} · pre-op empty after {clock(r['hold_empty_after'])}")

# ---------- charts ----------
times = [clock(sim_core.T0 + i * sim_core.BIN) for i in range(sim_core.NB)]
c1, c2 = st.columns(2)
for col, key, cap, title in ((c1, "p95_hold", r["avail"], "Holding Room (pre-op)"), (c2, "p95_pacu", rp["pacu_beds"], "PACU")):
    df = pd.DataFrame({"i": range(sim_core.NB), "time": times, "beds": r[key]})
    base = alt.Chart(df).encode(x=alt.X("i:Q", title="Time of day (from 4 AM)",
                                        axis=alt.Axis(values=list(range(0, 97, 16)),
                                                      labelExpr="['4 AM','8 AM','12 PM','4 PM','8 PM','12 AM','4 AM'][datum.value/16]")))
    area = base.mark_area(interpolate="step-after", opacity=.25, color="#946E24").encode(y=alt.Y("beds:Q", title="Beds occupied (95th pct)"))
    line = base.mark_line(interpolate="step-after", color="#946E24").encode(y="beds:Q", tooltip=["time", "beds"])
    rule = alt.Chart(pd.DataFrame({"cap": [cap]})).mark_rule(color="#A52A24", strokeDash=[6, 4]).encode(y="cap:Q")
    col.subheader(title)
    col.altair_chart((area + line + rule).properties(height=260), width="stretch")

st.subheader("How many beds would be enough?")
curve = pd.DataFrame({"beds": list(range(4, 27)) * 2,
                      "stage": ["Pre-op (surgical beds)"] * 23 + ["PACU"] * 23,
                      "days_over": [r["curve_hold"][b] for b in range(4, 27)] + [r["curve_pacu"][b] for b in range(4, 27)]})
ch = alt.Chart(curve).mark_line(point=True).encode(
    x=alt.X("beds:Q", title="Beds"), y=alt.Y("days_over:Q", title="Share of days over capacity", axis=alt.Axis(format="%")),
    color=alt.Color("stage:N", scale=alt.Scale(range=["#946E24", "#7FA3AA"])), tooltip=["stage", "beds", alt.Tooltip("days_over:Q", format=".0%")])
five = alt.Chart(pd.DataFrame({"y": [0.05]})).mark_rule(strokeDash=[5, 4], color="#5E5E5E").encode(y="y:Q")
st.altair_chart((ch + five).properties(height=280), width="stretch")

# ---------- pinned scenarios ----------
if "pins" not in st.session_state:
    st.session_state.pins = []
if st.button("Pin last run"):
    st.session_state.pins.append({"Scenario": st.session_state.result_label,
                                  "Pre-op beds needed": r["need_hold"], "Pre-op beds free": r["avail"], "Obs fit": r["obs_fit"],
                                  "PACU beds needed": r["need_pacu"], "PACU beds": rp["pacu_beds"], "Days PACU over": f"{r['over_pacu']:.0%}",
                                  "Last case out": clock(r["last_or_mean"])})
if st.session_state.pins:
    st.subheader("Pinned scenarios")
    st.dataframe(pd.DataFrame(st.session_state.pins), width="stretch", hide_index=True)

with st.expander("View the Python model"):
    st.code(open(sim_core.__file__).read(), language="python")
st.caption("Limits: PACU blocking isn't modeled (when PACU is full, real patients wait in the OR). Staffing and transport time are excluded, per the case.")
