"""
=============================================================
Garmin Sleep & Health Data Exporter
For: Smart Sleep Environment Optimiser Project
=============================================================

This script connects to your Garmin Connect account and exports:
- Sleep data (sleep score, sleep stages, duration)
- Heart Rate Variability (HRV)
- Resting Heart Rate
- Body Battery
- Daily activity summary (steps, exercise)
- Stress data

All data is saved as CSV files for easy merging with Arduino sensor data.

SETUP INSTRUCTIONS:
-------------------
1. Make sure you have Python 3.8+ installed
2. Install the required packages:
   
   pip install garminconnect

3. Run this script:

   python garmin_export.py

4. On first run, you'll be prompted for your Garmin Connect email and password.
   - These are the same credentials you use to log in to connect.garmin.com
   - A session token will be saved to ~/.garminconnect so you won't need to 
     log in again for up to a year.
   - If you have MFA (multi-factor authentication) enabled, you'll be prompted
     for your MFA code as well.

5. Edit the START_DATE and END_DATE below to match your recording week.

NOTES:
------
- Garmin syncs sleep data after you sync your watch in the morning.
  Make sure you sync your watch BEFORE running this script each day.
- Sleep data for a given night appears under the DATE YOU WOKE UP.
  e.g., if you slept from 11pm Feb 12 to 7am Feb 13, the sleep data
  is under Feb 13.
- Run this script after your recording week is complete, or run it
  each morning to grab the previous night's data incrementally.
"""

import json
import csv
import os
import sys
from datetime import date, datetime, timedelta
from getpass import getpass
from pathlib import Path
from datetime import datetime, timezone

from garminconnect import Garmin
from garth import client

# ============================================================
# CONFIGURATION — EDIT THESE DATES TO MATCH YOUR RECORDING WEEK
# ============================================================
# Set to the first morning and last morning of your recording week.
# Example: if you recorded nights of Feb 12–18 (sleeping Feb 12 night,
# waking Feb 13 morning), set START = Feb 13, END = Feb 19.
START_DATE = date(2026, 2, 28)  # First morning of recording week
END_DATE = date(2026, 3, 7)    # Last morning of recording week

# Output folder for CSV files
OUTPUT_FOLDER = "garmin_data"
# ============================================================
def login_to_garmin():
    """Authenticate with Garmin Connect. Uses saved tokens if available."""
    tokenstore = Path("~/.garminconnect").expanduser()

    # Try logging in with saved tokens first
    try:
        client = Garmin()
        client.login(str(tokenstore))
        client.get_full_name()  # Forces the library to load your user profile
        client.user_profile_number = client.garth.profile["profileId"]
        print("✓ Logged in using saved session tokens.")
        return client
    except Exception:
        print("No saved session found. Logging in with credentials...")

    # Get credentials from user
    email = input("Garmin Connect email: ")
    password = getpass("Garmin Connect password: ")

    try:
        client = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)
        result1, result2 = client.login()

        # Handle MFA if enabled
        if result1 == "needs_mfa":
            mfa_code = input("Enter MFA code from your authenticator app: ")
            client.resume_login(result2, mfa_code)

        # Save tokens for future use
        client.garth.dump(str(tokenstore))

        # Load user profile so API calls that need user ID work correctly
        client.get_full_name()
        client.user_profile_number = client.garth.profile["profileId"]

        print("✓ Login successful. Session tokens saved for future use.")
        return client

    except Exception as e:
        print(f"✗ Login failed: {e}")
        print("  Check your email/password and try again.")
        sys.exit(1)


def get_date_range(start, end):
    """Generate a list of dates from start to end (inclusive)."""
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates

def timestamp_to_datetime(ts_ms):
    """Convert millisecond timestamp to readable datetime string."""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

