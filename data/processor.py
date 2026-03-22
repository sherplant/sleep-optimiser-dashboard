"""
data/processor.py — Cleaning, scoring, alignment, and nightly summary building.

Composite scoring (v2):
    E = 0.30 × S_temp + 0.30 × S_light + 0.30 × S_rest + 0.10 × S_humidity

Nightly score = mean of per-minute scores within Garmin sleep_start → sleep_end.
Garmin timestamps are Unix milliseconds UTC.
"""

import pandas as pd
import numpy as np

# ── Design tokens (stage colours match charts.py) ─────────────────────────────
STAGE_COLOURS = {
    "deep":  "#1e4d8c",
    "light": "#4a90d9",
    "rem":   "#9b5fc0",
    "awake": "#e05c5c",
}

STAGE_LABELS = {
    "deep":  "Deep Sleep",
    "light": "Light Sleep",
    "rem":   "REM",
    "awake": "Awake",
}

# Column name lists used by explorer.py and correlations
ENV_COLS = [
    "env_score",
    "temp_score", "light_score", "rest_score", "humidity_score",
    "avg_temp", "avg_humidity", "avg_light", "avg_restlessness",
]
SLEEP_COLS = [
    "overall_sleep_score",
    "deep_sleep_mins", "light_sleep_mins", "rem_sleep_mins",
    "awake_mins", "duration_hours",
]


# ── Private per-component scorers ──────────────────────────────────────────────

def _score_temp(temp: pd.Series) -> pd.Series:
    """
    Temperature score.  Ideal band 19.0–20.5 °C (midpoint 19.75, half-band 0.75).
    Exponential decay outside band:  score = 100 × exp(−dist / 0.75)
    """
    t = pd.to_numeric(temp, errors="coerce")
    dist = np.maximum(0.0, (t - 19.75).abs() - 0.75)
    return (100.0 * np.exp(-dist / 0.75)).clip(0.0, 100.0)


def _score_humidity(hum: pd.Series) -> pd.Series:
    """
    Humidity score.  Ideal band 40–60 % (midpoint 50, half-band 10).
    score = 100 × exp(−dist / 10)
    """
    h = pd.to_numeric(hum, errors="coerce")
    dist = np.maximum(0.0, (h - 50.0).abs() - 10.0)
    return (100.0 * np.exp(-dist / 10.0)).clip(0.0, 100.0)


def _score_restlessness(rest: pd.Series) -> pd.Series:
    """
    Step-function restlessness score from Euclidean accel distance:
      < 0.053  → 100
      0.053–0.20 → 85
      0.20–0.50  → 50
      ≥ 0.50     → 10
    """
    r = pd.to_numeric(rest, errors="coerce").values
    out = np.where(r < 0.053, 100.0,
          np.where(r < 0.200,  85.0,
          np.where(r < 0.500,  50.0, 10.0)))
    return pd.Series(out.astype(float), index=rest.index)


def _compute_restlessness(ard: pd.DataFrame) -> pd.Series:
    """
    Euclidean restlessness per reading: sqrt(Δx² + Δy² + Δz²).
    diff() is computed per calendar date to avoid cross-night artifacts.
    Falls back to the loader-computed 'restlessness' column if raw axes absent.
    """
    has_axes = all(c in ard.columns for c in ["accel_x", "accel_y", "accel_z"])
    if has_axes:
        sort_cols = []
        if "date" in ard.columns:
            sort_cols.append("date")
        if "timestamp" in ard.columns:
            sort_cols.append("timestamp")
        srt = ard.sort_values(sort_cols) if sort_cols else ard

        if "date" in ard.columns:
            g = srt.groupby("date", sort=False)
            dx = g["accel_x"].diff().abs().fillna(0.0)
            dy = g["accel_y"].diff().abs().fillna(0.0)
            dz = g["accel_z"].diff().abs().fillna(0.0)
        else:
            dx = srt["accel_x"].diff().abs().fillna(0.0)
            dy = srt["accel_y"].diff().abs().fillna(0.0)
            dz = srt["accel_z"].diff().abs().fillna(0.0)

        rest = np.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
        return rest.reindex(ard.index).fillna(0.0)

    if "restlessness" in ard.columns:
        return ard["restlessness"].fillna(0.0)

    return pd.Series(np.nan, index=ard.index)


