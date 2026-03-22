# Claude Code Prompt — Sleep Environment Optimiser

Paste everything below this line into Claude Code after running `claude` in the project folder.

---

I am building a Streamlit dashboard for a university IoT project called **Smart Sleep Environment Optimiser**. I have provided you with a head start — the project folder already contains scaffold code written in a prior session. Your job is to **review the existing files, fix any issues, and build incrementally milestone by milestone**, running and verifying each before moving on.

## Project Context

**Two data sources:**

1. **Arduino sensor data** — Google Sheet ID: `1Ffx8hCabY_VDa9by-z3V9MzvicK-WcnpNpnsGPWUbsQ` (publicly readable CSV export). Columns: `timestamp, temp_c, humidity_pct, light_raw, sound_avg, sound_amplitude, pir_triggered, accel_x, accel_y, accel_z, accel_magnitude`. Key notes:
   - `light_raw` is **inverted**: flip with `4095 - light_raw` to get light intensity
   - DHT11 failures logged as `-1` → treat as NaN
   - Derive restlessness: `abs(diff(accel_x)) + abs(diff(accel_y)) + abs(diff(accel_z))`
   - 60-second sampling interval

2. **Garmin wearable data** — CSV files already in `./garmin_data/`. Key files and their schemas:
   - `sleep_summary.csv` — date, sleep_start (ms epoch), sleep_end (ms epoch), deep/light/rem/awake_sleep_seconds, average_respiration, overall_sleep_score
   - `sleep_stages.csv` — date, start_time, end_time, stage (deep/light/rem/awake), activity_level
   - `sleep_heart_rate_timeseries.csv` — date, timestamp, heart_rate
   - `hrv_timeseries.csv` — date, timestamp, timestamp_local, hrv_value
   - `sleep_stress_timeseries.csv` — date, timestamp, sleep_stress_value
   - `body_battery_sleep_timeseries.csv` — date, timestamp, body_battery_level
   - `respiration_timeseries.csv` — date, timestamp, respiration_rate (filter out -2 values)
   - `hrv_summary.csv` — date, weekly_avg, last_night_avg, last_night_5_min_high, status
   - `heart_rate_summary.csv` — date, resting_hr, min_hr, max_hr
   - `body_battery_summary.csv` — date, body_battery_charged, body_battery_drained, body_battery_highest, body_battery_lowest
   - `stress_timeseries.csv` — date, timestamp, stress_level
   - `sleep_movement_timeseries.csv` — date, start_time, end_time, movement_intensity
   - **Important:** Garmin files sleep under the **wake date**, not the fall-asleep date. Sleep timestamps are the previous calendar day.

## Existing File Structure

```
sleep_dashboard/
├── app.py                    ← navigation shell (written, needs review)
├── garmin_data/              ← all CSV files are here
├── data/
│   ├── __init__.py
│   ├── loader.py             ← Google Sheets + Garmin loading (written, needs review)
│   ├── processor.py          ← cleaning, scoring, alignment (written, needs review)
│   └── charts.py             ← shared Plotly theme + helpers (written, needs review)
├── views/
│   ├── __init__.py
│   ├── dashboard.py          ← View 1: single night detail (written, needs review)
│   ├── report_card.py        ← View 2: nightly report cards (written, needs review)
│   └── explorer.py           ← View 4: cross-night explorer (written, needs review)
└── requirements.txt
```

## Design System (apply consistently throughout)

- **Background:** `#0a0e1a` (page), `#0d1220` (cards/panels)
- **Grid/borders:** `#1e2a42`
- **Text:** `#c8d4e8` (primary), `#7a90b0` (muted)
- **Accent:** `#5b9cf6` (blue)
- **Fonts:** DM Serif Display (headings) + DM Mono (body/data) — import from Google Fonts
- **Sleep stage colours:** deep `#1e4d8c`, light `#4a90d9`, REM `#9b5fc0`, awake `#e05c5c`
- All Plotly charts use `paper_bgcolor="#0a0e1a"`, `plot_bgcolor="#0d1220"`, matching fonts and grid colours

## Environment Scoring Logic

