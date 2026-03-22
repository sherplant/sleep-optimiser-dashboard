import streamlit as st
import os
import sys
import pandas as pd

# Ensure project root on path
sys.path.insert(0, os.path.dirname(__file__))

from data.loader import load_arduino, load_all_garmin
from data.processor import process_all_nights
from views import dashboard, report_card, explorer

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sleep Environment Optimiser",
    page_icon="🌙",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Mono', monospace;
    background-color: #0a0e1a;
    color: #c8d4e8;
}
h1, h2, h3 { font-family: 'DM Serif Display', serif; }
.block-container { padding-top: 1.5rem; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0a1628 0%, #0d1f38 100%);
    border-right: 1px solid #1e3050;
}

/* Metric cards */
[data-testid="stMetric"] {
    background: #131d2e;
    border: 1px solid #1e3050;
    border-radius: 10px;
    padding: 0.6rem 0.8rem;
}
[data-testid="stMetricValue"] { color: #5b9cf6; font-family: 'DM Mono', monospace; }

/* Tabs */
[data-baseweb="tab-list"] { background: #0a1628; border-radius: 8px; }
[data-baseweb="tab"] { color: #7fa8d0; }
[aria-selected="true"] { color: #5b9cf6 !important; border-bottom: 2px solid #5b9cf6 !important; }

/* Selectbox */
[data-baseweb="select"] > div { background-color: #131d2e; border-color: #1e3050; }

/* Divider */
hr { border-color: #1e3050; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
# Defaults — reassigned inside expander if user changes them
garmin_dir   = os.path.join(os.path.dirname(__file__), "garmin_data")
arduino_mode = "Google Sheets (live)"
sheet_id     = "16LkssYKqLjgFbfxQerSVt52BYBK0ByGZzp-NaS3y6jg"
ard_file     = None

with st.sidebar:
    # Branded header
    st.markdown("""
    <div style="text-align:center; padding: 1rem 0 0.5rem;">
        <div style="font-size:2.5rem;">🌙</div>
        <div style="font-family:'DM Serif Display',serif; font-size:1.2rem;
                     color:#c8d4e8; font-weight:600; margin-top:0.3rem;">
            Sleep Optimiser
        </div>
        <div style="font-size:0.72rem; color:#7a90b0; margin-top:0.2rem;
                     text-transform:uppercase; letter-spacing:0.1em;">
            Smart Environment Monitor
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    # Navigation (above Data Sources)
    st.markdown(
        "<p style='color:#7a90b0; font-size:0.72rem; text-transform:uppercase; "
        "letter-spacing:0.1em; margin-bottom:8px;'>Navigation</p>",
        unsafe_allow_html=True,
    )
    view = st.radio(
        "View",
        ["📋 Report Cards", "🌙 Single Night", "📊 Sleep Analytics"],
        label_visibility="collapsed",
    )

    st.markdown("---")

    # Data Sources expander
    st.markdown(
        "<p style='color:#7a90b0; font-size:0.72rem; text-transform:uppercase; "
        "letter-spacing:0.1em; margin-bottom:8px;'>Data Sources</p>",
        unsafe_allow_html=True,
    )
    with st.expander("⚙️ Configure", expanded=False):
        # Garmin data directory
        garmin_dir = st.text_input(
            "Garmin data folder",
            value=garmin_dir,
            help="Path to folder containing Garmin CSV exports",
        )

        st.markdown("#### Arduino / Sensor Data")
        arduino_mode = st.radio(
            "Source", ["Google Sheets (live)", "Upload CSV", "No Arduino data"],
            label_visibility="collapsed",
        )

        csv_path = None
        ard_file = None

        if arduino_mode == "Google Sheets (live)":
            if sheet_id:
                short_id = sheet_id[:6] + "..." + sheet_id[-6:] if len(sheet_id) > 15 else sheet_id
                st.markdown(
                    f"<p style='color:#7a90b0; font-size:0.75rem; margin-bottom:2px;'>"
                    f"Current: <code>{short_id}</code></p>",
                    unsafe_allow_html=True,
                )
            sheet_id = st.text_input(
                "Google Sheet ID",
                value=sheet_id,
                help="Make the sheet publicly readable (View access) for live pull to work.",
            )
            if sheet_id:
                st.caption("⚠️ Sheet must be set to 'Anyone with link can view'")
        elif arduino_mode == "Upload CSV":
            ard_file = st.file_uploader("Upload Arduino CSV", type=["csv"])

# ── Load data (cached) ────────────────────────────────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def get_garmin(garmin_dir):
    return load_all_garmin(garmin_dir)

@st.cache_data(ttl=120, show_spinner=False)
def get_arduino_sheets(sid):
    return load_arduino(sheet_id=sid)

@st.cache_data(ttl=3600)
def get_arduino_csv(file_bytes: bytes) -> pd.DataFrame:
    import io, numpy as np
    if not file_bytes:
        return pd.DataFrame()
    raw = pd.read_csv(io.BytesIO(file_bytes))
    raw.columns = [c.strip().lower().replace(" ", "_") for c in raw.columns]
    if "timestamp" in raw.columns:
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce")
        raw = raw.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    for col in ["temp_c", "humidity_pct"]:
        if col in raw.columns:
            raw[col] = raw[col].replace(-1, np.nan)
    if "light_raw" in raw.columns:
        raw["light_lux"] = 4095 - raw["light_raw"]
    for axis in ["accel_x", "accel_y", "accel_z"]:
        if axis in raw.columns:
            raw[f"delta_{axis[-1]}"] = raw[axis].diff().abs()
    delta_cols = [c for c in ["delta_x", "delta_y", "delta_z"] if c in raw.columns]
    if delta_cols:
        raw["restlessness"] = raw[delta_cols].sum(axis=1)
    if "timestamp" in raw.columns:
        raw["date"] = raw["timestamp"].dt.date
    return raw

with st.spinner("Loading data..."):
    garmin = get_garmin(garmin_dir)

    if arduino_mode == "Google Sheets (live)" and sheet_id:
        arduino = get_arduino_sheets(sheet_id)
        if arduino.empty:
            st.sidebar.warning("⚠️ Could not load Sheet — check it's public. Continuing with Garmin-only.")
    elif arduino_mode == "Upload CSV" and ard_file is not None:
        arduino = get_arduino_csv(ard_file.read())
    else:
        arduino = pd.DataFrame()

nightly_df = process_all_nights(arduino, garmin)

# ── Status indicators (sidebar) ───────────────────────────────────────────────
stages_ok  = not garmin["stages"].empty
arduino_ok = not arduino.empty
summary_ok = not garmin["summary"].empty

with st.sidebar:
    st.markdown("---")
    st.markdown(
        "<p style='color:#7a90b0; font-size:0.72rem; text-transform:uppercase; "
        "letter-spacing:0.1em; margin-bottom:8px;'>Data Status</p>",
        unsafe_allow_html=True,
    )
    nights_count  = len(garmin["summary"]) if summary_ok else 0
    garmin_label  = (f"🟢 Garmin — {nights_count} night{'s' if nights_count != 1 else ''} loaded"
                     if stages_ok else "🔴 Garmin — no data found")
    arduino_label = ("🟢 Arduino — live sensor data loaded"
                     if arduino_ok else "🟡 Arduino — not loaded")
    st.markdown(
        f"<p style='font-size:0.78rem; color:#c8d4e8; margin:2px 0;'>{garmin_label}</p>"
        f"<p style='font-size:0.78rem; color:#c8d4e8; margin:2px 0;'>{arduino_label}</p>",
        unsafe_allow_html=True,
    )

# ── Routing ──────────────────────────────────────────────────────────────────
if view == "📋 Report Cards":
    report_card.render(garmin, arduino, nightly_df)

elif view == "🌙 Single Night":
    stages = garmin["stages"]
    if stages.empty:
        st.warning("No sleep stage data available.")
    else:
        dates = sorted(stages["date"].unique(), reverse=True)
        dashboard.render(garmin, arduino, dates, nightly_df)

elif view == "📊 Sleep Analytics":
    explorer.render(garmin, arduino, nightly_df)