def _score_light(df: pd.DataFrame) -> pd.Series:
    """
    Light score with two components:

    1. Categorical from light_raw (higher raw = darker room):
         ≥ 3800 → 100,  3700–3799 → 70,  3200–3699 → 40,  < 3200 → 0

    2. Sunrise penalty via 10-min rolling linear slope of light_raw:
         if slope < −5 and 3200 < light_raw < 3850:
             penalty = min(40, |slope| × 1.5)
         light_score = max(0, categorical − penalty)

    Slope is computed in units of light_raw per 1-min sample step.
    Requires 'timestamp' and 'light_raw' columns; returns NaN series if absent.
    """
    if "light_raw" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    lr = pd.to_numeric(df["light_raw"], errors="coerce").values

    # 1. Categorical score
    cat = np.where(lr >= 3800, 100.0,
          np.where(lr >= 3700,  70.0,
          np.where(lr >= 3200,  40.0,  0.0)))

    # 2. Sunrise penalty
    penalty = np.zeros(len(df))
    if "timestamp" in df.columns:
        # Build a timestamp-indexed series (sorted), compute rolling polyfit slope
        ts_sorted = df.sort_values("timestamp").set_index("timestamp")
        lr_ts = ts_sorted["light_raw"].astype(float)

        slope_ts = lr_ts.rolling("10min", min_periods=3).apply(
            lambda y: float(np.polyfit(np.arange(len(y)), y, 1)[0])
                      if len(y) >= 3 else np.nan,
            raw=True,
        )

        # For duplicate timestamps keep last value, then map back to df rows
        slope_by_ts = slope_ts.groupby(level=0).last()
        slope_arr = df["timestamp"].map(slope_by_ts).values.astype(float)

        sun_mask = (slope_arr < -5) & (lr > 3200) & (lr < 3850)
        abs_slope = np.where(np.isnan(slope_arr), 0.0, np.abs(slope_arr))
        penalty = np.where(sun_mask, np.minimum(40.0, abs_slope * 1.5), 0.0)

    return pd.Series(np.maximum(0.0, cat - penalty).astype(float), index=df.index)


# ── Public composite scorer ────────────────────────────────────────────────────

def compute_environment_score(df: pd.DataFrame) -> pd.Series:
    """
    Per-row composite environment score (0–100):
        E = 0.30·S_temp + 0.30·S_light + 0.30·S_rest + 0.10·S_humidity

    Missing components have their weight redistributed proportionally.
    Used by bin_arduino_to_stages, score_night, and the explorer view.
    """
    if df.empty:
        return pd.Series(dtype=float)

    rest_series = _compute_restlessness(df)

    candidates = []
    if "temp_c" in df.columns:
        candidates.append((_score_temp(df["temp_c"]),        0.30))
    if "light_raw" in df.columns:
        candidates.append((_score_light(df),                 0.30))
    if not rest_series.isna().all():
        candidates.append((_score_restlessness(rest_series), 0.30))
    if "humidity_pct" in df.columns:
        candidates.append((_score_humidity(df["humidity_pct"]), 0.10))

    if not candidates:
        return pd.Series(np.nan, index=df.index)

    w_sum = pd.Series(0.0, index=df.index)
    w_tot = 0.0
    for series, w in candidates:
        if not series.isna().all():
            w_sum += series.fillna(0.0) * w
            w_tot += w

    if w_tot == 0:
        return pd.Series(np.nan, index=df.index)

    return (w_sum / w_tot).clip(0.0, 100.0).round(1)


def score_night(arduino_night: pd.DataFrame) -> float:
    """Return 0–100 environment score averaged over one night of Arduino data."""
    if arduino_night.empty:
        return np.nan
    row_scores = compute_environment_score(arduino_night).dropna()
    return round(float(row_scores.mean()), 1) if not row_scores.empty else np.nan


# ── Stage / Arduino alignment ─────────────────────────────────────────────────

