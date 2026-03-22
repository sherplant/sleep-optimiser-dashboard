"""
views/dashboard.py — View 1: Single Night Deep Dive

Layout:
  1. Metrics strip (sleep score, duration, deep, REM, awake, env score)
  2. Filter expander (master + individual checkboxes per metric group)
  3. Unified make_subplots figure with shared x-axis
     - Sleep stage add_vrect bands on all rows (opacity 0.12)
     - Dynamic rows based on checked metrics
  4. Environment-per-stage summary table
"""

import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import ollama

from data.processor import (
    STAGE_COLOURS, STAGE_LABELS,
    bin_arduino_to_stages, per_stage_averages, score_night,
)

# Design tokens
BG    = "#0a0e1a"
BG2   = "#0d1220"
GRID  = "#1e2a42"
TEXT  = "#c8d4e8"
TEXT2 = "#7a90b0"


def _theme(fig: go.Figure, n_rows: int, height: int = 520) -> go.Figure:
    """Apply dark theme to a make_subplots figure in-place and return it."""
    fig.update_layout(
        height=height,
        paper_bgcolor=BG,
        plot_bgcolor=BG2,
        font=dict(color=TEXT, family="DM Mono, monospace", size=11),
        hovermode="x unified",
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT, size=10),
            orientation="h", y=-0.06,
        ),
        margin=dict(l=60, r=20, t=36, b=60),
    )
    fig.update_annotations(font=dict(color=TEXT2, size=11))
    # Apply type="date" to ALL x-axes (no row filter) so shared axes are covered
    fig.update_xaxes(type="date")
    for i in range(1, n_rows + 1):
        fig.update_xaxes(
            showgrid=True, gridcolor=GRID, zeroline=False,
            tickfont=dict(size=10, color=TEXT2), linecolor=GRID,
            row=i, col=1,
        )
        fig.update_yaxes(
            showgrid=True, gridcolor=GRID, zeroline=False,
            tickfont=dict(size=10, color=TEXT2), linecolor=GRID,
            row=i, col=1,
        )
    fig.update_xaxes(tickformat="%H:%M", title_text="Time", row=n_rows, col=1)
    return fig


