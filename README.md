# Periop Patient Flow and Capacity Planning Simulator

MGT 6473 Healthcare Operations Management · Final project

A discrete event simulation of patient flow through **Holding Room (pre-op) → 11 ORs → PACU**.
Set the schedule, service times and bed counts, press **Run simulation**, and the app simulates
1,000 days to show how many pre-op and PACU beds are needed (enough on 95% of days),
how many 23-hr Obs patients the Holding Room can still hold, and how long the OR day runs.

## Run it

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

- All 11 ORs start at 7:30 AM; 8 cases per OR (88/day) or 4 (44/day); 30-minute turnover.
- Pre-op ~ Normal(60, 30), OR ~ Normal(60, 20), PACU ~ Normal(90, 40) minutes.
- 23 Holding Room beds (14 used by Obs patients), 12 PACU beds.
- Patients are pulled into pre-op so it ends when their OR is ready (the OR is the bottleneck); an optional early-arrival cushion can be added.
- PACU blocking isn't modeled: the model counts beds needed. Staffing and transport time are excluded.

## Validation

The model reproduces the Excel workbook exactly on 50 identical simulated days, matches an independent
minute-by-minute model, gives hand-calculated answers when variation is removed, and agrees with Little's Law.