def export_sleep_data(client, dates, output_folder):
    """
    Export sleep data for each date.
    Returns detailed sleep stage data and nightly summary.
    """
    print("\n--- Exporting Sleep Data ---")

    # Nightly summary CSV
    summary_rows = []
    # Detailed sleep stages CSV
    stages_rows = []

    for d in dates:
        date_str = d.isoformat()
        try:
            sleep = client.get_sleep_data(date_str)
            daily = sleep.get("dailySleepDTO", {})

            if not daily:
                print(f"  {date_str}: No sleep data found")
                continue

            # --- Nightly Summary ---
            summary = {
                "date": date_str,
                "sleep_start": daily.get("sleepStartTimestampLocal", ""),
                "sleep_end": daily.get("sleepEndTimestampLocal", ""),
                "duration_seconds": daily.get("sleepTimeInSeconds", ""),
                "deep_sleep_seconds": daily.get("deepSleepSeconds", ""),
                "light_sleep_seconds": daily.get("lightSleepSeconds", ""),
                "rem_sleep_seconds": daily.get("remSleepSeconds", ""),
                "awake_seconds": daily.get("awakeSleepSeconds", ""),
                "unmeasurable_seconds": daily.get("unmeasurableSleepSeconds", ""),
                "average_respiration": daily.get("averageRespirationValue", ""),
                "lowest_respiration": daily.get("lowestRespirationValue", ""),
                "highest_respiration": daily.get("highestRespirationValue", ""),
                "average_spo2": daily.get("averageSpO2Value", ""),
                "lowest_spo2": daily.get("lowestSpO2Value", ""),
                "average_stress": daily.get("averageSleepStress", ""),
            }

            # Try to get sleep score (may be in different location depending on watch)
            sleep_scores = sleep.get("sleepScores", {})
            if sleep_scores:
                summary["overall_sleep_score"] = sleep_scores.get("overallScore", "")
                summary["rem_score"] = sleep_scores.get("remScore", "")
                summary["deep_score"] = sleep_scores.get("deepScore", "")
                summary["light_score"] = sleep_scores.get("lightScore", "")
                summary["awake_score"] = sleep_scores.get("awakeScore", "")
            else:
                # Alternative location for sleep score
                summary["overall_sleep_score"] = daily.get("sleepScores", {}).get("overall", {}).get("value", "")

            summary_rows.append(summary)

            # --- Detailed Sleep Stages (time blocks) ---
            sleep_levels = sleep.get("sleepLevels", [])
            if sleep_levels:
                stage_map = {0.0: "deep", 1.0: "light", 2.0: "rem", 3.0: "awake"}
                for level in sleep_levels:
                    activity_level = level.get("activityLevel", -1)
                    stages_rows.append({
                        "date": date_str,
                        "start_time": level.get("startGMT", ""),
                        "end_time": level.get("endGMT", ""),
                        "stage": stage_map.get(activity_level, "movement"),
                        "activity_level": activity_level,
                    })

            # Also check sleepLevelsMap format
            levels_map = daily.get("sleepLevelsMap", {})
            if levels_map and not sleep_levels:
                for stage_name, periods in levels_map.items():
                    if isinstance(periods, list):
                        for period in periods:
                            stages_rows.append({
                                "date": date_str,
                                "start_time_seconds": period.get("startTimeInSeconds", ""),
                                "end_time_seconds": period.get("endTimeInSeconds", ""),
                                "stage": stage_name,
                            })

            print(f"  {date_str}: ✓ Sleep data exported")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    # Write summary CSV
    if summary_rows:
        filepath = os.path.join(output_folder, "sleep_summary.csv")
        write_csv(filepath, summary_rows)
        print(f"  → Saved: {filepath}")

    # Write stages CSV
    if stages_rows:
        filepath = os.path.join(output_folder, "sleep_stages.csv")
        write_csv(filepath, stages_rows)
        print(f"  → Saved: {filepath}")

    return summary_rows