def bin_arduino_to_stages(arduino: pd.DataFrame, stages: pd.DataFrame) -> pd.DataFrame:
    """
    For each sleep stage block, compute mean Arduino sensor values AND mean
    per-minute environment scores using the v2 composite formula.

    Scores are pre-computed on the full Arduino dataset before windowing so that
    the 10-min rolling light slope is consistent across stage boundaries.

    Raw sensor columns (backward-compatible):
        temp_c, humidity_pct, light_lux, light_raw,
        restlessness (loader Manhattan), pir_triggered

    New score columns added per stage:
        avg_restlessness  — Euclidean accel distance (grouped by date)
        temp_score        — v2 temperature component (0–100)
        light_score       — v2 light component with sunrise penalty (0–100)
        rest_score        — v2 restlessness component (0–100)
        humidity_score    — v2 humidity component (0–100)
        env_score         — v2 composite (0–100)
    """
    if arduino.empty or stages.empty or "timestamp" not in arduino.columns:
        return stages.copy()

    # ── Pre-compute per-row scores on the full dataset ───────────────────────
    ard = arduino.copy()

    ard["_rest_v2"] = _compute_restlessness(ard)

    _t  = _score_temp(ard["temp_c"])            if "temp_c"       in ard.columns \
          else pd.Series(np.nan, index=ard.index)
    _l  = _score_light(ard)                     if "light_raw"    in ard.columns \
          else pd.Series(np.nan, index=ard.index)
    _r  = _score_restlessness(ard["_rest_v2"])
    _h  = _score_humidity(ard["humidity_pct"])  if "humidity_pct" in ard.columns \
          else pd.Series(np.nan, index=ard.index)

    ard["_temp_score"] = _t
    ard["_light_score"] = _l
    ard["_rest_score"] = _r
    ard["_hum_score"]  = _h

    # Composite per row (same weight redistribution logic as compute_environment_score)
    w_sum = pd.Series(0.0, index=ard.index)
    w_tot = 0.0
    for s, w in [(_t, 0.30), (_l, 0.30), (_r, 0.30), (_h, 0.10)]:
        if not s.isna().all():
            w_sum += s.fillna(0.0) * w
            w_tot += w
    ard["_env_score"] = (w_sum / w_tot).clip(0.0, 100.0).round(1) \
                        if w_tot > 0 else np.nan

    # ── Raw sensor columns (kept for backward compatibility) ─────────────────
    sensor_cols = [c for c in [
        "temp_c", "humidity_pct", "light_lux", "light_raw",
        "restlessness", "pir_triggered",
    ] if c in arduino.columns]

    # Internal → public name map for the new score columns
    score_map = {
        "_rest_v2":     "avg_restlessness",
        "_temp_score":  "temp_score",
        "_light_score": "light_score",
        "_rest_score":  "rest_score",
        "_hum_score":   "humidity_score",
        "_env_score":   "env_score",
    }
    score_internal = [k for k in score_map if k in ard.columns]

    results = []
    for _, row in stages.iterrows():
        mask   = (ard["timestamp"] >= row["start_time"]) & \
                 (ard["timestamp"] <  row["end_time"])
        window = ard.loc[mask]

        agg = {col: window[col].mean() for col in sensor_cols if col in window.columns}
        for internal, public in score_map.items():
            if internal in window.columns:
                agg[public] = round(float(window[internal].mean()), 2) \
                              if not window[internal].isna().all() else np.nan
        agg.update(row.to_dict())
        results.append(agg)

    return pd.DataFrame(results)


# Aliases used by explorer.py and dashboard.py
align_arduino_to_stages = bin_arduino_to_stages


def stage_environment_profile(binned: pd.DataFrame) -> pd.DataFrame:
    """
    Average sensor readings and v2 environment scores grouped by stage type.
    Columns included (where present):
        Raw:    temp_c, humidity_pct, light_lux, restlessness (loader Manhattan)
        Scores: avg_restlessness (Euclidean), env_score,
                temp_score, light_score, rest_score, humidity_score
    """
    if binned.empty or "stage" not in binned.columns:
        return pd.DataFrame()
    agg_cols = [c for c in [
        # raw sensor averages
        "temp_c", "humidity_pct", "light_lux", "restlessness",
        # v2 scores
        "avg_restlessness",
        "env_score", "temp_score", "light_score", "rest_score", "humidity_score",
    ] if c in binned.columns]
    if not agg_cols:
        return pd.DataFrame()
    return binned.groupby("stage")[agg_cols].mean().round(2).reset_index()


# Alias used by dashboard.py and explorer.py
per_stage_averages = stage_environment_profile


# ── Standalone night metrics ───────────────────────────────────────────────────