def render(garmin: dict, arduino: pd.DataFrame, available_dates, nightly_df: pd.DataFrame = None):
    st.markdown("## 🌙 Single Night Deep Dive")
    st.markdown(
        "<p style='color:#7a90b0; font-size:0.85rem; margin-top:-8px;'>"
        "A detailed look at one night — environment, physiology and sleep stage breakdown."
        "</p>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<p style='color:#7a90b0; font-size:0.78rem; "
        "text-transform:uppercase; letter-spacing:0.08em; margin-bottom:4px;'>"
        "📅 Select a night to explore"
        "</p>",
        unsafe_allow_html=True,
    )
    selected_date = st.selectbox(
        label="",
        options=available_dates,
        format_func=lambda d: d.strftime("%A, %d %b %Y") if hasattr(d, "strftime") else str(d),
        label_visibility="collapsed",
    )
    st.markdown("---")

    stages  = garmin.get("stages",       pd.DataFrame())
    hr      = garmin.get("hr",           pd.DataFrame())
    hrv     = garmin.get("hrv",          pd.DataFrame())
    stress  = garmin.get("stress",       pd.DataFrame())
    resp    = garmin.get("respiration",  pd.DataFrame())
    bb      = garmin.get("body_battery", pd.DataFrame())
    summary = garmin.get("summary",      pd.DataFrame())

    def _filt(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or "date" not in df.columns:
            return pd.DataFrame()
        return df[df["date"] == selected_date].copy()

    night_stages = _filt(stages)
    night_hr     = _filt(hr)
    night_hrv    = _filt(hrv)
    night_stress = _filt(stress)
    night_resp   = _filt(resp)
    night_bb     = _filt(bb)
    night_summ   = _filt(summary)
    night_ard    = _filt(arduino) if not arduino.empty else pd.DataFrame()

    # ── 1. Metrics strip ─────────────────────────────────────────────────────
    row_s     = night_summ.iloc[0] if not night_summ.empty else None
    env_score = score_night(night_ard) if not night_ard.empty else None

    lights_out_time   = None
    sleep_latency_min = None
    total_steps       = None
    active_kcal       = None
    intensity_mins    = None
    is_valid_activity = None
    if nightly_df is not None and not nightly_df.empty and selected_date in nightly_df["date"].values:
        nl_row = nightly_df[nightly_df["date"] == selected_date].iloc[0]
        lot = nl_row.get("lights_out_time")
        if lot is not None and not pd.isna(lot):
            lights_out_time = lot
        slm = nl_row.get("sleep_latency_mins")
        if slm is not None and pd.notna(slm):
            sleep_latency_min = slm
        total_steps       = nl_row.get("total_steps")
        active_kcal       = nl_row.get("active_kilocalories")
        intensity_mins    = nl_row.get("total_intensity_minutes")
        is_valid_activity = nl_row.get("is_valid_activity_day")

    def _v(field, fmt="{:.1f}", fallback="—"):
        if row_s is None:
            return fallback
        v = row_s.get(field)
        return fmt.format(v) if pd.notna(v) else fallback

    def _fmt_hours(val):
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return "—"
        h = int(val)
        m = round((val - h) * 60)
        if m == 60:
            h += 1
            m = 0
        return f"{h}h {m}m"

    def _vh(field):
        """Format a fractional-hours field as Xh Ym."""
        if row_s is None:
            return "—"
        v = row_s.get(field)
        return _fmt_hours(v) if v is not None and pd.notna(v) else "—"

    st.markdown("#### 📊 Tonight's Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Sleep Score", _v("overall_sleep_score", "{:.0f}"))
    c2.metric("Duration",    _vh("total_sleep_hrs"))
    c3.metric("Env Score",   f"{env_score:.0f}" if env_score is not None else "—")
    c4, c5, c6 = st.columns(3)
    c4.metric("Deep Sleep",  _vh("deep_sleep_hrs"))
    c5.metric("REM",         _vh("rem_sleep_hrs"))
    c6.metric("Awake",       _vh("awake_hrs"))
    c7, _, _ = st.columns(3)
    c7.metric("Sleep Latency", f"{sleep_latency_min:.0f} min" if sleep_latency_min is not None else "—")

    # ── 1b. Previous Day Activity ─────────────────────────────────────────────
    if is_valid_activity is not None and not (isinstance(is_valid_activity, float) and np.isnan(is_valid_activity)):
        st.markdown("#### 🏃 Previous Day Activity")
        if not bool(is_valid_activity):
            st.markdown(
                '<p style="color:#666;font-size:0.85rem;">'
                '🛌 Rest day / no activity data for the previous day.</p>',
                unsafe_allow_html=True,
            )
        else:
            a1, a2, a3 = st.columns(3)
            a1.metric("Steps",         f"{int(total_steps):,}"        if total_steps    is not None and pd.notna(total_steps)    else "—")
            a2.metric("Active kcal",   f"{active_kcal:.0f}"           if active_kcal    is not None and pd.notna(active_kcal)    else "—")
            a3.metric("Intensity min", f"{intensity_mins:.0f} min" if intensity_mins is not None and pd.notna(intensity_mins) else "—",
                      help="Moderate HR zone (50–70% max HR) = 1×, vigorous (70%+ max HR) = 2×. Calculated by Garmin from heart rate data.")

    st.markdown("---")

    # ── 2. Session state defaults ─────────────────────────────────────────────
    for key, default in [
        ("dn_show_temp",   True),
        ("dn_show_light",  True),
        ("dn_show_rest",   True),
        ("dn_show_hr",     True),
        ("dn_show_stress", True),
        ("dn_show_bb",     True),
        ("dn_show_resp",   True),
        ("dn_master_env",  True),
        ("dn_master_phy",  True),
    ]:
        st.session_state.setdefault(key, default)

    # ── 3. Data availability flags ────────────────────────────────────────────
    has_temp     = not night_ard.empty and "temp_c"          in night_ard.columns
    has_humidity = not night_ard.empty and "humidity_pct"    in night_ard.columns
    has_light    = not night_ard.empty and "light_lux"       in night_ard.columns
    has_rest     = not night_ard.empty and "restlessness"    in night_ard.columns
    has_pir      = not night_ard.empty and "pir_triggered"   in night_ard.columns
    has_hr       = not night_hr.empty  and "heart_rate"      in night_hr.columns
    has_hrv      = not night_hrv.empty and "hrv_value"       in night_hrv.columns
    has_bb       = not night_bb.empty  and "body_battery_level" in night_bb.columns
    has_resp     = not night_resp.empty and "respiration_rate"  in night_resp.columns
    stress_col   = (
        "sleep_stress_value" if not night_stress.empty and "sleep_stress_value" in night_stress.columns
        else "stress_level"  if not night_stress.empty and "stress_level"       in night_stress.columns
        else None
    )
    has_stress   = stress_col is not None

    env_child_keys = ["dn_show_temp", "dn_show_light", "dn_show_rest"]
    phy_child_keys = ["dn_show_hr",   "dn_show_stress", "dn_show_bb", "dn_show_resp"]

    def _apply_master_env():
        for k in env_child_keys:
            st.session_state[k] = st.session_state["dn_master_env"]

    def _apply_master_phy():
        for k in phy_child_keys:
            st.session_state[k] = st.session_state["dn_master_phy"]

    def _sync_masters():
        st.session_state["dn_master_env"] = all(st.session_state[k] for k in env_child_keys)
        st.session_state["dn_master_phy"] = all(st.session_state[k] for k in phy_child_keys)

    # ── 4. Filter expander ────────────────────────────────────────────────────
    _sync_masters()  # keep master in sync with children each render

    env_partial = any(st.session_state[k] for k in env_child_keys) and not all(st.session_state[k] for k in env_child_keys)
    phy_partial = any(st.session_state[k] for k in phy_child_keys) and not all(st.session_state[k] for k in phy_child_keys)

    st.markdown("#### 📈 Sleep & Environment Timeline")
    st.markdown(
        "<p style='color:#7a90b0; font-size:0.85rem; margin-top:-8px;'>"
        "Physiology and environment data plotted together — sleep stage bands show "
        "when each stage occurred throughout the night."
        "</p>",
        unsafe_allow_html=True,
    )

    with st.expander("📊 Customise Chart", expanded=False):
        col_env, col_phy = st.columns(2)

        with col_env:
            env_label = "Environment (partial)" if env_partial else "Environment"
            st.checkbox(env_label, key="dn_master_env", on_change=_apply_master_env)
            _, env_indent = st.columns([0.06, 0.94])
            with env_indent:
                st.checkbox("Temp & Humidity", key="dn_show_temp",
                            disabled=not (has_temp or has_humidity))
                st.checkbox("Light",           key="dn_show_light",
                            disabled=not has_light)
                st.checkbox("Restlessness",    key="dn_show_rest",
                            disabled=not (has_rest or has_pir))

        with col_phy:
            phy_label = "Physiology (partial)" if phy_partial else "Physiology"
            st.checkbox(phy_label, key="dn_master_phy", on_change=_apply_master_phy)
            _, phy_indent = st.columns([0.06, 0.94])
            with phy_indent:
                st.checkbox("Heart Rate & HRV", key="dn_show_hr",
                            disabled=not (has_hr or has_hrv))
                st.checkbox("Stress",           key="dn_show_stress",
                            disabled=not has_stress)
                st.checkbox("Body Battery",     key="dn_show_bb",
                            disabled=not has_bb)
                st.checkbox("Respiration",      key="dn_show_resp",
                            disabled=not has_resp)

    # ── 5. Stage warning (non-blocking) ───────────────────────────────────────
    if night_stages.empty:
        st.warning("No sleep stage data for this night — stage bands will not be shown.")

    # ── 6. Row plan ───────────────────────────────────────────────────────────
    row_plan = []  # list of {"title": str, "weight": float, "key": str}

    if st.session_state["dn_show_hr"] and (has_hr or has_hrv):
        row_plan.append({
            "title":  "Heart Rate (bpm) & HRV (ms)",
            "weight": 1.4 if (has_hr and has_hrv) else 1.0,
            "key":    "hr",
        })
    if st.session_state["dn_show_stress"] and has_stress:
        row_plan.append({"title": "Sleep Stress",         "weight": 1.0, "key": "stress"})
    if st.session_state["dn_show_resp"] and has_resp:
        row_plan.append({"title": "Respiration (br/min)", "weight": 1.0, "key": "resp"})
    if st.session_state["dn_show_temp"] and (has_temp or has_humidity):
        row_plan.append({
            "title":  "Temperature (°C) & Humidity (%)",
            "weight": 1.4 if (has_temp and has_humidity) else 1.0,
            "key":    "temp",
        })
    if st.session_state["dn_show_light"] and has_light:
        row_plan.append({"title": "Light Level (lux)",       "weight": 1.0, "key": "light"})
    if st.session_state["dn_show_rest"] and (has_rest or has_pir):
        row_plan.append({"title": "Restlessness & PIR Motion", "weight": 1.0, "key": "rest"})
    if st.session_state["dn_show_bb"] and has_bb:
        row_plan.append({"title": "Body Battery",         "weight": 1.0, "key": "bb"})

    if not row_plan:
        st.info("Select at least one metric to display the chart.")
    else:
        n_rows      = len(row_plan)
        weights     = [r["weight"] for r in row_plan]
        total_w     = sum(weights)
        row_heights = [w / total_w for w in weights]
        fig_height  = 180 + n_rows * 130

        fig = make_subplots(
            rows=n_rows, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=[r["title"] for r in row_plan],
            row_heights=row_heights,
        )

        # ── Helpers for stage background fills ──────────────────────────────
        def _hex_rgba(h, a=0.15):
            h = h.lstrip('#')
            return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"

        def _y_range(key):
            """Compute (y_min, y_max) from source data for a given row key."""
            vals = []
            if key == "hr":
                if has_hr:      vals.extend(night_hr["heart_rate"].dropna().tolist())
                if has_hrv:     vals.extend(night_hrv["hrv_value"].dropna().tolist())
            elif key == "stress" and has_stress:
                vals.extend(night_stress[stress_col].dropna().tolist())
            elif key == "bb" and has_bb:
                vals.extend(night_bb["body_battery_level"].dropna().tolist())
            elif key == "resp" and has_resp:
                vals.extend(night_resp["respiration_rate"].dropna().tolist())
            elif key == "temp":
                if has_temp:     vals.extend(night_ard["temp_c"].dropna().tolist())
                if has_humidity: vals.extend(night_ard["humidity_pct"].dropna().tolist())
            elif key == "light" and has_light:
                vals.extend(night_ard["light_lux"].dropna().tolist())
            elif key == "rest":
                if has_rest: vals.extend(night_ard["restlessness"].dropna().tolist())
                if has_pir:  vals.append(1.0)
            if not vals:
                return 0.0, 1.0
            mn, mx = float(min(vals)), float(max(vals))
            pad = (mx - mn) * 0.05 or 0.5
            return mn - pad, mx + pad

        # ── Stage background fills via Scatter toself (shapes stripped by Streamlit) ──
        # Streamlit's frontend drops layout.shapes; Scatter fill='toself' is reliable.
        if not night_stages.empty:
            for i, rp in enumerate(row_plan, 1):
                y0_r, y1_r = _y_range(rp["key"])
                for sname, scolour in STAGE_COLOURS.items():
                    seg_rows = night_stages[night_stages["stage"].str.lower() == sname]
                    if seg_rows.empty:
                        continue
                    x_pts: list = []
                    y_pts: list = []
                    for _, srow in seg_rows.iterrows():
                        x0t, x1t = srow["start_time"], srow["end_time"]
                        x_pts.extend([x0t, x0t, x1t, x1t, x0t, None])
                        y_pts.extend([y0_r, y1_r, y1_r, y0_r, y0_r, None])
                    fig.add_trace(go.Scatter(
                        x=x_pts, y=y_pts,
                        fill="toself",
                        fillcolor=_hex_rgba(scolour, 0.15),
                        line=dict(width=0),
                        mode="lines",
                        showlegend=False,
                        hoverinfo="skip",
                        name=f"_{sname}",
                    ), row=i, col=1)

        # ── Sleep latency shading + vertical annotations ─────────────────────
        # Use Scatter fill='toself' — layout.shapes are stripped by Streamlit.
        sleep_start_ts = row_s.get("sleep_start") if row_s is not None else None

        if lights_out_time is not None and not night_stages.empty:
            for i, rp in enumerate(row_plan, 1):
                y0_r, y1_r = _y_range(rp["key"])

                # Amber shading between lights-out and sleep onset
                if sleep_start_ts is not None and pd.notna(sleep_start_ts):
                    fig.add_trace(go.Scatter(
                        x=[lights_out_time, lights_out_time,
                           sleep_start_ts,  sleep_start_ts, lights_out_time],
                        y=[y0_r, y1_r, y1_r, y0_r, y0_r],
                        fill="toself",
                        fillcolor="rgba(243,156,18,0.07)",
                        line=dict(width=0),
                        mode="lines",
                        showlegend=False,
                        hoverinfo="skip",
                        name="_latency_shade",
                    ), row=i, col=1)

                # Lights-out vertical dashed line (amber)
                fig.add_trace(go.Scatter(
                    x=[lights_out_time, lights_out_time],
                    y=[y0_r, y1_r],
                    mode="lines",
                    line=dict(color="#f39c12", width=1.5, dash="dash"),
                    showlegend=(i == 1),
                    hoverinfo="skip",
                    name="Lights Out" if i == 1 else "_lights_out",
                ), row=i, col=1)

        if sleep_start_ts is not None and pd.notna(sleep_start_ts) and not night_stages.empty:
            for i, rp in enumerate(row_plan, 1):
                y0_r, y1_r = _y_range(rp["key"])
                fig.add_trace(go.Scatter(
                    x=[sleep_start_ts, sleep_start_ts],
                    y=[y0_r, y1_r],
                    mode="lines",
                    line=dict(color="#5b9cf6", width=1.5, dash="dot"),
                    showlegend=(i == 1),
                    hoverinfo="skip",
                    name="Sleep Onset" if i == 1 else "_sleep_onset",
                ), row=i, col=1)

        # ── Traces per row ───────────────────────────────────────────────────
        for i, rp in enumerate(row_plan, 1):
            k = rp["key"]

            if k == "hr":
                if has_hr:
                    fig.add_trace(go.Scatter(
                        x=night_hr["timestamp"], y=night_hr["heart_rate"],
                        name="Heart Rate", line=dict(color="#e05c5c", width=1.5),
                    ), row=i, col=1)
                if has_hrv:
                    fig.add_trace(go.Scatter(
                        x=night_hrv["timestamp"], y=night_hrv["hrv_value"],
                        name="HRV", line=dict(color="#2ecc71", width=1.5, dash="dot"),
                    ), row=i, col=1)

            elif k == "stress":
                fig.add_trace(go.Scatter(
                    x=night_stress["timestamp"], y=night_stress[stress_col],
                    name="Sleep Stress", line=dict(color="#f39c12", width=1.5),
                    fill="tozeroy", fillcolor="rgba(243,156,18,0.10)",
                ), row=i, col=1)

            elif k == "bb":
                fig.add_trace(go.Scatter(
                    x=night_bb["timestamp"], y=night_bb["body_battery_level"],
                    name="Body Battery", line=dict(color="#9b59b6", width=2),
                    fill="tozeroy", fillcolor="rgba(155,89,182,0.12)",
                ), row=i, col=1)

            elif k == "resp":
                fig.add_trace(go.Scatter(
                    x=night_resp["timestamp"], y=night_resp["respiration_rate"],
                    name="Respiration", line=dict(color="#1abc9c", width=1.5),
                ), row=i, col=1)

            elif k == "temp":
                if has_temp:
                    fig.add_trace(go.Scatter(
                        x=night_ard["timestamp"], y=night_ard["temp_c"],
                        name="Temp (°C)", line=dict(color="#e74c3c", width=1.5),
                    ), row=i, col=1)
                if has_humidity:
                    fig.add_trace(go.Scatter(
                        x=night_ard["timestamp"], y=night_ard["humidity_pct"],
                        name="Humidity (%)", line=dict(color="#3498db", width=1.5),
                    ), row=i, col=1)

            elif k == "light":
                fig.add_trace(go.Scatter(
                    x=night_ard["timestamp"], y=night_ard["light_lux"],
                    name="Light (lux)", line=dict(color="#f1c40f", width=1.5),
                    fill="tozeroy", fillcolor="rgba(241,196,15,0.10)",
                ), row=i, col=1)

            elif k == "rest":
                if has_rest:
                    fig.add_trace(go.Scatter(
                        x=night_ard["timestamp"], y=night_ard["restlessness"],
                        name="Restlessness", line=dict(color="#e67e22", width=1.5),
                        fill="tozeroy", fillcolor="rgba(230,126,34,0.10)",
                    ), row=i, col=1)
                if has_pir:
                    pir_ev = night_ard[night_ard["pir_triggered"] == 1]
                    if not pir_ev.empty:
                        y_pir = float(night_ard["restlessness"].max(skipna=True)) if has_rest else 1.0
                        y_pir = y_pir if y_pir > 0 else 1.0
                        fig.add_trace(go.Scatter(
                            x=pir_ev["timestamp"],
                            y=[y_pir] * len(pir_ev),
                            mode="markers", name="PIR Motion",
                            marker=dict(color="#c0392b", size=8, symbol="triangle-up"),
                        ), row=i, col=1)

        # ── Pin y-axis ranges so fills don't distort autoscale ──────────────
        for i, rp in enumerate(row_plan, 1):
            y0_r, y1_r = _y_range(rp["key"])
            fig.update_yaxes(range=[y0_r, y1_r], row=i, col=1)

        # ── Stage legend chips ───────────────────────────────────────────────
        legend_html = " ".join([
            f'<span style="background:{c};padding:2px 10px;border-radius:4px;'
            f'font-size:0.78rem;color:#fff;margin-right:6px;">'
            f'{STAGE_LABELS[s]}</span>'
            for s, c in STAGE_COLOURS.items()
        ])
        st.markdown(legend_html, unsafe_allow_html=True)

        _theme(fig, n_rows, height=fig_height)

        # ── X-axis range: sleep window (min 22:00 → 10:00) ──────────────────
        date_ts       = pd.Timestamp(selected_date)
        x_min_default = date_ts                            # 00:00
        x_max_default = date_ts + pd.Timedelta(hours=8)   # 08:00
        if not night_stages.empty:
            x_min = min(night_stages["start_time"].min() - pd.Timedelta(minutes=30), x_min_default)
            x_max = max(night_stages["end_time"].max()   + pd.Timedelta(minutes=30), x_max_default)
        else:
            x_min, x_max = x_min_default, x_max_default
        if lights_out_time is not None:
            x_min = min(lights_out_time - pd.Timedelta(minutes=10), x_min)
        fig.update_xaxes(range=[x_min, x_max])

        st.plotly_chart(fig, use_container_width=True)

    # ── 8. AI Sleep Insights ──────────────────────────────────────────────────
    def _build_prompt():
        lines = ["## Night Data Summary\n"]
        if row_s is not None:
            def _g(field, fmt="{:.1f}"):
                v = row_s.get(field)
                return fmt.format(v) if pd.notna(v) else "N/A"
            lines.append(f"- Sleep score: {_g('overall_sleep_score', '{:.0f}')}")
            lines.append(f"- Total sleep: {_g('total_sleep_hrs')} h")
            lines.append(f"- Deep sleep: {_g('deep_sleep_hrs')} h")
            lines.append(f"- REM sleep: {_g('rem_sleep_hrs')} h")
            lines.append(f"- Awake: {_g('awake_hrs')} h")
        if env_score is not None:
            lines.append(f"- Environment score: {env_score:.0f}")
        if not night_hr.empty and "heart_rate" in night_hr.columns:
            lines.append(f"- Mean heart rate: {night_hr['heart_rate'].mean():.1f} bpm")
        if not night_hrv.empty and "hrv_value" in night_hrv.columns:
            lines.append(f"- Mean HRV: {night_hrv['hrv_value'].mean():.1f} ms")
        if not night_ard.empty and "pir_triggered" in night_ard.columns:
            lines.append(f"- PIR motion events: {int(night_ard['pir_triggered'].sum())}")
        if not night_ard.empty and "light_raw" in night_ard.columns:
            after_4 = night_ard[night_ard["timestamp"].dt.hour >= 4]
            bright  = after_4[after_4["light_raw"] < 3800]
            if not bright.empty:
                lines.append(f"- Estimated sunrise/light onset: {bright.iloc[0]['timestamp'].strftime('%H:%M')}")
        if not night_ard.empty and not night_stages.empty:
            try:
                profile = per_stage_averages(bin_arduino_to_stages(night_ard, night_stages))
                if not profile.empty:
                    lines.append("\n## Per-Stage Environment Averages\n")
                    lines.append(profile.to_markdown(index=False, floatfmt=".1f"))
            except Exception:
                pass
        lines.append(
            "\n\nGiven the above data, provide exactly 3 bullet-point insights about "
            "correlations or patterns between the bedroom environment and sleep quality. "
            "Each bullet should be 2-3 sentences max. Reference specific values and times where relevant."
        )
        return "\n".join(lines)

    st.markdown("---")
    st.markdown("#### ✨ AI Sleep Insights")
    st.markdown(
        "<p style='color:#7a90b0; font-size:0.85rem; margin-top:-8px;'>"
        "Generate personalised insights about your sleep and bedroom environment.<br>"
        "Powered by a local AI model so your data never leaves your machine."
        "</p>",
        unsafe_allow_html=True,
    )
    # Check whether Ollama is reachable (works locally; fails on cloud/no server)
    try:
        ollama.list()
        ollama_ok = True
    except Exception:
        ollama_ok = False

    if not ollama_ok:
        st.info(
            "🤖 AI Sleep Insights uses Ollama to run a local language model. "
            "This feature is only available when running the dashboard locally — "
            "it is disabled in the hosted version."
        )

    data_ok = not night_stages.empty and row_s is not None
    if not data_ok:
        st.info("Insufficient data to generate insights for this night.")
    else:
        if st.button("✨ Generate Insights", disabled=not ollama_ok):
            system_prompt = (
                "You are a sleep analyst reviewing one night of data from a smart bedroom "
                "sensor system combined with a Garmin wearable. The bedroom has two occupants. "
                "Sensors include: temperature, humidity, light (LDR calibrated to room conditions), "
                "accelerometer-derived restlessness, PIR motion, heart rate, HRV, sleep stress, "
                "body battery, and respiration. Speak directly to the user in second person. "
                "Be specific — reference actual values and times where relevant. "
                "Do not give generic sleep hygiene advice."
            )
            user_prompt = _build_prompt()
            try:
                with st.spinner("Analysing your sleep data..."):
                    response = ollama.chat(
                        model="llama3.2",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user",   "content": user_prompt},
                        ],
                        stream=True,
                    )

                    def stream_response():
                        for chunk in response:
                            yield chunk["message"]["content"]

                    st.write_stream(stream_response())
                st.caption("Generated by Ollama (llama3.2) · Not medical advice")
            except Exception as e:
                err = str(e).lower()
                if isinstance(e, ConnectionError) or "connection" in err:
                    st.error("Could not connect to Ollama. Make sure Ollama is running locally — open a terminal and run: ollama serve")
                elif "model" in err or "not found" in err:
                    st.error("Model not found. Pull it first by running in your terminal: ollama pull llama3.2")
                else:
                    st.error(f"Ollama error: {str(e)}")

    # ── 7. Environment-per-stage table ────────────────────────────────────────
    if not night_ard.empty and not night_stages.empty:
        st.markdown("---")
        st.markdown("#### 🌡️ Environment per Sleep Stage")
        st.markdown(
            "<p style='color:#7a90b0; font-size:0.85rem; margin-top:-8px;'>"
            "How your bedroom conditions varied across each sleep stage last night — "
            "green highlights the best value, red the worst, per metric."
            "</p>",
            unsafe_allow_html=True,
        )
        binned  = bin_arduino_to_stages(night_ard, night_stages)
        profile = per_stage_averages(binned)
        if not profile.empty:
            # ── Step 1 — Data cleanup ─────────────────────────────────────────
            disp = profile.copy()
            drop_cols = ["avg_restlessness", "temp_score", "light_score",
                         "humidity_score", "rest_score"]
            disp = disp.drop(columns=[c for c in drop_cols if c in disp.columns])
            rename_map = {
                "stage":        "Sleep Stage",
                "temp_c":       "Temp (°C)",
                "humidity_pct": "Humidity (%)",
                "light_lux":    "Light (lux)",
                "restlessness": "Restlessness",
                "env_score":    "Env Score",
            }
            disp = disp.rename(columns=rename_map)
            STAGE_COLOR_MAP = {
                "awake": STAGE_COLOURS.get("awake", "#e05c5c"),
                "deep":  STAGE_COLOURS.get("deep",  "#1e4d8c"),
                "light": STAGE_COLOURS.get("light", "#4a90d9"),
                "rem":   STAGE_COLOURS.get("rem",   "#9b5fc0"),
            }

            # Keep Sleep Stage as regular column, don't set as index
            if "Sleep Stage" in disp.columns:
                disp["Sleep Stage"] = disp["Sleep Stage"].apply(
                    lambda s: f"● {str(s).capitalize()}"
                )

            disp = disp.reset_index(drop=True)

            for col in ["Temp (°C)", "Humidity (%)", "Light (lux)", "Env Score"]:
                if col in disp.columns:
                    disp[col] = disp[col].round(2)
            if "Restlessness" in disp.columns:
                disp["Restlessness"] = disp["Restlessness"].round(3)

            # ── Step 2 — Styling ──────────────────────────────────────────────
            fmt = {c: "{:.2f}" for c in disp.columns if c not in ["Sleep Stage", "Restlessness"]}
            if "Restlessness" in disp.columns:
                fmt["Restlessness"] = "{:.3f}"

            def highlight_best_worst(col):
                if col.name == "Sleep Stage":
                    return [""] * len(col)
                styles = [""] * len(col)
                numeric = pd.to_numeric(col, errors="coerce")
                if numeric.isna().all():
                    return styles
                lower_is_better = col.name in ["Restlessness", "Light (lux)", "Temp (°C)"]
                best_idx  = numeric.idxmin() if lower_is_better else numeric.idxmax()
                worst_idx = numeric.idxmax() if lower_is_better else numeric.idxmin()
                for i in range(len(col)):
                    if i == best_idx:
                        styles[i] = "color: #2ecc71; font-weight: 600;"
                    elif i == worst_idx:
                        styles[i] = "color: #e74c3c; font-weight: 600;"
                return styles

            def colour_stage_text(col):
                if col.name != "Sleep Stage":
                    return [""] * len(col)
                styles = []
                for val in col:
                    label = str(val).replace("●", "").strip().lower()
                    colour = STAGE_COLOR_MAP.get(label, "#c8d4e8")
                    styles.append(f"color: {colour}; font-weight: 700;")
                return styles

            numeric_cols = [c for c in disp.columns if c != "Sleep Stage"]
            best_env_idx = disp["Env Score"].idxmax() if "Env Score" in disp.columns else None

            def bold_best_env(row):
                if best_env_idx is not None and row.name == best_env_idx:
                    return ["font-weight: bold;"] * len(row)
                return [""] * len(row)

            styler = (
                disp.style.format(fmt)
                .set_properties(subset=numeric_cols, **{"text-align": "center"})
                .apply(colour_stage_text, axis=0)
                .apply(bold_best_env, axis=1)
                .apply(highlight_best_worst, axis=0)
            )

            # ── Step 3 — Render ───────────────────────────────────────────────
            st.dataframe(styler, use_container_width=True, hide_index=True)
            st.markdown(
                "<span style='font-size:0.8rem; color:#7a90b0;'>"
                "<span style='color:#2ecc71'>●</span> Best &nbsp;·&nbsp; "
                "<span style='color:#e74c3c'>●</span> Worst "
                "— per metric across all sleep stages"
                "</span>",
                unsafe_allow_html=True,
            )
        else:
            st.info("No environment-per-stage data available for this night.")
