import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from data.processor import STAGE_COLOURS, STAGE_LABELS, score_night

BG      = "#0a0e1a"
BG2     = "#0d1220"
ACCENT  = "#5b9cf6"
TEXT    = "#c8d4e8"
TEXT2   = "#7a90b0"
GRID    = "#1e2a42"


def _fmt_hours(val):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "—"
    h = int(val)
    m = round((val - h) * 60)
    if m == 60:
        h += 1
        m = 0
    return f"{h}h {m}m"


def _score_colour(score):
    if pd.isna(score): return "#666"
    if score >= 80: return "#2ecc71"
    if score >= 60: return "#f39c12"
    return "#e74c3c"


def _latency_colour(mins):
    if pd.isna(mins): return "#666"
    if mins <= 10: return "#2ecc71"
    if mins <= 20: return "#f39c12"
    return "#e74c3c"


def _score_label(score):
    if pd.isna(score): return "No data"
    if score >= 85: return "Excellent"
    if score >= 70: return "Good"
    if score >= 55: return "Fair"
    return "Poor"


def _auto_insight(row, env_score, hrv_row):
    """Return one human-readable insight string for the night."""
    awake_min = row.get("awake_hrs", np.nan)
    awake_min = awake_min * 60 if pd.notna(awake_min) else np.nan
    deep_h    = row.get("deep_sleep_hrs", np.nan)
    rem_h     = row.get("rem_sleep_hrs", np.nan)
    total_h   = row.get("total_sleep_hrs", np.nan)
    score     = row.get("overall_sleep_score", np.nan)

    if pd.notna(awake_min) and awake_min > 30:
        return f"Sleep disrupted — {awake_min:.0f} min awake during the night."
    if pd.notna(deep_h) and deep_h < 1.0:
        return f"Deep sleep was short at {deep_h*60:.0f} min — aim for 90+ min."
    if pd.notna(rem_h) and rem_h < 1.0:
        return f"REM sleep was low at {rem_h*60:.0f} min — target 90+ min."
    if pd.notna(env_score) and env_score >= 85:
        return f"Excellent sleep environment — environment score {env_score:.0f}."
    if pd.notna(env_score) and env_score < 60:
        return f"Poor sleep environment (score {env_score:.0f}) may have affected rest."
    if pd.notna(score) and score >= 85:
        return f"Strong night overall — Garmin sleep score {score:.0f}."
    if pd.notna(total_h):
        return f"Total sleep was {_fmt_hours(total_h)}."
    return "No insight available for this night."


def _env_badges(night_ard):
    """Return list of (label, value, status) tuples for environment metrics."""
    badges = []
    if night_ard.empty:
        return badges
    if "temp_c" in night_ard.columns:
        t = night_ard["temp_c"].dropna().mean()
        ok = 16 <= t <= 19 if not np.isnan(t) else None
        badges.append(("🌡 Temp", f"{t:.1f}°C", "good" if ok else "warn" if ok is not None else "na"))
    if "humidity_pct" in night_ard.columns:
        h = night_ard["humidity_pct"].dropna().mean()
        ok = 40 <= h <= 60 if not np.isnan(h) else None
        badges.append(("💧 Humidity", f"{h:.0f}%", "good" if ok else "warn" if ok is not None else "na"))
    if "light_lux" in night_ard.columns:
        l = night_ard["light_lux"].dropna().mean()
        ok = l < 100 if not np.isnan(l) else None
        badges.append(("💡 Light", f"{l:.0f}", "good" if ok else "warn" if ok is not None else "na"))
    return badges


