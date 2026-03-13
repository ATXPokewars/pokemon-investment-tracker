"""
Compare page: Overlay multiple products on one chart.
Supports both actual prices and normalized (index 100) views.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from database.models import get_connection
from database import operations as db
from analysis.comparison import normalize_prices, calculate_comparison_stats

st.title("⚖️ Compare Products")

# --- Load tracked products ---
conn = get_connection()
products = db.get_all_tracked_products(conn)

if not products:
    st.info("No products tracked yet. Search and track some products first.")
    conn.close()
    st.stop()

product_names = {p["id"]: f"{p['name']} ({p.get('set_name', '')})" for p in products}

# --- Product selection ---
selected_ids = st.multiselect(
    "Select products to compare (2-5 recommended)",
    options=list(product_names.keys()),
    format_func=lambda x: product_names[x],
    max_selections=5,
)

if len(selected_ids) < 2:
    st.info("Select at least 2 products to compare.")
    conn.close()
    st.stop()

# --- Chart mode ---
view_mode = st.radio(
    "View mode",
    ["Actual Prices ($)", "Normalized (Index 100)"],
    horizontal=True,
)

# --- Load price data ---
prices_dict = {}
for pid in selected_ids:
    snapshots = db.get_daily_snapshots(conn, pid)
    if snapshots:
        df = pd.DataFrame(snapshots)
        df["date"] = pd.to_datetime(df["date"])
        series = df.set_index("date")["tcg_market_price"].dropna()
        if not series.empty:
            prices_dict[product_names[pid]] = series

    # Fallback to individual price points
    if product_names[pid] not in prices_dict:
        history = db.get_price_history(conn, pid, source="tcgplayer")
        market_points = [h for h in history if h["price_type"] == "market"]
        if market_points:
            df = pd.DataFrame(market_points)
            df["observed_date"] = pd.to_datetime(df["observed_date"])
            series = df.set_index("observed_date")["price"].dropna()
            if not series.empty:
                prices_dict[product_names[pid]] = series

conn.close()

if not prices_dict:
    st.warning("No price data available for selected products.")
    st.stop()

# --- Build chart ---
if view_mode == "Normalized (Index 100)":
    chart_data = normalize_prices(prices_dict)
    y_title = "Index (100 = First Day)"
else:
    chart_data = prices_dict
    y_title = "Price (USD)"

colors = ["#FF6B35", "#2196F3", "#4CAF50", "#9C27B0", "#FF9800"]
fig = go.Figure()

for i, (name, series) in enumerate(chart_data.items()):
    color = colors[i % len(colors)]
    fig.add_trace(go.Scatter(
        x=series.index,
        y=series.values,
        mode="lines+markers",
        name=name[:40],  # Truncate long names
        line=dict(color=color, width=2),
        marker=dict(size=5),
    ))

fig.update_layout(
    title="Product Comparison",
    xaxis_title="Date",
    yaxis_title=y_title,
    hovermode="x unified",
    template="plotly_white",
    height=500,
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=-0.3,
        xanchor="center",
        x=0.5,
    ),
)

st.plotly_chart(fig, use_container_width=True)

# --- Comparison statistics table ---
if len(prices_dict) >= 2:
    st.subheader("Comparison Statistics")
    stats = calculate_comparison_stats(prices_dict)
    if stats:
        stats_df = pd.DataFrame(stats)
        # Format numbers
        stats_df["Current Price"] = stats_df["Current Price"].apply(lambda x: f"${x:,.2f}")
        stats_df["Start Price"] = stats_df["Start Price"].apply(lambda x: f"${x:,.2f}")
        stats_df["Total Return %"] = stats_df["Total Return %"].apply(lambda x: f"{x:+.1f}%")
        stats_df["Volatility %"] = stats_df["Volatility %"].apply(lambda x: f"{x:.1f}%")
        stats_df["Highest"] = stats_df["Highest"].apply(lambda x: f"${x:,.2f}")
        stats_df["Lowest"] = stats_df["Lowest"].apply(lambda x: f"${x:,.2f}")

        st.dataframe(stats_df, use_container_width=True, hide_index=True)
