# Periop Patient Flow and Capacity Planning Simulator

MGT 6473 Healthcare Operations Management · Final project

A discrete event simulation of patient flow through **Holding Room (pre-op) → 11 ORs → PACU**.
Set the schedule, service times and bed counts, press **Run simulation**, and the app simulates
1,000 days by default (a steady answer; pick 100 to mirror the Excel workbook's log, or up to 2,000) to show how many pre-op and PACU beds are needed (enough on 95% of days),
how many 23-hr Obs patients the Holding Room can still hold, and how long the OR day runs.

**Live app:** https://periop-simulator-auf2ujawu9nvnr95rzxohm.streamlit.app/

## What's in the app

- **Presets, in presentation order:** 1 Today (2.5 cases/OR) · 2 Proposed 88/day (the app opens here) · 3 44/day · 4 stagger starts · 5 18 PACU beds · 6 ★ Recommended · 7 add 13 beds.
- **Case questions:** the four case questions (slides 5 and 10) answered for the run on screen, side by side with the same inputs at the other volume (88 vs 44 cases/day).
- **Output table:** every metric (beds needed, shortfall, busiest moment, days over capacity, occupancy, Obs that fit, end-of-day times) for the run on screen next to each what-if preset, with a CSV download.
- **Results:** beds needed at your service level (any level from 50% to 99.5%), a plain-language "What this means" summary, average bed occupancy, time-of-day charts and a bed sizing curve.
- **Find the limit:** goal-seek the most cases per OR, the most ORs, or the fewest start waves that fit your beds (and, optionally, a latest OR finish time).
- **View the Python behind these results:** the exact inputs of the run on screen as a runnable script that reproduces its answers, plus the model code.
- **Guide:** what every input and result means, and how service level differs from occupancy.

## Run it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Files

| File | What it is |
|---|---|
| `app.py` | The Streamlit dashboard |
| `sim_core.py` | The simulation model (NumPy engine + pure-Python engine, same rules as the Excel workbook) |
| `requirements.txt` | Packages the app needs |
| `tests/` | Validation tests (`pip install pytest`, then `pytest -q`) |

## Model assumptions

The case setup is below (the app opens on the proposed 88 cases/day). Pick **Custom** in the what-if list to model any environment:
up to 40 ORs, 20 cases per OR, 6 start waves and 200 beds. Long days are tracked 48 hours from 4:00 AM.

- Today: about 2.5 cases per OR (~28/day, slide 4). Proposed: 8 cases per OR (88/day), or 4 (44/day). Half steps are spread across ORs (2.5 = 6 ORs doing 3 cases, 5 doing 2).
- All 11 ORs start at 7:30 AM; 30-minute turnover.
- Pre-op ~ Normal(60, 30), OR ~ Normal(60, 20), PACU ~ Normal(90, 40) minutes.
- 23 Holding Room beds (14 used by Obs patients), 12 PACU beds.
- Patients are pulled into pre-op so it ends when their OR is ready (the OR is the bottleneck); an optional early-arrival cushion can be added.
- Obs patients are assumed to be in their Holding Room beds while surgical patients use pre-op (slide 8 treats the 14 Obs beds as unavailable). Obs patients are evening/overnight, so the app also shows when pre-op empties and all 23 beds free up. PACU-to-Obs transfers aren't modeled.
- Times are drawn as in the Excel template: ABS(INT(NORM.INV(RAND(), mean, sd))).
- PACU blocking isn't modeled: the model counts beds needed. Staffing and transport time are excluded.

## Validation

The model reproduces the Excel workbook exactly on 50 identical simulated days, matches an independent
minute-by-minute model, gives hand-calculated answers when variation is removed, and agrees with Little's Law.