Ideal ranges: temp 16–19°C, humidity 40–60%, light_lux 0–30 (transformed), sound_amplitude 0–50.
Score each variable 0–100 based on Gaussian decay from ideal midpoint.
Weights: temp 35%, humidity 20%, light 25%, sound 20%.
Compute per Arduino row, then average per night.

## The Three Views

**View 1 — Single Night Dashboard (`views/dashboard.py`):**
- Night selector dropdown (by wake date)
- Summary metric strip: sleep score, duration, deep mins, REM mins, awake mins, env score
- Sleep stage Gantt bar at top (colour-coded blocks, full width)
- Two tabs: **Arduino environment** (temp, humidity, light, sound amplitude, restlessness line charts + PIR event markers) and **Garmin physiology** (heart rate, sleep stress, HRV, body battery, respiration)
- All charts share the same x-axis time range with sleep stage colour bands as background shading
- Environment-per-stage summary table at bottom

**View 2 — Sleep Report Cards (`views/report_card.py`):**
- Weekly overview grouped bar chart (sleep score vs env score per night)
- One card per night containing:
  - Sleep score gauge (0–100 arc)
  - Env score gauge (0–100 arc)
  - Stage donut chart (deep/light/REM/awake proportions)
  - Metric strip: duration, HRV avg, resting HR, avg temp, avg humidity, motion events
  - Auto-generated insight line from the data (e.g. "Room was warm at 20.3°C · Deep sleep was short at 48 min · HRV was healthy at 72ms")

**View 4 — Sleep Stage Explorer (`views/explorer.py`):**
- Tab 1 — Stage Composition: stacked bar chart across nights + stage duration table + per-stage environment averages table + radar chart
- Tab 2 — Correlations: Pearson r heatmap (env metrics vs sleep metrics) + top 5 strongest relationships listed in plain English
- Tab 3 — Scatter Explorer: user-selectable x/y axes + preset key relationship scatter plots with trend lines and r values
- Tab 4 — Env Optimiser: for each env variable, show average value on good nights (≥ median sleep score) with correlation direction; framed as personalised recommendations

## Missing Garmin Files

The following Garmin files were exported by the project's Python script but are not in the folder yet. The code must handle their absence gracefully (skip/warn, don't crash):
- `sleep_stages.csv` ← **critical** — if missing, stage Gantt and alignment won't work; show clear warning
- `hrv_timeseries.csv`
- `sleep_stress_timeseries.csv`
- `respiration_timeseries.csv`
- `restless_moments.csv`

If `sleep_stages.csv` is missing, generate a mock version from `sleep_summary.csv` timestamps as a fallback so the dashboard is still demonstrable.

## Build Milestones — Complete and Verify Each Before Moving On

**Milestone 1 — Data layer review and test**
- Read all existing files in `data/`
- Fix any bugs, import errors, or schema mismatches you find
- Write and run `test_data.py` that: loads Arduino data (or mock), loads all Garmin CSVs, runs `compute_environment_score`, runs `build_nightly_summary`, prints a summary table
- Show me the output. Wait for confirmation before proceeding.

**Milestone 2 — View 1: Single Night Dashboard**
- Review and fix `views/dashboard.py`
- Run `streamlit run app.py` and verify it renders without errors
- Confirm: night selector works, stage Gantt shows, at least one sensor panel renders, metrics strip shows
- Show me what's working and any issues. Wait for confirmation.

**Milestone 3 — View 2: Report Cards**
- Review and fix `views/report_card.py`
- Run and verify: weekly bar renders, at least one night card shows with gauges, donut, and insight line
- Wait for confirmation.

**Milestone 4 — View 4: Explorer**
- Review and fix `views/explorer.py`
- Run and verify: all 4 tabs render, correlation heatmap shows (or graceful message if <2 nights), scatter explorer works
- Wait for confirmation.

**Milestone 5 — Polish and edge cases**
- Handle missing data gracefully throughout (NaN, missing files, single night)
- Ensure consistent dark theme across all charts
- Add `st.cache_data` where missing
- Check all `__init__.py` files are present
- Final run-through of all three views
- Report what was fixed.

Start with **Milestone 1**. Read the existing files first, then run the test. Show me the output before touching anything else.
