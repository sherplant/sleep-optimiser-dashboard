import pandas as pd
import numpy as np
import requests
import io
import os

GARMIN_DIR = os.path.join(os.path.dirname(__file__), "..", "garmin_data")

# ── Google Sheets ─────────────────────────────────────────────────────────────

def load_arduino(sheet_id: str = None, csv_path: str = None) -> pd.DataFrame:
    if csv_path and os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
    elif sheet_id:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
        except Exception:
            return pd.DataFrame()
    else:
        return pd.DataFrame()

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    for col in ["temp_c", "humidity_pct"]:
        if col in df.columns:
            df[col] = df[col].replace(-1, np.nan)
    if "light_raw" in df.columns:
        df["light_lux"] = 4095 - df["light_raw"]
    for axis in ["accel_x", "accel_y", "accel_z"]:
        if axis in df.columns:
            df[f"delta_{axis[-1]}"] = df[axis].diff().abs()
    delta_cols = [c for c in ["delta_x", "delta_y", "delta_z"] if c in df.columns]
    if delta_cols:
        df["restlessness"] = df[delta_cols].sum(axis=1)
    if "timestamp" in df.columns:
        df["date"] = df["timestamp"].dt.date
    return df


# ── Garmin helpers ────────────────────────────────────────────────────────────

def _read(filename, garmin_dir=None):
    d = garmin_dir or GARMIN_DIR
    path = os.path.join(d, filename)
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


def load_sleep_summary(garmin_dir=None):
    df = _read("sleep_summary.csv", garmin_dir)
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for col in ["sleep_start", "sleep_end"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col].astype(float), unit="ms", errors="coerce")
    for col in ["deep_sleep_seconds","light_sleep_seconds","rem_sleep_seconds","awake_seconds"]:
        if col in df.columns:
            df[col.replace("_seconds","_hrs")] = df[col] / 3600
    if "deep_sleep_seconds" in df.columns:
        total = sum(df.get(c, pd.Series(0)).fillna(0) for c in
                    ["deep_sleep_seconds","light_sleep_seconds","rem_sleep_seconds","awake_seconds"])
        df["total_sleep_hrs"] = total / 3600
    return df


def load_sleep_stages(garmin_dir=None):
    df = _read("sleep_stages.csv", garmin_dir)
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
    df["end_time"]   = pd.to_datetime(df["end_time"],   errors="coerce")
    df["duration_min"] = (df["end_time"] - df["start_time"]).dt.total_seconds() / 60
    df["stage_num"] = df["stage"].map({"deep":0,"light":1,"rem":2,"awake":3})
    return df


def _ts_df(filename, ts_col="timestamp", garmin_dir=None, positive_col=None):
    df = _read(filename, garmin_dir)
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.dropna(subset=[ts_col]).sort_values(ts_col)
    if positive_col and positive_col in df.columns:
        df = df[df[positive_col] > 0]
    return df


def load_heart_rate(garmin_dir=None):
    df = _ts_df("sleep_heart_rate_timeseries.csv", garmin_dir=garmin_dir)
    if df.empty:
        df = _ts_df("heart_rate_timeseries.csv", garmin_dir=garmin_dir)
    return df


def load_hrv(garmin_dir=None):
    df = _read("hrv_timeseries.csv", garmin_dir)
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df.dropna(subset=["timestamp"]).sort_values("timestamp")


def load_stress(garmin_dir=None):
    df = _ts_df("sleep_stress_timeseries.csv", garmin_dir=garmin_dir)
    if df.empty:
        df = _ts_df("stress_timeseries.csv", garmin_dir=garmin_dir)
    return df


def load_respiration(garmin_dir=None):
    return _ts_df("respiration_timeseries.csv", garmin_dir=garmin_dir,
                  positive_col="respiration_rate")


def load_body_battery(garmin_dir=None):
    df = _ts_df("body_battery_sleep_timeseries.csv", garmin_dir=garmin_dir)
    if df.empty:
        df = _ts_df("body_battery_allday_timeseries.csv", garmin_dir=garmin_dir)
    return df


def load_restless(garmin_dir=None):
    df = _read("restless_moments.csv", garmin_dir)
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df.dropna(subset=["timestamp"])


def load_movement(garmin_dir=None):
    df = _read("sleep_movement_timeseries.csv", garmin_dir)
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
    df["end_time"]   = pd.to_datetime(df["end_time"],   errors="coerce")
    return df.dropna(subset=["start_time"])


def load_hrv_summary(garmin_dir=None):
    df = _read("hrv_summary.csv", garmin_dir)
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def load_heart_rate_summary(garmin_dir=None):
    df = _read("heart_rate_summary.csv", garmin_dir)
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def load_body_battery_summary(garmin_dir=None):
    df = _read("body_battery_summary.csv", garmin_dir)
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def load_activity_data(garmin_dir=None):
    df = _read("daily_activity.csv", garmin_dir)
    if df.empty:
        return df
    df = df.rename(columns={"date": "activity_date"})
    df["activity_date"] = pd.to_datetime(df["activity_date"]).dt.date
    from datetime import timedelta
    df["sleep_date"] = df["activity_date"].apply(lambda d: d + timedelta(days=1))
    df["is_valid"] = df["total_steps"] > 1000
    for col in ["moderate_intensity_minutes", "vigorous_intensity_minutes"]:
        if col not in df.columns:
            df[col] = 0
    df["total_intensity_minutes"] = (
        df["moderate_intensity_minutes"].fillna(0) +
        df["vigorous_intensity_minutes"].fillna(0) * 2
    )
    return df


def load_all_garmin(garmin_dir=None):
    d = garmin_dir or GARMIN_DIR
    return {
        "summary":      load_sleep_summary(d),
        "stages":       load_sleep_stages(d),
        "hr":           load_heart_rate(d),
        "hrv":          load_hrv(d),
        "hrv_summary":  load_hrv_summary(d),
        "hr_summary":   load_heart_rate_summary(d),
        "bb_summary":   load_body_battery_summary(d),
        "stress":       load_stress(d),
        "respiration":  load_respiration(d),
        "body_battery": load_body_battery(d),
        "restless":     load_restless(d),
        "movement":     load_movement(d),
        "activity":     load_activity_data(d),
    }
