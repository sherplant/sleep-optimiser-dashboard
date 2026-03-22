"""
views/explorer.py  —  View #4: Sleep Stage Explorer
Cross-night pattern analysis: correlations, stage environment breakdown,
scatter plots, and the environment optimiser insight panel.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.loader import (
    load_arduino, load_sleep_stages, load_sleep_summary,
    load_hrv_summary, load_heart_rate_summary, load_body_battery_summary,
)
from data.processor import (
    compute_environment_score, align_arduino_to_stages,
    per_stage_averages, build_nightly_summary, compute_correlations,
    ENV_COLS, SLEEP_COLS,
)
from data.charts import (
    BG, BG2, GRID, TEXT, TEXT2, ACCENT, STAGE_COLORS,
    base_layout, correlation_heatmap, stage_radar,
)


def _scatter(nightly, x_col, y_col, x_label, y_label, height=280):
    keep_cols = list(dict.fromkeys(c for c in [x_col, y_col, "night", "overall_sleep_score"] if c in nightly.columns))
    df = nightly[keep_cols].dropna(subset=[x_col, y_col])
    if df.empty:
        return go.Figure()
    layout = base_layout(height=height)
    layout["xaxis"]["title"] = dict(text=x_label, font=dict(color=TEXT2, size=10))
    layout["yaxis"]["title"] = dict(text=y_label, font=dict(color=TEXT2, size=10))
    layout["margin"] = dict(l=50, r=60, t=30, b=50)
    fig = go.Figure(layout=go.Layout(**layout))
    if "overall_sleep_score" in df.columns:
        marker = dict(
            size=14,
            color=df["overall_sleep_score"],
            colorscale="RdYlGn",
            cmin=70, cmax=90,
            showscale=True,
            colorbar=dict(
                title=dict(text="Sleep Score", font=dict(color=TEXT2, size=10)),
                thickness=12,
                len=0.75,
                tickfont=dict(color=TEXT2, size=9),
            ),
            line=dict(color="#ffffff", width=1.5),
        )
    else:
        marker = dict(
            size=14,
            color=ACCENT,
            opacity=0.85,
            line=dict(color="#ffffff", width=1.5),
        )
    fig.add_trace(go.Scatter(
        x=df[x_col], y=df[y_col],
        mode="markers+text",
        text=[str(n) for n in df["night"]] if "night" in df.columns else None,
        textposition="top center",
        textfont=dict(color=TEXT2, size=8),
        marker=marker,
        showlegend=False,
        hovertemplate=f"<b>%{{text}}</b><br>{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>",
    ))
    if len(df) >= 2:
        m, b = np.polyfit(df[x_col].astype(float), df[y_col].astype(float), 1)
        x_range = np.linspace(df[x_col].min(), df[x_col].max(), 50)
        fig.add_trace(go.Scatter(
            x=x_range, y=m * x_range + b,
            mode="lines", line=dict(color=ACCENT, width=2, dash="dot"),
            opacity=0.6,
            showlegend=False, hoverinfo="skip",
        ))
        r = df[[x_col, y_col]].corr().iloc[0, 1]
        fig.add_annotation(
            text=f"r = {r:.2f}", xref="paper", yref="paper",
            x=0.98, y=0.05, showarrow=False,
            font=dict(color=TEXT2, size=10, family="DM Mono"),
        )
    fig.update_layout(showlegend=False)
    return fig


def _stage_bar(sleep_sum, height=240):
    if sleep_sum.empty:
        return go.Figure()
    df = sleep_sum.copy()
    df["night"] = df["date"].apply(
        lambda d: d.strftime("%d %b") if hasattr(d, "strftime") else str(d)
    )
    layout = base_layout(height=height, barmode="stack")
    fig = go.Figure(layout=go.Layout(**layout))
    for stage, col, color in [
        ("Deep",  "deep_sleep_mins",  STAGE_COLORS["deep"]),
        ("Light", "light_sleep_mins", STAGE_COLORS["light"]),
        ("REM",   "rem_sleep_mins",   STAGE_COLORS["rem"]),
        ("Awake", "awake_mins",       STAGE_COLORS["awake"]),
    ]:
        if col in df.columns:
            fig.add_trace(go.Bar(
                x=df["night"], y=df[col], name=stage,
                marker_color=color, opacity=0.87,
                hovertemplate=f"<b>%{{x}}</b><br>{stage}: %{{y:.0f}} min<extra></extra>",
            ))
    return fig


def _optimiser_panel(nightly):
    st.markdown("#### 🎯 Environment Optimiser")
    st.markdown(
        "<p style='color:#7a90b0;font-size:0.85rem;margin-top:-8px;'>"
        "Based on your top performing nights, here's what your bedroom conditions looked like — "
        "and what to aim for tonight.</p>",
        unsafe_allow_html=True,
    )
    if "overall_sleep_score" not in nightly.columns or len(nightly) < 2:
        st.info("Need at least 2 nights of data to compute personal optimals.")
        return

    good   = nightly[nightly["overall_sleep_score"] >= nightly["overall_sleep_score"].median()]
    latest = nightly.sort_values("date").iloc[-1] if "date" in nightly.columns else None

    metrics = [
        ("avg_temp",      "Temperature", "°C",  "{:.1f}"),
        ("avg_humidity",  "Humidity",    "%",   "{:.1f}"),
        ("avg_env_score", "Env Score",   "",    "{:.0f}"),
    ]

    findings = []
    for col, label, unit, fmt in metrics:
        if col not in nightly.columns:
            continue
        opt_val    = good[col].mean()
        r          = nightly[[col, "overall_sleep_score"]].dropna().corr().iloc[0, 1]
        latest_val = latest[col] if latest is not None and col in latest.index and not pd.isna(latest[col]) else None
        on_target  = (
            latest_val is not None
            and opt_val != 0
            and abs(latest_val - opt_val) / abs(opt_val) <= 0.10
        )
        findings.append((col, label, unit, fmt, opt_val, r, latest_val, on_target))

    if not findings:
        st.info("Not enough data yet.")
        return

    cols = st.columns(len(findings))
    for i, (col, label, unit, fmt, opt_val, r, latest_val, on_target) in enumerate(findings):
        if r > 0.1:
            direction_html = f"<span style='color:#2ecc71;'>↑ Higher on your better nights</span>"
        elif r < -0.1:
            direction_html = f"<span style='color:#e74c3c;'>↓ Lower on your better nights</span>"
        else:
            direction_html = f"<span style='color:{TEXT2};'>~ No clear pattern</span>"

        val_str = fmt.format(opt_val) + unit

        if latest_val is not None:
            if on_target:
                target_html = "<p style='color:#2ecc71;font-size:0.75rem;margin:6px 0 0;'>✅ Last night was on target</p>"
            else:
                latest_str = fmt.format(latest_val) + unit
                aim_str    = fmt.format(opt_val) + unit
                target_html = (
                    f"<p style='color:#f39c12;font-size:0.75rem;margin:6px 0 0;'>"
                    f"⚠️ Last night: {latest_str} — aim for ~{aim_str}</p>"
                )
        else:
            target_html = ""

        cols[i].markdown(
            f"<div style='background:{BG2};border:1px solid {GRID};"
            f"border-radius:12px;padding:16px;text-align:center;'>"
            f"<p style='color:{TEXT2};font-size:0.72rem;text-transform:uppercase;"
            f"letter-spacing:0.08em;margin:0 0 6px;'>{label}</p>"
            f"<p style='color:{ACCENT};font-size:1.5rem;font-family:DM Serif Display,serif;"
            f"margin:0 0 4px;'>{val_str}</p>"
            f"<p style='font-size:0.75rem;margin:0;'>{direction_html}</p>"
            f"{target_html}"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── Bottom recommendation line ────────────────────────────────────────
    recommendations = []
    opt_temp     = next((f[4] for f in findings if f[0] == "avg_temp"),     None)
    opt_humidity = next((f[4] for f in findings if f[0] == "avg_humidity"), None)
    opt_env      = next((f[4] for f in findings if f[0] == "avg_env_score"),None)

    if opt_temp     is not None: recommendations.append(f"~{opt_temp:.1f}°C")
    if opt_humidity is not None: recommendations.append(f"~{opt_humidity:.0f}% humidity")
    if opt_env      is not None: recommendations.append(f"environment score above {opt_env:.0f}")

    if recommendations:
        rec_str = ", ".join(recommendations)
        st.markdown(
            f"<div style='background:{BG2}; border-left: 3px solid {ACCENT}; "
            f"border-radius: 8px; padding: 0.75rem 1rem; margin-top: 0.8rem;'>"
            f"<p style='color:#c8d4e8; margin:0; font-size:0.9rem;'>"
            f"🎯 <strong>Tonight's targets:</strong> Aim for {rec_str} "
            f"to replicate your best nights.</p>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render(garmin: dict, arduino: "pd.DataFrame", nightly_df: "pd.DataFrame" = None):
    import pandas as _pd  # local alias to avoid shadowing
    st.markdown("## Your Sleep Story")
    st.markdown(
        "<p style='color:#7a90b0;font-size:0.85rem;margin-top:-12px;'>"
        "Patterns, relationships and personalised recommendations from your sleep data.</p>",
        unsafe_allow_html=True,
    )

    # Use pre-loaded data passed from app.py instead of reloading
    stages_all = garmin.get("stages",       _pd.DataFrame())
    sleep_sum  = garmin.get("summary",      _pd.DataFrame())
    hrv_sum    = garmin.get("hrv_summary",  _pd.DataFrame())
    hr_sum     = garmin.get("hr_summary",   _pd.DataFrame())
    bb_sum     = garmin.get("bb_summary",   _pd.DataFrame())

    nightly = build_nightly_summary(arduino, sleep_sum, hrv_sum, hr_sum, bb_sum)
    arduino_staged = arduino.copy() if not arduino.empty else _pd.DataFrame()
    if not arduino.empty and not stages_all.empty:
        arduino_staged = align_arduino_to_stages(arduino, stages_all)

    tab1, tab2, tab3 = st.tabs([
        "📊  Sleep Patterns",
        "🔍  Dig Deeper",
        "🎯  Env Optimiser",
    ])

    with tab1:
        src = nightly if not nightly.empty else sleep_sum
        if not src.empty:
            st.markdown("#### 🌙 Your Nightly Sleep Breakdown")
            st.plotly_chart(_stage_bar(src), use_container_width=True)
        else:
            st.info("No sleep summary data found.")

        st.markdown("---")
        if not stages_all.empty and "stage" in arduino_staged.columns:
            st.markdown("#### 🌡️ Your Bedroom Conditions by Sleep Stage")
            stage_avgs = per_stage_averages(arduino_staged)
            if not stage_avgs.empty:
                # ── Step 1 — Data prep ───────────────────────────────────────────
                rename_map = {
                    "temp_c":       "Temp (°C)",
                    "humidity_pct": "Humidity (%)",
                    "light_lux":    "Light (lux)",
                    "restlessness": "Restlessness",
                    "env_score":    "Env Score",
                }
                score_cols  = ["temp_score", "light_score", "humidity_score", "rest_score"]
                drop_extra  = (
                    ["avg_restlessness"]
                    if "avg_restlessness" in stage_avgs.columns and "restlessness" in stage_avgs.columns
                    else []
                )
                disp = (
                    stage_avgs
                    .drop(columns=[c for c in score_cols + drop_extra if c in stage_avgs.columns])
                    .rename(columns=rename_map)
                    .round(2)
                )
                STAGE_COLOR_MAP = {
                    "awake": STAGE_COLORS.get("awake", "#e05c5c"),
                    "deep":  STAGE_COLORS.get("deep",  "#1e4d8c"),
                    "light": STAGE_COLORS.get("light", "#4a90d9"),
                    "rem":   STAGE_COLORS.get("rem",   "#9b5fc0"),
                }

                # Keep stage as regular column, don't set as index
                if "stage" in disp.columns:
                    disp["stage"] = disp["stage"].apply(
                        lambda s: f"● {str(s).capitalize()}"
                    )
                    disp = disp.rename(columns={"stage": "Stage"})

                # Reset integer index so Stage is column 0
                disp = disp.reset_index(drop=True)

                # ── Step 2 — Styling ─────────────────────────────────────────────
                def highlight_best_worst(col):
                    if col.name == "Stage":
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
                    if col.name != "Stage":
                        return [""] * len(col)
                    styles = []
                    for val in col:
                        label = str(val).replace("●", "").strip().lower()
                        colour = STAGE_COLOR_MAP.get(label, "#c8d4e8")
                        styles.append(f"color: {colour}; font-weight: 700;")
                    return styles

                fmt_tbl = {c: "{:.2f}" for c in disp.columns if c not in ["Stage", "Restlessness"]}
                if "Restlessness" in disp.columns:
                    fmt_tbl["Restlessness"] = "{:.3f}"
                numeric_cols = [c for c in disp.columns if c != "Stage"]
                best_env_idx = disp["Env Score"].idxmax() if "Env Score" in disp.columns else None

                def bold_best_env(row):
                    if best_env_idx is not None and row.name == best_env_idx:
                        return ["font-weight: bold;"] * len(row)
                    return [""] * len(row)

                styled = (
                    disp.style.format(fmt_tbl)
                    .set_properties(subset=numeric_cols, **{"text-align": "center"})
                    .apply(colour_stage_text, axis=0)
                    .apply(bold_best_env, axis=1)
                    .apply(highlight_best_worst, axis=0)
                )
                st.dataframe(styled, use_container_width=True, hide_index=True)
                st.markdown(
                    "<span style='font-size:0.8rem; color:#7a90b0;'>"
                    "<span style='color:#2ecc71'>●</span> Best &nbsp;·&nbsp; "
                    "<span style='color:#e74c3c'>●</span> Worst "
                    "— per metric across all sleep stages"
                    "</span>",
                    unsafe_allow_html=True,
                )

                # ── Step 3 — Normalised grouped bar chart ────────────────────────
                metric_cols = [c for c in
                               ["Temp (°C)", "Humidity (%)", "Light (lux)", "Restlessness", "Env Score"]
                               if c in disp.columns]
                if len(metric_cols) >= 2 and len(disp) >= 2:
                    # Capture stage labels before norm loses them (disp index is integer after reset_index)
                    bar_stage_labels = (
                        disp["Stage"].tolist() if "Stage" in disp.columns
                        else [str(i) for i in disp.index]
                    )
                    norm      = disp[metric_cols].copy().astype(float)
                    col_range = (norm.max() - norm.min()).replace(0, 1)
                    norm      = (norm - norm.min()) / col_range

                    layout          = base_layout(height=300, barmode="group")
                    layout["yaxis"] = {
                        **layout.get("yaxis", {}),
                        "title": dict(text="Relative Level (Low → High)",
                                      font=dict(size=10, color=TEXT2)),
                    }
                    stage_color_map = {
                        "deep":  STAGE_COLORS["deep"],
                        "light": STAGE_COLORS["light"],
                        "rem":   STAGE_COLORS["rem"],
                        "awake": STAGE_COLORS["awake"],
                    }
                    fig = go.Figure(layout=go.Layout(**layout))
                    for i, stage_label in enumerate(bar_stage_labels):
                        clean_label = str(stage_label).replace("●", "").strip().lower()
                        color = stage_color_map.get(clean_label, ACCENT)
                        fig.add_trace(go.Bar(
                            name=clean_label.capitalize(),
                            x=metric_cols,
                            y=norm.iloc[i][metric_cols].tolist(),
                            marker_color=color,
                            opacity=0.87,
                            hovertemplate=(
                                "<b>%{x}</b><br>"
                                + clean_label.capitalize()
                                + ": %{y:.2f}<extra></extra>"
                            ),
                        ))
                    fig.update_layout(
                        bargap=0.5,
                        bargroupgap=0.05,
                    )
                    for i in range(1, len(metric_cols)):
                        fig.add_vline(
                            x=i - 0.5,
                            line=dict(color="#1e2a42", width=1.5, dash="solid"),
                            layer="below",
                        )
                    st.markdown("---")
                    st.markdown("#### 🏆 Which Stage Had the Best Conditions?")
                    st.plotly_chart(fig, use_container_width=True)
                    st.markdown(
                        "<span style='font-size:0.8rem; color:#7a90b0;'>"
                        "Metrics are scaled from 0–1 across sleep stages (0 = lowest, 1 = highest), "
                        "making it easy to compare different measurements at a glance."
                        "</span>",
                        unsafe_allow_html=True,
                    )

        # ── Correlation heatmap + insights (merged from old Correlations tab) ──
        st.markdown("---")
        st.markdown("#### 🔍 Which Environment Factors Correlate With Better Sleep?")
        corr = compute_correlations(nightly)
        if not corr.empty:
            _RAW_ENV_ROWS = ["avg_temp", "avg_humidity", "light_score", "avg_restlessness", "avg_env_score"]
            _CORR_Y_LABELS = {
                "avg_temp":         "Temperature",
                "avg_humidity":     "Humidity",
                "light_score":      "Room Darkness *",
                "avg_restlessness": "Restlessness",
                "avg_env_score":    "Environment Score",
            }
            _CORR_X_LABELS = {
                "overall_sleep_score": "Sleep Score",
                "deep_sleep_mins":     "Deep Sleep",
                "light_sleep_mins":    "Light Sleep",
                "rem_sleep_mins":      "REM Sleep",
                "awake_mins":          "Awake Time",
                "duration_hours":      "Duration",
            }
            keep_rows = [r for r in _RAW_ENV_ROWS if r in corr.index]
            corr_disp = corr.loc[keep_rows].dropna(how="all")
            corr_disp = corr_disp.rename(index=_CORR_Y_LABELS, columns=_CORR_X_LABELS)

            # ── Bubble chart ──────────────────────────────────────────────────
            x_labels_bubble = list(corr_disp.columns)
            y_labels_bubble = list(corr_disp.index)
            fig_bubble = go.Figure()
            for y_lbl in y_labels_bubble:
                for x_lbl in x_labels_bubble:
                    r_val = corr_disp.loc[y_lbl, x_lbl]
                    if pd.isna(r_val):
                        continue
                    colour = "#5b9cf6" if r_val >= 0 else "#e05c5c"
                    size   = max(4, abs(r_val) * 60)
                    if "Room Darkness" in y_lbl:
                        hover = (
                            f"<b>Room Darkness * vs {x_lbl}</b><br>"
                            f"r = {r_val:.2f}<br>"
                            f"<i>* Averaged across full sleep window — not stage-specific.<br>"
                            f"Low nightly variance means this correlation should be treated with caution.</i>"
                            f"<extra></extra>"
                        )
                    else:
                        hover = (
                            f"<b>{y_lbl} vs {x_lbl}</b><br>"
                            f"r = {r_val:.2f}<extra></extra>"
                        )
                    fig_bubble.add_trace(go.Scatter(
                        x=[x_lbl], y=[y_lbl],
                        mode="markers",
                        marker=dict(size=size, color=colour, opacity=0.85,
                                    line=dict(color=BG, width=1)),
                        hovertemplate=hover,
                        showlegend=False,
                    ))
            bubble_height = max(320, len(y_labels_bubble) * 90)
            fig_bubble.update_layout(
                height=bubble_height,
                showlegend=False,
                paper_bgcolor=BG,
                plot_bgcolor=BG2,
                font=dict(color=TEXT, family="DM Mono, monospace", size=10),
                margin=dict(l=130, r=20, t=20, b=80),
                xaxis=dict(
                    type="category",
                    tickfont=dict(color=TEXT2, size=10),
                    tickangle=-20,
                    showgrid=False, zeroline=False,
                    categoryorder="array", categoryarray=x_labels_bubble,
                ),
                yaxis=dict(
                    type="category",
                    tickfont=dict(color=TEXT2, size=10),
                    showgrid=False, zeroline=False,
                    categoryorder="array", categoryarray=y_labels_bubble[::-1],
                ),
            )
            st.plotly_chart(fig_bubble, use_container_width=True)
            st.markdown(
                "<span style='font-size:0.8rem; color:#7a90b0;'>"
                "Each circle shows how strongly a nightly average environment factor correlates "
                "with a nightly sleep metric across your 7 nights.<br>"
                "Larger circles = stronger relationship. "
                "<span style='color:#5b9cf6'>●</span> tends to improve sleep &nbsp;·&nbsp; "
                "<span style='color:#e05c5c'>●</span> tends to reduce sleep quality."
                "</span>",
                unsafe_allow_html=True,
            )

            st.markdown("---")
            # ── What Stands Out insight cards ─────────────────────────────────
            LABEL_MAP = {
                "avg_temp":            "room temperature",
                "avg_humidity":        "humidity",
                "light_score":         "room darkness",
                "avg_env_score":       "environment score",
                "avg_restlessness":    "restlessness",
                "overall_sleep_score": "sleep score",
                "deep_sleep_mins":     "deep sleep",
                "light_sleep_mins":    "light sleep",
                "rem_sleep_mins":      "REM sleep",
                "awake_mins":          "time awake",
                "duration_hours":      "sleep duration",
                "avg_hrv":             "HRV",
                "avg_hr":              "heart rate",
            }

            def _lbl(col):
                return LABEL_MAP.get(col, col.replace("_", " "))

            def _strength(r):
                a = abs(r)
                if a >= 0.7: return "strong"
                if a >= 0.4: return "moderate"
                return "weak"

            EMOJI_MAP = {
                "avg_temp":          "🌡️",
                "avg_humidity":      "💧",
                "light_score":       "💡",
                "avg_env_score":     "🌿",
                "avg_restlessness":  "🛏️",
            }

            def _emoji(col):
                return EMOJI_MAP.get(col, "📊")

            def _insight_sentence(env_var, sleep_var, r):
                env_lbl   = _lbl(env_var)
                sleep_lbl = _lbl(sleep_var)
                strength  = _strength(r)
                emoji     = _emoji(env_var)
                if r > 0:
                    return (
                        f"{emoji} <strong>Your {sleep_lbl} tends to be better on nights "
                        f"when {env_lbl} is higher</strong> — "
                        f"a {strength} pattern across your {len(nightly)} nights."
                    )
                else:
                    return (
                        f"{emoji} <strong>Higher {env_lbl} appears linked to worse {sleep_lbl}</strong> — "
                        f"worth watching across future nights. {strength.capitalize()} pattern."
                    )

            # Filter to raw sensor rows only before generating insight cards
            _RAW_CARD_ROWS = ["avg_temp", "avg_humidity", "light_score", "avg_restlessness", "avg_env_score"]
            corr_raw = corr.loc[[r for r in _RAW_CARD_ROWS if r in corr.index]].dropna(how="all")
            st.markdown("#### 💡 What Your Data Is Telling You")
            flat     = corr_raw.abs().stack().sort_values(ascending=False)
            seen_env = set()
            cards    = 0
            for (env_var, sleep_var), _ in flat.items():
                if cards >= 4:
                    break
                if env_var in seen_env:
                    continue
                seen_env.add(env_var)
                r_val = corr_raw.loc[env_var, sleep_var]
                sentence = _insight_sentence(env_var, sleep_var, r_val)
                border   = "#2ecc71" if r_val > 0 else "#e74c3c"
                st.markdown(f"""
                <div style="
                    background:{BG2};
                    border-left: 3px solid {border};
                    border-radius: 8px;
                    padding: 0.75rem 1rem;
                    margin-bottom: 0.6rem;
                ">
                    <p style="color:#c8d4e8; margin:0; font-size:0.9rem;">{sentence}</p>
                    <p style="color:#7a90b0; margin:0.2rem 0 0; font-size:0.75rem;">
                        r = {r_val:.2f} &nbsp;·&nbsp; based on {len(nightly)} nights
                    </p>
                </div>
                """, unsafe_allow_html=True)
                cards += 1
            st.markdown(
                "<span style='font-size:0.8rem; color:#7a90b0;'>"
                "⚠️ Room darkness is based on a calibrated score (dark = 100, toilet light = 70, "
                "bedside lamp = 40, bright = 0) rather than raw lux values. "
                "All findings are exploratory — 7 nights is a small sample."
                "</span>",
                unsafe_allow_html=True,
            )
        else:
            st.info("Need more nights of data to compute meaningful correlations.")

    with tab2:
        if nightly.empty:
            st.info("No cross-night data available.")
        else:
            LABEL_MAP = {
                "avg_temp":            "Avg Temperature (°C)",
                "avg_humidity":        "Avg Humidity (%)",
                "avg_light":           "Avg Light Level (lux)",
                "avg_env_score":       "Environment Score",
                "rest_score":          "Restlessness Score",
                "temp_score":          "Temperature Score",
                "light_score":         "Light Score",
                "humidity_score":      "Humidity Score",
                "overall_sleep_score": "Sleep Score",
                "deep_sleep_mins":     "Deep Sleep (min)",
                "light_sleep_mins":    "Light Sleep (min)",
                "rem_sleep_mins":      "REM Sleep (min)",
                "awake_mins":          "Awake Time (min)",
                "duration_hours":      "Sleep Duration (hrs)",
                "avg_hrv":             "Avg HRV (ms)",
                "avg_hr":              "Avg Heart Rate (bpm)",
            }

            def _label(col):
                return LABEL_MAP.get(col, col.replace("_", " ").title())

            # ── Section 3 — Interactive Scatter ───────────────────────────────
            st.markdown("---")
            st.markdown("#### 🔍 How Does Your Environment Shape Your Sleep?")
            st.markdown(
                "<span style='font-size:0.8rem; color:#7a90b0;'>"
                "⚠️ Exploratory only — 7 nights is too small a sample for reliable conclusions. "
                "Use to spot patterns, not to draw conclusions."
                "</span>",
                unsafe_allow_html=True,
            )
            env_options   = [c for c in ENV_COLS   if c in nightly.columns]
            sleep_options = [c for c in SLEEP_COLS  if c in nightly.columns]

            if not env_options or not sleep_options or len(nightly) < 2:
                st.info("Need at least 2 nights of data with matching env and sleep metrics.")
            else:
                env_labels   = [_label(c) for c in env_options]
                sleep_labels = [_label(c) for c in sleep_options]

                c1, c2 = st.columns(2)
                x_label_sel = c1.selectbox("X axis (environment)", env_labels,
                                           index=env_labels.index(_label("avg_temp")) if _label("avg_temp") in env_labels else 0)
                y_label_sel = c2.selectbox("Y axis (sleep metric)", sleep_labels,
                                           index=sleep_labels.index(_label("overall_sleep_score")) if _label("overall_sleep_score") in sleep_labels else 0)
                x_col = env_options[env_labels.index(x_label_sel)]
                y_col = sleep_options[sleep_labels.index(y_label_sel)]

                st.plotly_chart(
                    _scatter(nightly, x_col, y_col, _label(x_col), _label(y_col), height=320),
                    use_container_width=True,
                )

        # ── Activity × Sleep scatter plots (moved from old Correlations tab) ──
        if (nightly_df is not None and not nightly_df.empty
                and "total_steps" in nightly_df.columns
                and "is_valid_activity_day" in nightly_df.columns):
            act_n = nightly_df[nightly_df["is_valid_activity_day"] == True].copy()
            if "night" not in act_n.columns:
                act_n["night"] = act_n["date"].apply(
                    lambda d: d.strftime("%d %b") if hasattr(d, "strftime") else str(d)
                )
            if len(act_n) >= 2:
                st.markdown("---")
                st.markdown("#### 🏃 Does Being More Active Lead to Better Sleep?")
                st.markdown(
                    "<span style='font-size:0.8rem; color:#7a90b0;'>"
                    "⚠️ Exploratory only — 7 nights is too small a sample for reliable conclusions. "
                    "Use to spot patterns, not to draw conclusions."
                    "</span>",
                    unsafe_allow_html=True,
                )
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown(
                        f"<p style='color:{TEXT2};font-size:0.78rem;"
                        f"text-transform:uppercase;letter-spacing:0.07em;"
                        f"margin-bottom:4px;'>Total Steps vs Sleep Score</p>",
                        unsafe_allow_html=True,
                    )
                    if "overall_sleep_score" in act_n.columns:
                        st.plotly_chart(
                            _scatter(act_n, "total_steps", "overall_sleep_score",
                                     "Total Steps", "Sleep Score", height=240),
                            use_container_width=True,
                        )
                with col_b:
                    st.markdown(
                        f"<p style='color:{TEXT2};font-size:0.78rem;"
                        f"text-transform:uppercase;letter-spacing:0.07em;"
                        f"margin-bottom:4px;'>Intensity Minutes vs Deep Sleep</p>",
                        unsafe_allow_html=True,
                    )
                    if "deep_sleep_mins" in act_n.columns:
                        st.plotly_chart(
                            _scatter(act_n, "total_intensity_minutes", "deep_sleep_mins",
                                     "Intensity Min", "Deep Sleep (min)", height=240),
                            use_container_width=True,
                        )
                        st.caption(
                            "Intensity minutes = moderate + (vigorous × 2), derived from "
                            "Garmin HR zones. Vigorous minutes weighted 2× per WHO guidelines."
                        )

    with tab3:
        _optimiser_panel(nightly)