def render(garmin: dict, arduino: pd.DataFrame, nightly_df: pd.DataFrame = None):
    st.markdown("## 🌙 Your Sleep Report Cards")

    summary = garmin["summary"]
    stages  = garmin["stages"]
    hrv_sum = garmin["hrv_summary"]

    if summary.empty:
        st.warning("No summary data available.")
        return

    if "overall_sleep_score" in summary.columns and not summary["overall_sleep_score"].isna().all():
        best_date  = summary.loc[summary["overall_sleep_score"].idxmax(), "date"]
        best_label = best_date.strftime("%a %d %b") if hasattr(best_date, "strftime") else str(best_date)
        subtitle   = (
            "A card for each night — tap 'View Details' to explore your sleep and environment in full. "
            f"{best_label} is your best night this week."
        )
    else:
        subtitle = "A card for each night — tap 'View Details' to explore your sleep and environment in full."
    st.markdown(
        f"<p style='color:#7a90b0; font-size:0.85rem; margin-top:-8px;'>{subtitle}</p>",
        unsafe_allow_html=True,
    )

    # ── Session state ──────────────────────────────────────────────────────────
    if "selected_night" not in st.session_state:
        st.session_state["selected_night"] = None

    # ── Best night ─────────────────────────────────────────────────────────────
    best_score = summary["overall_sleep_score"].max() if not summary.empty else None

    dates = sorted(summary["date"].unique())

    # ── Per-night data helper ──────────────────────────────────────────────────
    def _night_data(date):
        row          = summary[summary["date"] == date].iloc[0]
        night_ard    = arduino[arduino["date"] == date] if not arduino.empty else pd.DataFrame()
        night_stages = stages[stages["date"] == date]   if not stages.empty  else pd.DataFrame()
        hrv_row      = (hrv_sum[hrv_sum["date"] == date].iloc[0]
                        if (not hrv_sum.empty and date in hrv_sum["date"].values) else None)
        sleep_score   = row.get("overall_sleep_score", np.nan)
        env_score     = score_night(night_ard) if not night_ard.empty else np.nan
        sleep_latency = np.nan
        act_steps     = np.nan
        act_intensity = np.nan
        act_valid     = np.nan
        if nightly_df is not None and not nightly_df.empty and date in nightly_df["date"].values:
            nl_row        = nightly_df[nightly_df["date"] == date].iloc[0]
            sleep_latency = nl_row.get("sleep_latency_mins",     np.nan)
            act_steps     = nl_row.get("total_steps",             np.nan)
            act_intensity = nl_row.get("total_intensity_minutes", np.nan)
            act_valid     = nl_row.get("is_valid_activity_day",   np.nan)
        return (row, night_ard, night_stages, hrv_row,
                sleep_score, env_score, sleep_latency,
                act_steps, act_intensity, act_valid)

    # ── Stage bar helpers ──────────────────────────────────────────────────────
    def _stage_fig(night_stages, height, show_text, key):
        if night_stages.empty:
            return
        stage_dur = (
            night_stages.groupby("stage")["duration_min"]
            .sum()
            .reindex(["deep", "light", "rem", "awake"])
            .fillna(0)
        )
        total_min = stage_dur.sum()
        if total_min == 0:
            return
        fig = go.Figure()
        for s in ["deep", "light", "rem", "awake"]:
            pct = (stage_dur[s] / total_min) * 100
            hrs = stage_dur[s] / 60
            fig.add_trace(go.Bar(
                x=[pct], y=[""],
                orientation="h",
                name=STAGE_LABELS[s],
                marker_color=STAGE_COLOURS[s],
                text=f"{STAGE_LABELS[s]}<br>{_fmt_hours(hrs)}" if show_text else None,
                textposition="inside" if show_text else "none",
                hovertemplate=f"{STAGE_LABELS[s]}: {_fmt_hours(hrs)} ({pct:.0f}%)<extra></extra>",
            ))
        fig.update_layout(
            barmode="stack", height=height,
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#c8d4e8", size=11),
            margin=dict(l=0, r=0, t=0, b=0),
            showlegend=False,
            xaxis=dict(showticklabels=False, showgrid=False, range=[0, 100]),
            yaxis=dict(showticklabels=False, showgrid=False),
        )
        st.plotly_chart(fig, use_container_width=True, key=key)

    # ── Detail panel renderer ──────────────────────────────────────────────────
    def _render_detail(selected):
        (row, night_ard, night_stages, hrv_row,
         sleep_score, env_score, sleep_latency,
         act_steps, act_intensity, act_valid) = _night_data(selected)

        c1, c2, c3, c4 = st.columns([2, 1.2, 1.2, 1.2])
        with c1:
            st.markdown(f"#### {selected.strftime('%A, %d %b %Y') if hasattr(selected,'strftime') else selected}")
            if pd.notna(row.get("sleep_start")) and pd.notna(row.get("sleep_end")):
                st.caption(f"🕙 {row['sleep_start'].strftime('%H:%M')} → {row['sleep_end'].strftime('%H:%M')}")
        with c2:
            sc = int(sleep_score) if pd.notna(sleep_score) else None
            colour = _score_colour(sleep_score)
            label  = _score_label(sleep_score)
            st.markdown(f"""
<div style="text-align:center;background:{BG};border-radius:12px;padding:0.7rem;">
  <div style="font-size:2.2rem;font-weight:800;color:{colour};">{sc if sc else '—'}</div>
  <div style="font-size:0.75rem;color:#aaa;">Garmin Sleep Score</div>
  <div style="font-size:0.85rem;color:{colour};font-weight:600;">{label}</div>
</div>""", unsafe_allow_html=True)
        with c3:
            ec      = f"{env_score:.0f}" if pd.notna(env_score) else "—"
            ecolour = _score_colour(env_score)
            elabel  = _score_label(env_score)
            st.markdown(f"""
<div style="text-align:center;background:{BG};border-radius:12px;padding:0.7rem;">
  <div style="font-size:2.2rem;font-weight:800;color:{ecolour};">{ec}</div>
  <div style="font-size:0.75rem;color:#aaa;">Environment Score</div>
  <div style="font-size:0.85rem;color:{ecolour};font-weight:600;">{elabel}</div>
</div>""", unsafe_allow_html=True)
        with c4:
            lv = f"{sleep_latency:.0f}" if pd.notna(sleep_latency) else "—"
            lc = _latency_colour(sleep_latency)
            st.markdown(f"""
<div style="text-align:center;background:{BG};border-radius:12px;padding:0.7rem;">
  <div style="font-size:2.2rem;font-weight:800;color:{lc};">{lv}</div>
  <div style="font-size:0.75rem;color:#aaa;">Sleep Latency (min)</div>
  <div style="font-size:0.85rem;color:{lc};font-weight:600;">Time to sleep onset</div>
</div>""", unsafe_allow_html=True)

        st.markdown("---")
        _stage_fig(night_stages, height=70, show_text=True, key=f"detail_{selected}")

        insight = _auto_insight(row, env_score, hrv_row)
        st.markdown(
            f'<p style="color:{TEXT2};font-style:italic;margin:0.3rem 0 0.6rem 0;">'
            f'&#128161; {insight}</p>',
            unsafe_allow_html=True,
        )

        m_cols  = st.columns(5)
        metrics = []
        if pd.notna(row.get("total_sleep_hrs")):
            metrics.append(("⏱ Total", _fmt_hours(row["total_sleep_hrs"])))
        if pd.notna(row.get("deep_sleep_hrs")):
            metrics.append(("🌊 Deep", _fmt_hours(row["deep_sleep_hrs"])))
        if pd.notna(row.get("rem_sleep_hrs")):
            metrics.append(("🌀 REM", _fmt_hours(row["rem_sleep_hrs"])))
        if pd.notna(row.get("average_respiration")):
            metrics.append(("🌬 Resp", f"{row['average_respiration']:.0f}br/m"))
        if hrv_row is not None and pd.notna(hrv_row.get("last_night_avg")):
            metrics.append(("💚 HRV", f"{hrv_row['last_night_avg']:.0f}ms"))
        for col_ui, (lbl, val) in zip(m_cols, metrics[:5]):
            col_ui.metric(lbl, val)

        badges = _env_badges(night_ard)
        if badges:
            st.markdown("")
            badge_cols = st.columns(len(badges))
            colour_map = {"good": "#2ecc71", "warn": "#f39c12", "na": "#666"}
            for bc, (lbl, val, status) in zip(badge_cols, badges):
                c = colour_map[status]
                bc.markdown(f"""
<div style="text-align:center;padding:0.4rem 0.6rem;
            border:1px solid {c};border-radius:8px;
            color:{c};font-size:0.85rem;">
  {lbl}<br><b>{val}</b>
</div>""", unsafe_allow_html=True)

        if not pd.isna(act_valid):
            st.markdown("")
            if bool(act_valid):
                act_cols = st.columns(2)
                act_cols[0].metric("🏃 Steps", f"{int(act_steps):,}" if pd.notna(act_steps) else "—")
                act_cols[1].metric("🏃 Intensity min",
                                   f"{act_intensity:.0f} min" if pd.notna(act_intensity) else "—",
                                   help="Moderate HR zone (50–70% max HR) = 1×, vigorous (70%+ max HR) = 2×. Calculated by Garmin from heart rate data.")
            else:
                st.markdown(
                    '<p style="color:#666;font-size:0.78rem;margin:0.2rem 0;">🏃 Rest day / no activity data</p>',
                    unsafe_allow_html=True,
                )

    # ── Section 1 — Compact card grid ──────────────────────────────────────────
    grid_rows = [dates[i:i + 3] for i in range(0, len(dates), 3)]
    for row_dates in grid_rows:
        cols = st.columns(3)
        for col_ui, date in zip(cols, row_dates):
            with col_ui:
                (row, night_ard, night_stages, hrv_row,
                 sleep_score, env_score, sleep_latency,
                 act_steps, act_intensity, act_valid) = _night_data(date)

                has_data        = pd.notna(sleep_score)
                score_colour    = _score_colour(sleep_score)
                env_colour      = _score_colour(env_score)
                score_lbl       = _score_label(sleep_score)
                env_lbl         = _score_label(env_score)
                sleep_score_str = f"{int(sleep_score)}" if has_data else "—"
                env_score_str   = f"{env_score:.0f}" if pd.notna(env_score) else "—"

                sleep_start_str = ""
                sleep_end_str   = ""
                if pd.notna(row.get("sleep_start")) and pd.notna(row.get("sleep_end")):
                    sleep_start_str = row["sleep_start"].strftime("%H:%M")
                    sleep_end_str   = row["sleep_end"].strftime("%H:%M")

                is_best      = has_data and best_score is not None and sleep_score == best_score
                border_color = ACCENT if is_best else GRID

                st.markdown(f"""
<div style="
    background:{BG2};
    border:1px solid {border_color};
    border-radius:12px;
    padding:1rem;
    margin-bottom:0.5rem;
    min-height:160px;
">
  <p style="color:{TEXT};font-size:0.95rem;font-weight:600;margin:0;">
    {date.strftime('%a %d %b') if hasattr(date,'strftime') else date}
  </p>
  <p style="color:{TEXT2};font-size:0.75rem;margin:0 0 0.6rem;">
    {sleep_start_str} → {sleep_end_str}
  </p>
  <div style="display:flex;gap:1rem;margin-bottom:0.6rem;">
    <div style="flex:1;text-align:center;">
      <div style="font-size:1.6rem;font-weight:800;color:{score_colour};">{sleep_score_str}</div>
      <div style="font-size:0.65rem;color:{TEXT2};text-transform:uppercase;">Sleep Score</div>
      <div style="font-size:0.75rem;color:{score_colour};">{score_lbl}</div>
    </div>
    <div style="flex:1;text-align:center;">
      <div style="font-size:1.6rem;font-weight:800;color:{env_colour};">{env_score_str}</div>
      <div style="font-size:0.65rem;color:{TEXT2};text-transform:uppercase;">Env Score</div>
      <div style="font-size:0.75rem;color:{env_colour};">{env_lbl}</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

                _stage_fig(night_stages, height=50, show_text=False,
                           key=f"mini_{date}")
                clicked = st.button("View Details", key=f"btn_{date}",
                                    use_container_width=True, disabled=not has_data)
                if clicked:
                    st.session_state["selected_night"] = date

    # ── Section 2 — Detail panel ───────────────────────────────────────────────
    if st.session_state.get("selected_night") is not None:
        selected = st.session_state["selected_night"]
        if selected not in dates:
            st.session_state["selected_night"] = None
        else:
            st.markdown("---")
            st.markdown(
                f"### 📋 {selected.strftime('%A, %d %b %Y') if hasattr(selected,'strftime') else selected}"
            )
            if st.button("✕ Close", key="close_detail"):
                st.session_state["selected_night"] = None
                st.rerun()
            else:
                _render_detail(selected)

    # ── Weekly summary bar chart at bottom ────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📅 Weekly Overview")
    st.markdown(
        "<p style='color:#7a90b0; font-size:0.85rem; margin-top:-8px;'>"
        "How did your sleep and bedroom environment trend across the week?"
        "</p>",
        unsafe_allow_html=True,
    )
    chron_dates = sorted(summary["date"].unique())
    sleep_scores = [
        summary[summary["date"] == d]["overall_sleep_score"].values[0]
        if not summary[summary["date"] == d].empty else np.nan
        for d in chron_dates
    ]
    env_scores_list = [
        score_night(arduino[arduino["date"] == d])
        if not arduino.empty else np.nan
        for d in chron_dates
    ]
    date_labels = [
        d.strftime("%a %d %b") if hasattr(d, "strftime") else str(d)
        for d in chron_dates
    ]

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=date_labels, y=sleep_scores, name="Sleep Score",
        marker=dict(color="#6674cc", opacity=0.87, line=dict(width=0)),
    ))
    fig2.add_trace(go.Scatter(
        x=date_labels, y=env_scores_list, name="Env Score",
        mode="lines+markers",
        line=dict(color="#f39c12", width=2.5),
        marker=dict(color="#f39c12", size=10, symbol="circle",
                    line=dict(color="#ffffff", width=1.5)),
    ))
    fig2.add_shape(
        type="line",
        x0=0, x1=1, xref="paper",
        y0=80, y1=80, yref="y",
        line=dict(dash="dash", color="#7a90b0", width=1),
        opacity=0.4,
    )
    fig2.add_annotation(
        xref="paper", yref="y",
        x=1.02, y=80,
        text="Good",
        showarrow=False,
        font=dict(size=10, color="#7a90b0"),
        xanchor="left",
    )
    fig2.update_layout(
        height=320,
        plot_bgcolor=BG2, paper_bgcolor=BG,
        font=dict(color=TEXT, family="DM Mono, monospace"),
        legend=dict(orientation="h", y=1.08, x=0),
        yaxis=dict(range=[0, 105], zeroline=False, gridcolor=GRID),
        xaxis=dict(showgrid=False, tickfont=dict(color=TEXT2)),
        margin=dict(l=50, r=60, t=40, b=50),
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.markdown(
        "<span style='font-size:0.8rem; color:#7a90b0;'>"
        "Bars = Garmin sleep score. Line = environment score. Dashed line = score 80 threshold."
        "</span>",
        unsafe_allow_html=True,
    )