def _pir_trips(
    ard_night: pd.DataFrame,
    sleep_start: pd.Timestamp,
    sleep_end: pd.Timestamp,
) -> dict:
    """
    Classify mid-sleep PIR events into 'your' vs 'partner' bathroom trips.

    Window: sleep_start + 60 min → sleep_end  (skip initial sleep-onset period)

    Your trips:    cluster of 2+ PIR triggers within 15 min
                   AND light_raw dips into 3700–3800 within ±10 min of cluster
    Partner trips: isolated single PIR trigger
                   AND light_raw stays ≥ 3800 within ±5 min of trigger

    Returns: { your_trips, partner_trips, mid_sleep_events }
    where mid_sleep_events = total number of distinct PIR clusters.
    """
    empty = {"your_trips": 0, "partner_trips": 0, "mid_sleep_events": 0}
    if "pir_triggered" not in ard_night.columns or \
       "timestamp" not in ard_night.columns or \
       pd.isna(sleep_start) or pd.isna(sleep_end):
        return empty

    win_start = sleep_start + pd.Timedelta(minutes=60)
    w = ard_night[
        (ard_night["timestamp"] >= win_start) &
        (ard_night["timestamp"] <= sleep_end)
    ].copy().sort_values("timestamp").reset_index(drop=True)

    pir_ts = w.loc[w["pir_triggered"] > 0, "timestamp"].tolist()
    if not pir_ts:
        return empty

    # Cluster consecutive PIR triggers that are ≤15 min apart
    clusters = []
    cur = [pir_ts[0]]
    for t in pir_ts[1:]:
        if (t - cur[-1]).total_seconds() <= 900:   # 15 min
            cur.append(t)
        else:
            clusters.append(cur)
            cur = [t]
    clusters.append(cur)

    your_trips    = 0
    partner_trips = 0

    for cluster in clusters:
        if len(cluster) >= 2:
            # Paired triggers: look for bathroom-light dip in ±10 min window
            if "light_raw" in w.columns:
                t0 = min(cluster) - pd.Timedelta(minutes=10)
                t1 = max(cluster) + pd.Timedelta(minutes=10)
                win_lr = w.loc[
                    (w["timestamp"] >= t0) & (w["timestamp"] <= t1), "light_raw"
                ]
                if not win_lr.empty and ((win_lr >= 3700) & (win_lr <= 3800)).any():
                    your_trips += 1
                # paired-but-no-light: ambiguous — not counted in either category
            else:
                your_trips += 1   # no light data → assume yours
        else:
            # Isolated trigger: partner if light stays dark, else ambiguous
            if "light_raw" in w.columns:
                t0 = cluster[0] - pd.Timedelta(minutes=5)
                t1 = cluster[0] + pd.Timedelta(minutes=5)
                win_lr = w.loc[
                    (w["timestamp"] >= t0) & (w["timestamp"] <= t1), "light_raw"
                ]
                if not win_lr.empty and (win_lr >= 3800).all():
                    partner_trips += 1
            # else: ambiguous, not counted

    return {
        "your_trips":      your_trips,
        "partner_trips":   partner_trips,
        "mid_sleep_events": len(clusters),
    }


def _sunrise_onset(ard_night: pd.DataFrame):
    """
    First timestamp in the night where:
      • 10-min rolling linear slope of light_raw < −5
      • light_raw is between 3200 and 3850

    Returns a time string 'HH:MM', or None if not detected.
    Slope units: light_raw per 1-min sample step (data sampled ~1/min).
    """
    if "light_raw" not in ard_night.columns or "timestamp" not in ard_night.columns:
        return None

    ts_s = (
        ard_night
        .sort_values("timestamp")
        .set_index("timestamp")["light_raw"]
        .astype(float)
    )

    slope = ts_s.rolling("10min", min_periods=3).apply(
        lambda y: float(np.polyfit(np.arange(len(y)), y, 1)[0])
                  if len(y) >= 3 else np.nan,
        raw=True,
    )

    mask  = (slope < -5) & (ts_s > 3200) & (ts_s < 3850) & (ts_s.index.hour >= 5)
    first = mask[mask].index
    return first[0].strftime("%H:%M") if not first.empty else None


def _restlessness_bouts(ard_night: pd.DataFrame) -> int:
    """
    Count distinct in-bed movement bouts per night.

    Criteria:
      • restlessness > 0.053  (Euclidean accel distance)
      • no PIR trigger within ±2 min  (exclude bathroom-trip motion)
      • a bout ends after 2+ consecutive readings below threshold
    """
    if ard_night.empty:
        return 0

    ard  = ard_night.sort_values("timestamp").reset_index(drop=True)
    rest = _compute_restlessness(ard)

    # Build PIR-proximity mask
    near_pir = pd.Series(False, index=ard.index)
    if "pir_triggered" in ard.columns and "timestamp" in ard.columns:
        pir_times = ard.loc[ard["pir_triggered"] > 0, "timestamp"]
        for pt in pir_times:
            near_pir |= (ard["timestamp"] - pt).abs() <= pd.Timedelta(minutes=2)

    active = (rest > 0.053) & (~near_pir)

    # State machine: bout ends on 2 consecutive inactive readings
    bouts        = 0
    in_bout      = False
    false_streak = 0

    for val in active:
        if val:
            if not in_bout:
                bouts  += 1
                in_bout = True
            false_streak = 0
        else:
            false_streak += 1
            if in_bout and false_streak >= 2:
                in_bout      = False
                false_streak = 0

    return bouts


