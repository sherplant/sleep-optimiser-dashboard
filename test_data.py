"""
test_data.py — Milestone 1 verification script.
Run: python test_data.py  (from the sleep_dashboard/ directory)
"""

import os, sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from data.loader import load_arduino, load_all_garmin
from data.processor import (
    compute_environment_score,
    build_nightly_summary,
    compute_correlations,
)

SHEET_ID   = "16LkssYKqLjgFbfxQerSVt52BYBK0ByGZzp-NaS3y6jg"
GARMIN_DIR = os.path.join(os.path.dirname(__file__), "garmin_data")

SEP = "=" * 64


def _mock_arduino():
    """Generate 3-night mock Arduino data for offline testing."""
    rng  = np.random.default_rng(42)
    rows = []
    dates_start = [
        ("2026-02-07 23:00", "2026-02-08"),
        ("2026-02-08 23:00", "2026-02-09"),
        ("2026-02-09 23:00", "2026-02-10"),
    ]
    for start_str, wake_date in dates_start:
        n   = 480  # 8 h × 60 s
        ts  = pd.date_range(start_str, periods=n, freq="60s")
        ax  = rng.normal(0,   0.005, n)
        ay  = rng.normal(0,   0.005, n)
        az  = rng.normal(9.8, 0.005, n)
        rows.append(pd.DataFrame({
            "timestamp":       ts,
            "temp_c":          rng.normal(18, 0.8, n),
            "humidity_pct":    rng.normal(52, 3,   n),
            "light_raw":       rng.integers(3950, 4095, n),
            "sound_avg":       rng.normal(28, 6,   n),
            "sound_amplitude": rng.normal(22, 5,   n).clip(0),
            "pir_triggered":   rng.binomial(1, 0.01, n),
            "accel_x":  ax, "accel_y": ay, "accel_z": az,
        }))

    df = pd.concat(rows, ignore_index=True)
    df["light_lux"]     = 4095 - df["light_raw"]
    df["delta_x"]       = df["accel_x"].diff().abs()
    df["delta_y"]       = df["accel_y"].diff().abs()
    df["delta_z"]       = df["accel_z"].diff().abs()
    df["restlessness"]  = df[["delta_x", "delta_y", "delta_z"]].sum(axis=1)
    df["date"]          = df["timestamp"].dt.date
    return df


# ── 1. Arduino ─────────────────────────────────────────────────────────────────
print(SEP)
print("1. Loading Arduino data from Google Sheets…")
arduino = load_arduino(sheet_id=SHEET_ID)

if arduino.empty:
    print("   [WARN] Could not reach Google Sheets (or sheet is private).")
    print("   [INFO] Using 3-night mock Arduino data instead.\n")
    arduino = _mock_arduino()
else:
    print(f"   [OK]  Shape        : {arduino.shape}")
    print(f"   [OK]  Columns      : {list(arduino.columns)}")
    print(f"   [OK]  Date range   : {arduino['timestamp'].min()} -> {arduino['timestamp'].max()}")
    print(f"   [OK]  Nights       : {arduino['date'].nunique()}")
    print(f"   [OK]  First row    :\n{arduino.iloc[0].to_string()}")

# ── 2. Garmin ──────────────────────────────────────────────────────────────────
print()
print(SEP)
print("2. Loading all Garmin CSV files…")
garmin = load_all_garmin(GARMIN_DIR)

all_ok = True
for key, df in garmin.items():
    if isinstance(df, pd.DataFrame):
        nights = df["date"].nunique() if "date" in df.columns and not df.empty else 0
        status = "[OK]  " if not df.empty else "[WARN]"
        print(f"   {status} {key:<22}: {df.shape[0]:>4} rows x {df.shape[1]:>2} cols  ({nights} nights)")
        if df.empty:
            all_ok = False

if all_ok:
    print("\n   All Garmin loaders returned data.")
else:
    print("\n   [WARN] Some Garmin files returned empty DataFrames.")

# ── 3. compute_environment_score ───────────────────────────────────────────────
print()
print(SEP)
print("3. compute_environment_score — per-row Gaussian scoring…")
sample = pd.DataFrame({
    "temp_c":          [17.5, 22.0, 18.0, 16.0],
    "humidity_pct":    [50.0, 70.0, 45.0, 40.0],
    "light_lux":       [10.0, 200., 5.0,  0.0 ],
    "sound_amplitude": [20.0, 80.0, 30.0, 5.0 ],
})
scores = compute_environment_score(sample)
desc = ["ideal", "too warm/humid/bright/loud", "near-ideal", "boundary"]
for i, (s, d) in enumerate(zip(scores, desc)):
    print(f"   Row {i} ({d:30s}): {s:5.1f}/100")

# ── 4. build_nightly_summary ───────────────────────────────────────────────────
print()
print(SEP)
print("4. build_nightly_summary…")
sleep_sum = garmin["summary"]
hrv_sum   = garmin["hrv_summary"]
hr_sum    = garmin.get("hr_summary",  pd.DataFrame())
bb_sum    = garmin.get("bb_summary",  pd.DataFrame())

nightly = build_nightly_summary(arduino, sleep_sum, hrv_sum, hr_sum, bb_sum)

if nightly.empty:
    print("   [WARN] Nightly summary is empty -- no matching dates between Arduino and Garmin.")
else:
    print(f"   [OK]  Shape   : {nightly.shape}")
    print(f"   [OK]  Columns : {list(nightly.columns)}")
    print()
    # Pretty-print key columns
    display_cols = [c for c in [
        "date", "night", "overall_sleep_score",
        "deep_sleep_mins", "rem_sleep_mins", "duration_hours",
        "env_score", "avg_temp", "avg_humidity",
        "resting_hr", "last_night_avg",
    ] if c in nightly.columns]
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.width", 120)
    print(nightly[display_cols].to_string(index=False))

# ── 5. compute_correlations ────────────────────────────────────────────────────
print()
print(SEP)
print("5. compute_correlations…")
corr = compute_correlations(nightly)

if corr.empty:
    print("   [WARN] Correlation matrix empty -- need >=2 nights with overlapping env+sleep data.")
    print("          (If using mock Arduino data with real Garmin, dates may not overlap.)")
else:
    print(f"   [OK]  Matrix shape : {corr.shape}")
    print()
    print(corr.round(2).to_string())

print()
print(SEP)
print("All tests complete.")