def export_hrv_data(client, dates, output_folder):
    """Export time-series HRV data (every ~5 minutes during sleep)."""
    print("\n--- Exporting HRV Time-Series Data ---")

    summary_rows = []
    timeseries_rows = []

    for d in dates:
        date_str = d.isoformat()
        try:
            hrv = client.get_hrv_data(date_str)

            if hrv:
                # Daily summary
                summary = hrv.get("hrvSummary", {})
                if summary:
                    summary_rows.append({
                        "date": date_str,
                        "weekly_avg": summary.get("weeklyAvg", ""),
                        "last_night_avg": summary.get("lastNightAvg", ""),
                        "last_night_5_min_high": summary.get("lastNight5MinHigh", ""),
                        "baseline_low": summary.get("baselineLowUpper", ""),
                        "baseline_balanced_low": summary.get("baselineBalancedLow", ""),
                        "baseline_balanced_upper": summary.get("baselineBalancedUpper", ""),
                        "status": summary.get("status", ""),
                    })

                # Time-series data from hrvReadings
                hrv_readings = hrv.get("hrvReadings", [])
                for entry in hrv_readings:
                    if entry:
                        timeseries_rows.append({
                            "date": date_str,
                            "timestamp": entry.get("readingTimeGMT", ""),
                            "timestamp_local": entry.get("readingTimeLocal", ""),
                            "hrv_value": entry.get("hrvValue", ""),
                        })

                print(f"  {date_str}: ✓ HRV data exported ({len(hrv_readings)} readings)")
            else:
                print(f"  {date_str}: No HRV data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if summary_rows:
        filepath = os.path.join(output_folder, "hrv_summary.csv")
        write_csv(filepath, summary_rows)
        print(f"  → Saved: {filepath}")

    if timeseries_rows:
        filepath = os.path.join(output_folder, "hrv_timeseries.csv")
        write_csv(filepath, timeseries_rows)
        print(f"  → Saved: {filepath} ({len(timeseries_rows)} total readings)")

def export_heart_rate_data(client, dates, output_folder):
    """Export time-series heart rate data (every ~2 minutes)."""
    print("\n--- Exporting Heart Rate Time-Series Data ---")

    summary_rows = []
    timeseries_rows = []

    for d in dates:
        date_str = d.isoformat()
        try:
            hr = client.get_heart_rates(date_str)

            if hr:
                # Daily summary
                summary_rows.append({
                    "date": date_str,
                    "resting_hr": hr.get("restingHeartRate", ""),
                    "min_hr": hr.get("minHeartRate", ""),
                    "max_hr": hr.get("maxHeartRate", ""),
                    "last_seven_days_avg_resting_hr": hr.get("lastSevenDaysAvgRestingHeartRate", ""),
                })

                # Time-series data
                hr_values = hr.get("heartRateValues", [])
                for entry in hr_values:
                    if len(entry) >= 2 and entry[0] is not None and entry[1] is not None:
                        timeseries_rows.append({
                            "date": date_str,
                            "timestamp": timestamp_to_datetime(entry[0]),
                            "timestamp_ms": entry[0],
                            "heart_rate": entry[1],
                        })

                print(f"  {date_str}: ✓ HR data exported ({len(hr_values)} readings)")
            else:
                print(f"  {date_str}: No HR data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if summary_rows:
        filepath = os.path.join(output_folder, "heart_rate_summary.csv")
        write_csv(filepath, summary_rows)
        print(f"  → Saved: {filepath}")

    if timeseries_rows:
        filepath = os.path.join(output_folder, "heart_rate_timeseries.csv")
        write_csv(filepath, timeseries_rows)
        print(f"  → Saved: {filepath} ({len(timeseries_rows)} total readings)")


def export_body_battery_data(client, dates, output_folder):
    """Export body battery data: sleep period and all-day."""
    print("\n--- Exporting Body Battery Data ---")

    summary_rows = []
    sleep_bb_rows = []
    allday_bb_rows = []

    for d in dates:
        date_str = d.isoformat()
        try:
            # --- Daily summary from stats ---
            stats = client.get_stats(date_str)
            if stats:
                summary_rows.append({
                    "date": date_str,
                    "body_battery_charged": stats.get("bodyBatteryChargedValue", ""),
                    "body_battery_drained": stats.get("bodyBatteryDrainedValue", ""),
                    "body_battery_highest": stats.get("bodyBatteryHighestValue", ""),
                    "body_battery_lowest": stats.get("bodyBatteryLowestValue", ""),
                    "body_battery_most_recent": stats.get("bodyBatteryMostRecentValue", ""),
                    "average_stress_level": stats.get("averageStressLevel", ""),
                    "max_stress_level": stats.get("maxStressLevel", ""),
                })

            # --- Sleep body battery (from sleep endpoint) ---
            sleep = client.get_sleep_data(date_str)
            sleep_bb_count = 0
            if sleep:
                sleep_bb = sleep.get("sleepBodyBattery", [])
                for entry in sleep_bb:
                    if entry and entry.get("startGMT") is not None:
                        sleep_bb_rows.append({
                            "date": date_str,
                            "timestamp": timestamp_to_datetime(entry["startGMT"]),
                            "timestamp_ms": entry["startGMT"],
                            "body_battery_level": entry.get("value", ""),
                        })
                sleep_bb_count = len(sleep_bb)

            # --- All-day body battery (from stress endpoint) ---
            stress = client.get_stress_data(date_str)
            allday_bb_count = 0
            if stress:
                bb_values = stress.get("bodyBatteryValuesArray", [])
                for entry in bb_values:
                    if len(entry) >= 3 and entry[0] is not None:
                        allday_bb_rows.append({
                            "date": date_str,
                            "timestamp": timestamp_to_datetime(entry[0]),
                            "timestamp_ms": entry[0],
                            "status": entry[1],
                            "body_battery_level": entry[2],
                        })
                allday_bb_count = len(bb_values)

            print(f"  {date_str}: ✓ Body Battery exported (sleep: {sleep_bb_count}, all-day: {allday_bb_count})")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if summary_rows:
        filepath = os.path.join(output_folder, "body_battery_summary.csv")
        write_csv(filepath, summary_rows)
        print(f"  → Saved: {filepath}")

    if sleep_bb_rows:
        filepath = os.path.join(output_folder, "body_battery_sleep_timeseries.csv")
        write_csv(filepath, sleep_bb_rows)
        print(f"  → Saved: {filepath} ({len(sleep_bb_rows)} total readings)")

    if allday_bb_rows:
        filepath = os.path.join(output_folder, "body_battery_allday_timeseries.csv")
        write_csv(filepath, allday_bb_rows)
        print(f"  → Saved: {filepath} ({len(allday_bb_rows)} total readings)")


def export_daily_activity(client, dates, output_folder):
    """Export daily activity summary (steps, exercise, etc.) - context layer."""
    print("\n--- Exporting Daily Activity Data (Context Layer) ---")

    rows = []
    for d in dates:
        date_str = d.isoformat()
        try:
            stats = client.get_stats(date_str)

            if stats:
                row = {
                    "date": date_str,
                    "total_steps": stats.get("totalSteps", ""),
                    "total_distance_meters": stats.get("totalDistanceMeters", ""),
                    "total_kilocalories": stats.get("totalKilocalories", ""),
                    "active_kilocalories": stats.get("activeKilocalories", ""),
                    "floors_climbed": stats.get("floorsClimbed", ""),
                    "moderate_intensity_minutes": stats.get("moderateIntensityMinutes", ""),
                    "vigorous_intensity_minutes": stats.get("vigorousIntensityMinutes", ""),
                    "intensity_minutes_goal": stats.get("intensityMinutesGoal", ""),
                    "sedentary_seconds": stats.get("sedentarySeconds", ""),
                    "active_seconds": stats.get("activeSeconds", ""),
                    "highly_active_seconds": stats.get("highlyActiveSeconds", ""),
                }
                rows.append(row)
                print(f"  {date_str}: ✓ Activity data exported (steps: {stats.get('totalSteps', 'n/a')})")
            else:
                print(f"  {date_str}: No activity data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if rows:
        filepath = os.path.join(output_folder, "daily_activity.csv")
        write_csv(filepath, rows)
        print(f"  → Saved: {filepath}")


def export_stress_data(client, dates, output_folder):
    """Export stress data for each day."""
    print("\n--- Exporting Stress Data ---")

    rows = []
    for d in dates:
        date_str = d.isoformat()
        try:
            stress = client.get_stress_data(date_str)

            if stress:
                row = {
                    "date": date_str,
                    "avg_stress_level": stress.get("avgStressLevel", ""),
                    "max_stress_level": stress.get("maxStressLevel", ""),
                    "start_time_gmt": stress.get("startTimestampGMT", ""),
                    "end_time_gmt": stress.get("endTimestampGMT", ""),
                }
                rows.append(row)
                print(f"  {date_str}: ✓ Stress data exported (avg: {stress.get('avgStressLevel', 'n/a')})")
            else:
                print(f"  {date_str}: No stress data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if rows:
        filepath = os.path.join(output_folder, "stress_data.csv")
        write_csv(filepath, rows)
        print(f"  → Saved: {filepath}")

def export_sleep_stress_data(client, dates, output_folder):
    """Export sleep stress time-series (every ~3 minutes during sleep)."""
    print("\n--- Exporting Sleep Stress Time-Series Data ---")

    rows = []
    for d in dates:
        date_str = d.isoformat()
        try:
            sleep = client.get_sleep_data(date_str)

            if sleep:
                stress_data = sleep.get("sleepStress", [])
                for entry in stress_data:
                    if entry and entry.get("startGMT") is not None:
                        rows.append({
                            "date": date_str,
                            "timestamp": timestamp_to_datetime(entry["startGMT"]),
                            "timestamp_ms": entry["startGMT"],
                            "sleep_stress_value": entry.get("value", ""),
                        })
                print(f"  {date_str}: ✓ Sleep stress exported ({len(stress_data)} readings)")
            else:
                print(f"  {date_str}: No sleep data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if rows:
        filepath = os.path.join(output_folder, "sleep_stress_timeseries.csv")
        write_csv(filepath, rows)
        print(f"  → Saved: {filepath} ({len(rows)} total readings)")


def export_restless_moments_data(client, dates, output_folder):
    """Export restless moments during sleep — timestamps of detected movement."""
    print("\n--- Exporting Restless Moments Data ---")

    rows = []
    for d in dates:
        date_str = d.isoformat()
        try:
            sleep = client.get_sleep_data(date_str)

            if sleep:
                restless = sleep.get("sleepRestlessMoments", [])
                daily = sleep.get("dailySleepDTO", {})
                restless_count = daily.get("restlessMomentsCount", "")

                for entry in restless:
                    if entry and entry.get("startGMT") is not None:
                        rows.append({
                            "date": date_str,
                            "timestamp": timestamp_to_datetime(entry["startGMT"]),
                            "timestamp_ms": entry["startGMT"],
                            "intensity": entry.get("value", ""),
                        })
                print(f"  {date_str}: ✓ Restless moments exported ({len(restless)} events, total count: {restless_count})")
            else:
                print(f"  {date_str}: No sleep data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if rows:
        filepath = os.path.join(output_folder, "restless_moments.csv")
        write_csv(filepath, rows)
        print(f"  → Saved: {filepath} ({len(rows)} total events)")

def export_respiration_data(client, dates, output_folder):
    """Export respiration rate time-series during sleep."""
    print("\n--- Exporting Respiration Time-Series Data ---")

    rows = []
    for d in dates:
        date_str = d.isoformat()
        try:
            sleep = client.get_sleep_data(date_str)

            if sleep:
                respiration = sleep.get("wellnessEpochRespirationDataDTOList", [])
                for entry in respiration:
                    if entry and entry.get("startTimeGMT") is not None:
                        rows.append({
                            "date": date_str,
                            "timestamp": timestamp_to_datetime(entry["startTimeGMT"]),
                            "timestamp_ms": entry["startTimeGMT"],
                            "respiration_rate": entry.get("respirationValue", ""),
                        })
                print(f"  {date_str}: ✓ Respiration exported ({len(respiration)} readings)")
            else:
                print(f"  {date_str}: No sleep data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if rows:
        filepath = os.path.join(output_folder, "respiration_timeseries.csv")
        write_csv(filepath, rows)
        print(f"  → Saved: {filepath} ({len(rows)} total readings)")

def export_sleep_movement_data(client, dates, output_folder):
    """Export minute-by-minute movement intensity during sleep.
    Great for validating Arduino accelerometer and PIR data."""
    print("\n--- Exporting Sleep Movement Time-Series Data ---")

    rows = []
    for d in dates:
        date_str = d.isoformat()
        try:
            sleep = client.get_sleep_data(date_str)

            if sleep:
                movement = sleep.get("sleepMovement", [])
                for entry in movement:
                    if entry:
                        rows.append({
                            "date": date_str,
                            "start_time": entry.get("startGMT", ""),
                            "end_time": entry.get("endGMT", ""),
                            "movement_intensity": entry.get("activityLevel", ""),
                        })
                print(f"  {date_str}: ✓ Sleep movement exported ({len(movement)} readings)")
            else:
                print(f"  {date_str}: No sleep data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if rows:
        filepath = os.path.join(output_folder, "sleep_movement_timeseries.csv")
        write_csv(filepath, rows)
        print(f"  → Saved: {filepath} ({len(rows)} total readings)")


def export_sleep_heart_rate_data(client, dates, output_folder):
    """Export heart rate during sleep window only (every ~2 minutes).
    Better for sync graph than the all-day heart rate data."""
    print("\n--- Exporting Sleep Heart Rate Time-Series Data ---")

    rows = []
    for d in dates:
        date_str = d.isoformat()
        try:
            sleep = client.get_sleep_data(date_str)

            if sleep:
                sleep_hr = sleep.get("sleepHeartRate", [])
                for entry in sleep_hr:
                    if entry and entry.get("startGMT") is not None:
                        rows.append({
                            "date": date_str,
                            "timestamp": timestamp_to_datetime(entry["startGMT"]),
                            "timestamp_ms": entry["startGMT"],
                            "heart_rate": entry.get("value", ""),
                        })
                print(f"  {date_str}: ✓ Sleep HR exported ({len(sleep_hr)} readings)")
            else:
                print(f"  {date_str}: No sleep data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if rows:
        filepath = os.path.join(output_folder, "sleep_heart_rate_timeseries.csv")
        write_csv(filepath, rows)
        print(f"  → Saved: {filepath} ({len(rows)} total readings)")


def export_stress_timeseries_data(client, dates, output_folder):
    """Export all-day stress time-series (every ~3 minutes).
    Useful as context layer — high daytime stress can affect sleep quality."""
    print("\n--- Exporting All-Day Stress Time-Series Data ---")

    rows = []
    for d in dates:
        date_str = d.isoformat()
        try:
            stress = client.get_stress_data(date_str)

            if stress:
                stress_values = stress.get("stressValuesArray", [])
                for entry in stress_values:
                    if len(entry) >= 2 and entry[0] is not None and entry[1] is not None:
                        rows.append({
                            "date": date_str,
                            "timestamp": timestamp_to_datetime(entry[0]),
                            "timestamp_ms": entry[0],
                            "stress_level": entry[1],
                        })
                print(f"  {date_str}: ✓ Stress time-series exported ({len(stress_values)} readings)")
            else:
                print(f"  {date_str}: No stress data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if rows:
        filepath = os.path.join(output_folder, "stress_timeseries.csv")
        write_csv(filepath, rows)
        print(f"  → Saved: {filepath} ({len(rows)} total readings)")


def export_breathing_disruption_data(client, dates, output_folder):
    """Export breathing disruption data during sleep.
    Value of 255 = no disruption detected. Lower values indicate disruptions."""
    print("\n--- Exporting Breathing Disruption Data ---")

    rows = []
    disruption_count = 0

    for d in dates:
        date_str = d.isoformat()
        try:
            sleep = client.get_sleep_data(date_str)

            if sleep:
                disruptions = sleep.get("breathingDisruptionData", [])
                for entry in disruptions:
                    if entry and entry.get("startGMT") is not None:
                        value = entry.get("value", 255)
                        rows.append({
                            "date": date_str,
                            "timestamp": timestamp_to_datetime(entry["startGMT"]),
                            "timestamp_ms": entry["startGMT"],
                            "end_timestamp": timestamp_to_datetime(entry["endGMT"]) if entry.get("endGMT") else "",
                            "end_timestamp_ms": entry.get("endGMT", ""),
                            "disruption_value": value,
                            "disruption_detected": "no" if value == 255 else "yes",
                        })
                        if value != 255:
                            disruption_count += 1

                print(f"  {date_str}: ✓ Breathing disruption exported ({len(disruptions)} entries)")
            else:
                print(f"  {date_str}: No sleep data found")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    if rows:
        filepath = os.path.join(output_folder, "breathing_disruption.csv")
        write_csv(filepath, rows)
        print(f"  → Saved: {filepath} ({len(rows)} entries, {disruption_count} actual disruptions detected)")
    else:
        print(f"  → No breathing disruption data found for any date")

def export_raw_json(client, dates, output_folder):
    """
    Save raw JSON responses for each date.
    Useful as a backup and for exploring what other data fields are available.
    """
    print("\n--- Saving Raw JSON Backups ---")

    json_folder = os.path.join(output_folder, "raw_json")
    os.makedirs(json_folder, exist_ok=True)

    for d in dates:
        date_str = d.isoformat()
        try:
            data = {
                "sleep": client.get_sleep_data(date_str),
                "heart_rate": client.get_heart_rates(date_str),
                "stats": client.get_stats(date_str),
            }

            # These might not be available on all watches
            try:
                data["hrv"] = client.get_hrv_data(date_str)
            except Exception:
                data["hrv"] = None

            try:
                data["stress"] = client.get_stress_data(date_str)
            except Exception:
                data["stress"] = None

            filepath = os.path.join(json_folder, f"garmin_raw_{date_str}.json")
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)

            print(f"  {date_str}: ✓ Raw JSON saved")

        except Exception as e:
            print(f"  {date_str}: ✗ Error - {e}")

    print(f"  → Saved to: {json_folder}/")


def write_csv(filepath, rows):
    """Write a list of dictionaries to a CSV file."""
    if not rows:
        return

    fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    print("=" * 60)
    print("  Garmin Sleep & Health Data Exporter")
    print("  Smart Sleep Environment Optimiser Project")
    print("=" * 60)
    print(f"\n  Date range: {START_DATE} to {END_DATE}")
    print(f"  ({(END_DATE - START_DATE).days + 1} days)")

    # Create output folder
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    # Login
    client = login_to_garmin()

    # Generate date list
    dates = get_date_range(START_DATE, END_DATE)

    # Export all data types
    export_sleep_data(client, dates, OUTPUT_FOLDER)
    export_hrv_data(client, dates, OUTPUT_FOLDER)
    export_heart_rate_data(client, dates, OUTPUT_FOLDER)
    export_body_battery_data(client, dates, OUTPUT_FOLDER)
    export_daily_activity(client, dates, OUTPUT_FOLDER)
    export_stress_data(client, dates, OUTPUT_FOLDER)
    export_sleep_stress_data(client, dates, OUTPUT_FOLDER)
    export_respiration_data(client, dates, OUTPUT_FOLDER)
    export_restless_moments_data(client, dates, OUTPUT_FOLDER)
    export_sleep_movement_data(client, dates, OUTPUT_FOLDER)
    export_sleep_heart_rate_data(client, dates, OUTPUT_FOLDER)
    export_stress_timeseries_data(client, dates, OUTPUT_FOLDER)
    export_breathing_disruption_data(client, dates, OUTPUT_FOLDER)

    # Save raw JSON as backup
    export_raw_json(client, dates, OUTPUT_FOLDER)

    # Summary
    print("\n" + "=" * 60)
    print("  EXPORT COMPLETE")
    print("=" * 60)
    print(f"\n  Files saved to: ./{OUTPUT_FOLDER}/")
    print(f"\n  CSV files generated:")
    print(f"")
    print(f"  Sleep Metrics (for sync graph):")
    print(f"    - sleep_summary.csv                  (nightly sleep overview)")
    print(f"    - sleep_stages.csv                   (sleep stages + movement intensity)")
    print(f"    - sleep_heart_rate_timeseries.csv     (HR every ~2 min during sleep)")
    print(f"    - sleep_stress_timeseries.csv         (stress every ~3 min during sleep)")
    print(f"    - hrv_timeseries.csv                  (HRV every ~5 min during sleep)")
    print(f"    - respiration_timeseries.csv          (breathing rate during sleep)")
    print(f"    - body_battery_sleep_timeseries.csv   (body battery during sleep)")
    print(f"    - restless_moments.csv                (restless events during sleep)")
    print(f"    - sleep_movement_timeseries.csv       (movement intensity during sleep)")
    print(f"    - breathing_disruption.csv            (breathing disruptions during sleep)")
    print(f"")
    print(f"  Context Layer (daytime / confounding factors):")
    print(f"    - daily_activity.csv                  (steps, exercise, intensity)")
    print(f"    - heart_rate_timeseries.csv           (HR every ~2 min all day)")
    print(f"    - stress_timeseries.csv               (stress every ~3 min all day)")
    print(f"    - body_battery_allday_timeseries.csv  (body battery all day)")
    print(f"")
    print(f"  Summaries (weekly trends):")
    print(f"    - hrv_summary.csv                     (nightly HRV overview)")
    print(f"    - heart_rate_summary.csv              (daily resting HR)")
    print(f"    - body_battery_summary.csv            (daily charge/drain)")
    print(f"    - stress_data.csv                     (daily stress breakdown)")
    print(f"")
    print(f"  Backup:")
    print(f"    - raw_json/                           (raw API responses)")
    print(f"")
    print(f"  Next steps:")
    print(f"    1. Check the CSV files look correct")
    print(f"    2. The sleep-window CSVs are key for your sync graph")
    print(f"       (overlay with Arduino environmental data)")
    print(f"    3. The context layer CSVs help explain nights where")
    print(f"       environment was good but sleep was poor")
    print(f"    4. Compare sleep_movement and restless_moments with")
    print(f"       Arduino accelerometer/PIR data to validate sensors")


if __name__ == "__main__":
    main()