def _detect_lights_out(ard_night: pd.DataFrame, sleep_start: pd.Timestamp):
    """
    Find the timestamp of the last lights-off event before sleep_start.

    Searches backward from sleep_start for the last contiguous run of
    light_raw >= 3800 with >= 5 consecutive readings whose first reading is
    NOT the very first row (i.e. there is a visible transition from light to dark).

    Returns a pd.Timestamp or None.
    Returns None when:
      - data already dark at the start of the window (no transition visible)
      - no sustained dark run found at all
    """
    if "light_raw" not in ard_night.columns or "timestamp" not in ard_night.columns:
        return None
    if pd.isna(sleep_start):
        return None

    before = (
        ard_night[ard_night["timestamp"] < sleep_start]
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if before.empty:
        return None

    dark = (before["light_raw"] >= 3800).values

    # Collect contiguous dark runs as (start_idx, end_idx)
    runs: list = []
    in_run = False
    run_start = 0
    for i, d in enumerate(dark):
        if d and not in_run:
            in_run, run_start = True, i
        elif not d and in_run:
            in_run = False
            runs.append((run_start, i - 1))
    if in_run:
        runs.append((run_start, len(dark) - 1))

    valid = [(s, e) for s, e in runs if (e - s + 1) >= 5]
    if not valid:
        return None

    last_s, _ = valid[-1]
    if last_s == 0:
        return None     # data started already dark — no visible transition

    return before.iloc[last_s]["timestamp"]


def _score_window(ard_window: pd.DataFrame) -> dict:
    """
    Compute mean environment component scores for a pre-filtered Arduino slice.
    ard_window must have '_rest_v2' already computed (call _compute_restlessness first).
    Returns dict: env_score, temp_score, light_score, rest_score, humidity_score.
    """
    empty = {k: np.nan for k in ["env_score", "temp_score", "light_score", "rest_score", "humidity_score"]}
    if ard_window.empty:
        return empty

    t_s = _score_temp(ard_window["temp_c"])            if "temp_c"       in ard_window.columns \
          else pd.Series(np.nan, index=ard_window.index)
    l_s = _score_light(ard_window)                     if "light_raw"    in ard_window.columns \
          else pd.Series(np.nan, index=ard_window.index)
    r_s = _score_restlessness(ard_window["_rest_v2"])  if "_rest_v2"     in ard_window.columns \
          else pd.Series(np.nan, index=ard_window.index)
    h_s = _score_humidity(ard_window["humidity_pct"])  if "humidity_pct" in ard_window.columns \
          else pd.Series(np.nan, index=ard_window.index)

    w_sum = pd.Series(0.0, index=ard_window.index)
    w_tot = 0.0
    for s, w in [(t_s, 0.30), (l_s, 0.30), (r_s, 0.30), (h_s, 0.10)]:
        if not s.isna().all():
            w_sum += s.fillna(s.mean()) * w
            w_tot += w

    env = round(float((w_sum / w_tot).mean()), 1) if w_tot > 0 else np.nan

    def _mn(s):
        return round(float(s.mean()), 1) if not s.isna().all() else np.nan

    return {
        "env_score":      env,
        "temp_score":     _mn(t_s),
        "light_score":    _mn(l_s),
        "rest_score":     _mn(r_s),
        "humidity_score": _mn(h_s),
    }


# ── Nightly summary ───────────────────────────────────────────────────────────

def build_nightly_summary(
    arduino:   pd.DataFrame,
    sleep_sum: pd.DataFrame,
    hrv_sum:   pd.DataFrame = None,
    hr_sum:    pd.DataFrame = None,
    bb_sum:    pd.DataFrame = None,
) -> pd.DataFrame:
    """
    Build a per-night merged summary of environment + Garmin metrics.

    Environment scores are computed over the Garmin sleep_start → sleep_end window
    (sleep_start and sleep_end must already be pandas Timestamps, as produced by
    loader.load_sleep_summary which converts Unix-ms to UTC datetimes).

    Output columns (where data available):
        date, night, env_score, temp_score, light_score, rest_score, humidity_score,
        sunrise_onset, your_pir_trips, partner_pir_trips, mid_sleep_events,
        restlessness_bouts,
        avg_temp, avg_humidity, avg_light, avg_restlessness, pir_events,
        overall_sleep_score, deep_sleep_{seconds,hrs,mins},
        light_sleep_{seconds,hrs,mins}, rem_sleep_{seconds,hrs,mins},
        awake_{seconds,hrs,mins}, total_sleep_hrs, duration_hours,
        + merged Garmin HRV, HR, body-battery columns
    """
    if sleep_sum is None or sleep_sum.empty:
        return pd.DataFrame()

    result = sleep_sum.copy()

    # Derive _hrs from _seconds (if not already present)
    for sec_col, hrs_col in [
        ("deep_sleep_seconds",  "deep_sleep_hrs"),
        ("light_sleep_seconds", "light_sleep_hrs"),
        ("rem_sleep_seconds",   "rem_sleep_hrs"),
        ("awake_seconds",       "awake_hrs"),
    ]:
        if sec_col in result.columns and hrs_col not in result.columns:
            result[hrs_col] = result[sec_col] / 3600.0

    # Derive _mins from _hrs (used by explorer.py)
    for hrs_col, mins_col in [
        ("deep_sleep_hrs",  "deep_sleep_mins"),
        ("light_sleep_hrs", "light_sleep_mins"),
        ("rem_sleep_hrs",   "rem_sleep_mins"),
        ("awake_hrs",       "awake_mins"),
    ]:
        if hrs_col in result.columns and mins_col not in result.columns:
            result[mins_col] = (result[hrs_col] * 60).round(0)

    # total_sleep_hrs and duration_hours
    if "total_sleep_hrs" not in result.columns:
        hrs_cols = [c for c in [
            "deep_sleep_hrs", "light_sleep_hrs", "rem_sleep_hrs", "awake_hrs",
        ] if c in result.columns]
        if hrs_cols:
            result["total_sleep_hrs"] = result[hrs_cols].sum(axis=1)

    if "duration_hours" not in result.columns and "total_sleep_hrs" in result.columns:
        result["duration_hours"] = result["total_sleep_hrs"]

    # Night label  (date objects → "01 Mar")
    if "date" in result.columns:
        result["night"] = result["date"].apply(
            lambda d: d.strftime("%d %b") if hasattr(d, "strftime") else str(d)
        )

    # ── Environment scoring per night within Garmin sleep window ──────────────
    env_records = []

    can_score = (
        not arduino.empty
        and "timestamp"   in arduino.columns
        and "sleep_start" in sleep_sum.columns
        and "sleep_end"   in sleep_sum.columns
    )

    if can_score:
        # Pre-compute Euclidean restlessness on the full dataset (grouped by date)
        ard_full = arduino.copy()
        ard_full["_rest_v2"] = _compute_restlessness(ard_full)

        for _, row in sleep_sum.iterrows():
            d       = row["date"]
            t_start = row["sleep_start"]
            t_end   = row["sleep_end"]

            if pd.isna(t_start) or pd.isna(t_end):
                env_records.append({"date": d})
                continue

            # Filter Arduino to Garmin sleep window
            ard = ard_full[
                (ard_full["timestamp"] >= t_start) &
                (ard_full["timestamp"] <= t_end)
            ].copy()

            if ard.empty:
                env_records.append({"date": d})
                continue

            # Component scores
            t_s = _score_temp(ard["temp_c"]) \
                  if "temp_c" in ard.columns \
                  else pd.Series(np.nan, index=ard.index)

            l_s = _score_light(ard) \
                  if "light_raw" in ard.columns \
                  else pd.Series(np.nan, index=ard.index)

            r_s = _score_restlessness(ard["_rest_v2"])

            h_s = _score_humidity(ard["humidity_pct"]) \
                  if "humidity_pct" in ard.columns \
                  else pd.Series(np.nan, index=ard.index)

            # Weighted composite (per-minute then averaged)
            w_sum = pd.Series(0.0, index=ard.index)
            w_tot = 0.0
            for s, w in [(t_s, 0.30), (l_s, 0.30), (r_s, 0.30), (h_s, 0.10)]:
                if not s.isna().all():
                    fill_val = s.mean() if not s.isna().all() else 0.0
                    w_sum += s.fillna(fill_val) * w
                    w_tot += w

            env_score = (
                round(float((w_sum / w_tot).mean()), 1) if w_tot > 0 else np.nan
            )

            # Standalone metrics
            pir_info = _pir_trips(ard, t_start, t_end)
            sunrise  = _sunrise_onset(ard)
            bouts    = _restlessness_bouts(ard)

            def _mean(col):
                return round(float(ard[col].mean()), 3) \
                       if col in ard.columns and not ard[col].isna().all() \
                       else np.nan

            env_records.append({
                "date":               d,
                "env_score":          env_score,
                "avg_env_score":      env_score,          # compat alias
                "temp_score":         round(float(t_s.mean()), 1)
                                      if not t_s.isna().all() else np.nan,
                "light_score":        round(float(l_s.mean()), 1)
                                      if not l_s.isna().all() else np.nan,
                "rest_score":         round(float(r_s.mean()), 1)
                                      if not r_s.isna().all() else np.nan,
                "humidity_score":     round(float(h_s.mean()), 1)
                                      if not h_s.isna().all() else np.nan,
                "avg_temp":           _mean("temp_c"),
                "avg_humidity":       _mean("humidity_pct"),
                "avg_light":          _mean("light_lux"),
                "avg_restlessness":   _mean("_rest_v2"),
                "pir_events":         int(ard["pir_triggered"].sum())
                                      if "pir_triggered" in ard.columns else 0,
                "sunrise_onset":      sunrise,
                "your_pir_trips":     pir_info["your_trips"],
                "partner_pir_trips":  pir_info["partner_trips"],
                "mid_sleep_events":   pir_info["mid_sleep_events"],
                "restlessness_bouts": bouts,
            })

        if env_records:
            env_df = pd.DataFrame(env_records)
            result = result.merge(env_df, on="date", how="left")

    else:
        # No Arduino data — fill env columns with NaN so downstream never KeyErrors
        for col in [
            "env_score", "avg_env_score",
            "temp_score", "light_score", "rest_score", "humidity_score",
            "avg_temp", "avg_humidity", "avg_light", "avg_restlessness",
            "pir_events", "sunrise_onset",
            "your_pir_trips", "partner_pir_trips", "mid_sleep_events",
            "restlessness_bouts",
        ]:
            if col not in result.columns:
                result[col] = np.nan

    # ── Merge additional Garmin summaries ─────────────────────────────────────
    if hrv_sum is not None and not hrv_sum.empty and "date" in hrv_sum.columns:
        hrv_cols = [c for c in ["date", "last_night_avg", "weekly_avg"]
                    if c in hrv_sum.columns]
        result = result.merge(hrv_sum[hrv_cols], on="date", how="left")

    if hr_sum is not None and not hr_sum.empty and "date" in hr_sum.columns:
        hr_cols = [c for c in ["date", "resting_hr", "min_hr", "max_hr"]
                   if c in hr_sum.columns]
        result = result.merge(hr_sum[hr_cols], on="date", how="left")

    if bb_sum is not None and not bb_sum.empty and "date" in bb_sum.columns:
        bb_cols = [c for c in [
            "date", "body_battery_highest", "body_battery_lowest",
            "body_battery_charged", "body_battery_drained",
        ] if c in bb_sum.columns]
        result = result.merge(bb_sum[bb_cols], on="date", how="left")

    return result.sort_values("date").reset_index(drop=True) if not result.empty else result


def nightly_summary(arduino: pd.DataFrame, garmin_summary: pd.DataFrame) -> pd.DataFrame:
    """Legacy helper — prefer build_nightly_summary for new code."""
    return build_nightly_summary(arduino, garmin_summary)


def process_all_nights(
    arduino:     pd.DataFrame,
    garmin_dict: dict,
) -> pd.DataFrame:
    """
    Extended nightly summary with lights-out detection and sleep latency.

    Calls build_nightly_summary() then adds per-night:
        lights_out_time            — pd.Timestamp of lights-off, or NaT
        sleep_latency_mins         — minutes from lights-out to sleep_start
                                     (NaN if > 45 min or undetectable)
        env_score_presleep         — env score for the lights_out→sleep_start window
        env_score_sleep            — env score for the sleep_start→sleep_end window
        total_sleep_mins           — total_sleep_hrs × 60
        sleep_score                — alias for overall_sleep_score
        total_mid_sleep_pir_events — renamed from mid_sleep_events
    """
    sleep_sum = garmin_dict.get("summary",     pd.DataFrame())
    hrv_sum   = garmin_dict.get("hrv_summary", pd.DataFrame())
    hr_sum    = garmin_dict.get("hr_summary",  pd.DataFrame())
    bb_sum    = garmin_dict.get("bb_summary",  pd.DataFrame())

    nightly = build_nightly_summary(arduino, sleep_sum, hrv_sum, hr_sum, bb_sum)
    if nightly.empty or arduino.empty or "sleep_start" not in nightly.columns:
        return nightly

    # Pre-compute Euclidean restlessness on the full dataset once
    ard_full = arduino.copy()
    ard_full["_rest_v2"] = _compute_restlessness(ard_full)

    lot_list: list  = []
    lat_list: list  = []
    pre_list: list  = []
    sleep_e_list: list = []

    for _, row in nightly.iterrows():
        d       = row["date"]
        t_start = row.get("sleep_start")

        ard_night = ard_full[ard_full["date"] == d]

        # Lights-out detection
        lot = (
            _detect_lights_out(ard_night, t_start)
            if (not ard_night.empty and pd.notna(t_start))
            else None
        )
        lot_list.append(lot if lot is not None else pd.NaT)

        # Sleep latency (NaN if > 45 min or lights-out undetectable)
        if lot is not None and pd.notna(t_start):
            lat = (t_start - lot).total_seconds() / 60.0
            lat_list.append(round(lat, 1) if lat <= 45 else np.nan)
        else:
            lat_list.append(np.nan)

        # Pre-sleep env score (lights_out → sleep_start)
        if lot is not None and pd.notna(t_start):
            pre_win = ard_full[
                (ard_full["timestamp"] >= lot) & (ard_full["timestamp"] < t_start)
            ]
            pre_list.append(_score_window(pre_win)["env_score"])
        else:
            pre_list.append(np.nan)

        # Sleep env score (sleep_start → sleep_end) = existing env_score column
        sleep_e_list.append(row.get("env_score", np.nan))

    nightly["lights_out_time"]   = lot_list
    nightly["sleep_latency_mins"] = lat_list
    nightly["env_score_presleep"] = pre_list
    nightly["env_score_sleep"]    = sleep_e_list

    if "total_sleep_hrs" in nightly.columns:
        nightly["total_sleep_mins"] = (nightly["total_sleep_hrs"] * 60).round(0)
    if "overall_sleep_score" in nightly.columns:
        nightly["sleep_score"] = nightly["overall_sleep_score"]
    if "mid_sleep_events" in nightly.columns:
        nightly["total_mid_sleep_pir_events"] = nightly["mid_sleep_events"]

    # ── Merge previous-day activity ───────────────────────────────────────────
    act = garmin_dict.get("activity", pd.DataFrame())
    if not act.empty and "sleep_date" in act.columns:
        act_m = act.rename(columns={"is_valid": "is_valid_activity_day"})
        keep = ["sleep_date"] + [c for c in [
            "activity_date", "total_steps", "active_kilocalories",
            "total_intensity_minutes", "highly_active_seconds", "is_valid_activity_day",
        ] if c in act_m.columns]
        nightly = nightly.merge(act_m[keep], left_on="date", right_on="sleep_date", how="left")
        nightly = nightly.drop(columns=["sleep_date"], errors="ignore")

    return nightly.sort_values("date").reset_index(drop=True)


# ── Stage environment profile ─────────────────────────────────────────────────

def compute_correlations(nightly: pd.DataFrame) -> pd.DataFrame:
    """
    Pairwise Pearson r between env metrics (rows) and sleep metrics (cols).
    Returns a pivot DataFrame suitable for correlation_heatmap().
    Requires at least 2 nights with overlapping data.
    """
    env_cols_present   = [c for c in ENV_COLS   if c in nightly.columns]
    sleep_cols_present = [c for c in SLEEP_COLS if c in nightly.columns]

    if not env_cols_present or not sleep_cols_present or len(nightly) < 2:
        return pd.DataFrame()

    data = {}
    for s_col in sleep_cols_present:
        col_data = {}
        for e_col in env_cols_present:
            sub = nightly[[e_col, s_col]].dropna()
            col_data[e_col] = round(sub[e_col].corr(sub[s_col]), 3) \
                              if len(sub) >= 2 else np.nan
        data[s_col] = col_data

    return pd.DataFrame(data, index=env_cols_present)


def correlations(nightly: pd.DataFrame) -> pd.DataFrame:
    """Long-form correlations — used by some legacy views."""
    env_cols_present = [c for c in [
        "env_score", "temp_score", "light_score", "rest_score", "humidity_score",
        "avg_temp", "avg_humidity", "avg_light", "avg_restlessness", "pir_events",
    ] if c in nightly.columns]
    sleep_cols_present = [c for c in [
        "overall_sleep_score", "total_sleep_hrs",
        "deep_sleep_hrs", "rem_sleep_hrs",
    ] if c in nightly.columns]

    if not env_cols_present or not sleep_cols_present:
        return pd.DataFrame()

    rows = []
    for e in env_cols_present:
        for s in sleep_cols_present:
            sub = nightly[[e, s]].dropna()
            if len(sub) >= 3:
                rows.append({
                    "env_metric":   e,
                    "sleep_metric": s,
                    "r":            round(sub[e].corr(sub[s]), 3),
                })
    return pd.DataFrame(rows)


# ── Legacy Gaussian scoring (kept for any external callers) ───────────────────

def _gauss(x, lo: float, hi: float):
    """Gaussian score: 100 at midpoint, decays to ~61 at band edges."""
    mid   = (lo + hi) / 2.0
    sigma = (hi - lo) / 2.0 + 1e-9
    return 100.0 * np.exp(-0.5 * ((x - mid) / sigma) ** 2)
