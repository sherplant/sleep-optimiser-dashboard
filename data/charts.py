"""
data/charts.py — Shared Plotly theme, design tokens, and chart helper functions.
All views import constants and builders from here to keep styling consistent.
"""

import pandas as pd
import numpy as np
import plotly.graph_objects as go

# ── Design tokens ─────────────────────────────────────────────────────────────
BG     = "#0a0e1a"   # page background
BG2    = "#0d1220"   # card / panel background
GRID   = "#1e2a42"   # grid lines and borders
TEXT   = "#c8d4e8"   # primary text
TEXT2  = "#7a90b0"   # muted / secondary text
ACCENT = "#5b9cf6"   # blue accent

STAGE_COLORS = {
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


# ── Internal helpers ──────────────────────────────────────────────────────────

def _hex_to_rgba(hex_color: str, alpha: float = 0.15) -> str:
    """Convert '#rrggbb' to 'rgba(r,g,b,alpha)'."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# ── Shared layout factory ─────────────────────────────────────────────────────

def base_layout(height: int = 400, **kwargs) -> dict:
    """
    Return a dict suitable for go.Figure(layout=go.Layout(**base_layout(...))).
    Caller can override any key via kwargs.
    """
    layout = dict(
        height=height,
        paper_bgcolor=BG,
        plot_bgcolor=BG2,
        font=dict(color=TEXT, family="DM Mono, monospace", size=11),
        margin=dict(l=52, r=20, t=32, b=44),
        hovermode="x unified",
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT, size=10),
        ),
        xaxis=dict(
            gridcolor=GRID,
            zeroline=False,
            tickfont=dict(color=TEXT2, size=10),
            linecolor=GRID,
        ),
        yaxis=dict(
            gridcolor=GRID,
            zeroline=False,
            tickfont=dict(color=TEXT2, size=10),
            linecolor=GRID,
        ),
    )
    layout.update(kwargs)
    return layout


# ── Chart builders ────────────────────────────────────────────────────────────

def correlation_heatmap(corr_pivot: pd.DataFrame, height: int = 300) -> go.Figure:
    """
    Annotated correlation heatmap.
    corr_pivot should be a DataFrame with env metrics as index and sleep metrics
    as columns; cell values are Pearson r ∈ [-1, 1].
    """
    if corr_pivot.empty:
        return go.Figure()

    z = corr_pivot.values.astype(float)
    x_labels = [c.replace("_", " ").title() for c in corr_pivot.columns]
    y_labels = [c.replace("_", " ").title() for c in corr_pivot.index]
    text = [
        [f"{v:.2f}" if not np.isnan(v) else "" for v in row]
        for row in z
    ]

    fig = go.Figure(go.Heatmap(
        z=z,
        x=x_labels,
        y=y_labels,
        text=text,
        texttemplate="%{text}",
        textfont=dict(size=10, color=TEXT),
        colorscale="RdBu",
        zmid=0,
        zmin=-1,
        zmax=1,
        showscale=True,
        colorbar=dict(
            thickness=12,
            len=0.85,
            tickfont=dict(color=TEXT2, size=9),
            title=dict(text="r", font=dict(color=TEXT2, size=10)),
        ),
    ))

    layout = base_layout(height=height)
    layout["xaxis"]["tickangle"] = 0
    layout["margin"] = dict(l=130, r=20, t=30, b=60)
    fig.update_layout(**layout)
    return fig


def stage_radar(
    stage_avgs: pd.DataFrame,
    metrics: list,
    labels: list,
    height: int = 340,
) -> go.Figure:
    """
    Polar radar chart with one trace per sleep stage.

    Parameters
    ----------
    stage_avgs : DataFrame with a 'stage' column + metric columns
    metrics    : list of column names to plot
    labels     : display labels matching metrics (same length)
    """
    if stage_avgs.empty or "stage" not in stage_avgs.columns or not metrics:
        return go.Figure()

    fig = go.Figure()

    for _, row in stage_avgs.iterrows():
        stage = str(row["stage"])
        values = [float(row.get(m, 0) or 0) for m in metrics]
        # Normalise each metric to 0-100 for comparable radar axes
        max_val = max(values) if max(values) > 0 else 1
        values_norm = [v / max_val * 100 for v in values]
        # Close the polygon
        values_closed = values_norm + [values_norm[0]]
        labels_closed  = labels + [labels[0]]

        color = STAGE_COLORS.get(stage, ACCENT)
        fig.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=labels_closed,
            fill="toself",
            name=STAGE_LABELS.get(stage, stage.capitalize()),
            line=dict(color=color, width=2),
            fillcolor=_hex_to_rgba(color, 0.18),
        ))

    fig.update_layout(
        height=height,
        paper_bgcolor=BG,
        font=dict(color=TEXT, size=10),
        polar=dict(
            bgcolor=BG2,
            radialaxis=dict(
                visible=True,
                gridcolor=GRID,
                tickfont=dict(color=TEXT2, size=9),
                linecolor=GRID,
                range=[0, 110],
            ),
            angularaxis=dict(
                gridcolor=GRID,
                tickfont=dict(color=TEXT, size=10),
                linecolor=GRID,
            ),
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=TEXT, size=10),
        ),
        margin=dict(l=40, r=40, t=30, b=30),
    )
    return fig
