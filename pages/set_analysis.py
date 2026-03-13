"""
Set Release Analysis page.
Analyze how product prices move relative to a set's public release date.
Key question: How long after release do prices decline before recovering?
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, timedelta, datetime
from database.models import get_connection
from database import operations as db
from scrapers.tcg_client import TCGCSVClient
from scrapers.history_loader import load_history_for_set, get_available_date_range
from analysis.trends import (
    calculate_moving_average,
    calculate_trend_direction,
    detect_trend_reversal,
)

st.title("📅 Set Release Analysis")
st.markdown(
    "Analyze how prices move after a set's release date. "
    "Identify when products stop declining and start gaining value."
)

# --- Initialize ---
if "tcg_client" not in st.session_state:
    st.session_state.tcg_client = TCGCSVClient()

client = st.session_state.tcg_client

# --- Step 1: Select a set ---
st.subheader("1. Select a Pokemon Set")

with st.spinner("Loading set catalog..."):
    all_sets = client.get_all_sets()

# Sort by release date (newest first) and build selection options
sorted_sets = sorted(
    all_sets,
    key=lambda s: s.get("publishedOn", ""),
    reverse=True,
)

set_options = {}
for s in sorted_sets:
    pub = s.get("publishedOn", "")
    release_str = pub[:10] if pub else "Unknown"
    label = f"{s['name']} (Released: {release_str})"
    set_options[s["groupId"]] = {
        "label": label,
        "name": s["name"],
        "release_date": release_str,
        "groupId": s["groupId"],
    }

selected_group_id = st.selectbox(
    "Choose a set",
    options=list(set_options.keys()),
    format_func=lambda x: set_options[x]["label"],
)

selected_set = set_options[selected_group_id]
release_date_str = selected_set["release_date"]

# Parse release date
try:
    release_date = datetime.strptime(release_date_str, "%Y-%m-%d").date()
except ValueError:
    release_date = None

if release_date:
    days_since_release = (date.today() - release_date).days
    st.info(f"**{selected_set['name']}** — Released {release_date_str} ({days_since_release} days ago)")
else:
    st.warning("Release date unavailable for this set.")

# --- Step 2: Load historical data ---
st.subheader("2. Load Historical Price Data")

earliest_available, latest_available = get_available_date_range()

st.caption(
    f"Historical data available from {earliest_available} to {latest_available}. "
    f"Each day's archive is ~3MB. Loading a full year of data downloads ~365 files."
)

col_a, col_b = st.columns(2)
with col_a:
    # Default start: set release date or earliest available
    default_start = release_date if release_date and release_date >= earliest_available else earliest_available
    load_start = st.date_input("From date", value=default_start, min_value=earliest_available, max_value=latest_available)
with col_b:
    load_end = st.date_input("To date", value=latest_available, min_value=earliest_available, max_value=latest_available)

num_days = (load_end - load_start).days + 1

if st.button(f"Load {num_days} days of historical data", type="primary"):
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(current, total, date_str):
        progress_bar.progress(current / total)
        status_text.text(f"Downloading archive {current}/{total}: {date_str}")

    with st.spinner("Loading historical data from TCGCSV archives..."):
        stats = load_history_for_set(
            group_id=selected_group_id,
            set_name=selected_set["name"],
            start_date=load_start,
            end_date=load_end,
            progress_callback=update_progress,
        )

    progress_bar.empty()
    status_text.empty()

    st.success(
        f"Loaded {stats['dates_loaded']} days of data for "
        f"{stats['products_found']} products ({stats['prices_stored']} price points)"
    )
    if stats["errors"]:
        for err in stats["errors"]:
            st.error(err)


# --- Step 3: Analyze price movements since release ---
st.subheader("3. Price Movement Since Release")

conn = get_connection()

# Find all products in this set
products = db.search_products(conn, selected_set["name"])
# Filter to products that belong to this set
set_products = [p for p in products if p.get("tcg_group_id") == selected_group_id]

if not set_products:
    st.info("No data loaded yet for this set. Click 'Load historical data' above.")
    conn.close()
    st.stop()

# --- Product type filter ---
st.markdown("**Filter products:**")
filter_col1, filter_col2 = st.columns(2)
with filter_col1:
    # Detect product types from names
    product_types = []
    for p in set_products:
        name_lower = p["name"].lower()
        if any(kw in name_lower for kw in ["booster box", "booster bundle"]):
            product_types.append("Booster Box/Bundle")
        elif any(kw in name_lower for kw in ["elite trainer", "etb"]):
            product_types.append("Elite Trainer Box")
        elif any(kw in name_lower for kw in ["booster pack"]):
            product_types.append("Booster Pack")
        elif any(kw in name_lower for kw in ["collection", "box", "tin", "binder"]):
            product_types.append("Sealed Product")
        else:
            product_types.append("Single Card")

    available_types = sorted(set(product_types))
    selected_types = st.multiselect(
        "Product types to include",
        available_types,
        default=available_types,
    )

with filter_col2:
    min_price = st.number_input("Minimum market price ($)", value=1.0, min_value=0.0, step=1.0)

# Filter products
filtered_products = []
for p, ptype in zip(set_products, product_types):
    if ptype in selected_types:
        filtered_products.append(p)

if not filtered_products:
    st.warning("No products match the current filters.")
    conn.close()
    st.stop()

# --- Build the "days since release" chart ---
# For each product, get its price history and align it to "days since release"
all_series = {}  # product_name -> {day_number: market_price}
summary_data = []

for product in filtered_products:
    snapshots = db.get_daily_snapshots(conn, product["id"])
    if not snapshots:
        continue

    df = pd.DataFrame(snapshots)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["tcg_market_price"].notna()].sort_values("date")

    if df.empty:
        continue

    # Check minimum price filter
    latest_price = df["tcg_market_price"].iloc[-1]
    if latest_price < min_price:
        continue

    if release_date:
        df["days_since_release"] = (df["date"] - pd.Timestamp(release_date)).dt.days
    else:
        df["days_since_release"] = range(len(df))

    prices = df.set_index("days_since_release")["tcg_market_price"]
    all_series[product["name"]] = prices

    # Calculate summary stats for this product
    first_price = prices.iloc[0]
    current_price = prices.iloc[-1]
    min_price_val = prices.min()
    min_day = prices.idxmin()

    change_from_first = ((current_price - first_price) / first_price * 100) if first_price > 0 else 0
    drop_from_first = ((min_price_val - first_price) / first_price * 100) if first_price > 0 else 0
    recovery_from_min = ((current_price - min_price_val) / min_price_val * 100) if min_price_val > 0 else 0

    summary_data.append({
        "Product": product["name"][:50],
        "First Price": first_price,
        "Lowest Price": min_price_val,
        "Day of Low": int(min_day),
        "Current Price": current_price,
        "Drop from Start %": round(drop_from_first, 1),
        "Recovery from Low %": round(recovery_from_min, 1),
        "Overall Change %": round(change_from_first, 1),
        "product_id": product["id"],
    })

conn.close()

if not all_series:
    st.warning("No price data available for the filtered products.")
    st.stop()

# --- Chart 1: Individual product prices over days since release ---
st.markdown("### Price Trajectories Since Release")

# Let user pick specific products or show aggregate
view_option = st.radio(
    "View",
    ["Top sealed products", "All products (aggregate)", "Select specific products"],
    horizontal=True,
)

fig = go.Figure()

if view_option == "Select specific products":
    product_choices = st.multiselect(
        "Select products to chart",
        options=list(all_series.keys()),
        default=list(all_series.keys())[:5],
        max_selections=10,
    )
    chart_series = {k: v for k, v in all_series.items() if k in product_choices}
elif view_option == "Top sealed products":
    # Filter to sealed products (boxes, etbs, packs)
    sealed_keywords = ["booster", "elite", "etb", "box", "bundle", "collection", "tin", "pack"]
    chart_series = {
        k: v for k, v in all_series.items()
        if any(kw in k.lower() for kw in sealed_keywords)
    }
    if not chart_series:
        chart_series = dict(list(all_series.items())[:10])
else:
    chart_series = all_series

colors = [
    "#FF6B35", "#2196F3", "#4CAF50", "#9C27B0", "#FF9800",
    "#E91E63", "#00BCD4", "#795548", "#607D8B", "#3F51B5",
]

for i, (name, series) in enumerate(chart_series.items()):
    color = colors[i % len(colors)]
    fig.add_trace(go.Scatter(
        x=series.index,
        y=series.values,
        mode="lines",
        name=name[:40],
        line=dict(color=color, width=2),
        hovertemplate=f"<b>{name[:30]}</b><br>Day %{{x}}: $%{{y:.2f}}<extra></extra>",
    ))

# Add vertical line at release date (day 0)
fig.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="Release Day")

fig.update_layout(
    title=f"Price vs Days Since Release — {selected_set['name']}",
    xaxis_title="Days Since Release",
    yaxis_title="Price (USD)",
    hovermode="x unified",
    template="plotly_white",
    height=550,
    legend=dict(orientation="h", yanchor="bottom", y=-0.4, xanchor="center", x=0.5),
)

st.plotly_chart(fig, use_container_width=True)


# --- Chart 2: Normalized view (all products indexed to 100) ---
st.markdown("### Normalized Price Movement (Index 100 = First Tracked Price)")

fig2 = go.Figure()

for i, (name, series) in enumerate(chart_series.items()):
    if len(series) < 2:
        continue
    base = series.iloc[0]
    if base > 0:
        normalized = (series / base) * 100
        color = colors[i % len(colors)]
        fig2.add_trace(go.Scatter(
            x=normalized.index,
            y=normalized.values,
            mode="lines",
            name=name[:40],
            line=dict(color=color, width=2),
        ))

fig2.add_hline(y=100, line_dash="dot", line_color="gray", annotation_text="Starting Price")
if release_date:
    fig2.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="Release Day")

fig2.update_layout(
    title="Normalized Price Index (100 = Starting Price)",
    xaxis_title="Days Since Release",
    yaxis_title="Price Index (100 = Start)",
    hovermode="x unified",
    template="plotly_white",
    height=500,
    legend=dict(orientation="h", yanchor="bottom", y=-0.4, xanchor="center", x=0.5),
)

st.plotly_chart(fig2, use_container_width=True)


# --- Chart 3: Average set behavior ---
if len(all_series) >= 3:
    st.markdown("### Average Set Behavior")
    st.caption("Average normalized price across all products in the set — shows the typical decline and recovery pattern.")

    # Normalize all series and compute average
    all_normalized = {}
    for name, series in all_series.items():
        if len(series) >= 2:
            base = series.iloc[0]
            if base > 0:
                all_normalized[name] = (series / base) * 100

    if all_normalized:
        # Combine into a single DataFrame, forward-fill, and average
        combined = pd.DataFrame(all_normalized)
        avg_series = combined.mean(axis=1).dropna()
        median_series = combined.median(axis=1).dropna()
        q25 = combined.quantile(0.25, axis=1).dropna()
        q75 = combined.quantile(0.75, axis=1).dropna()

        fig3 = go.Figure()

        # Confidence band (25th-75th percentile)
        fig3.add_trace(go.Scatter(
            x=list(q75.index) + list(q25.index[::-1]),
            y=list(q75.values) + list(q25.values[::-1]),
            fill="toself",
            fillcolor="rgba(33, 150, 243, 0.15)",
            line=dict(width=0),
            name="25th-75th Percentile",
            showlegend=True,
        ))

        fig3.add_trace(go.Scatter(
            x=avg_series.index,
            y=avg_series.values,
            mode="lines",
            name="Average",
            line=dict(color="#FF6B35", width=3),
        ))

        fig3.add_trace(go.Scatter(
            x=median_series.index,
            y=median_series.values,
            mode="lines",
            name="Median",
            line=dict(color="#2196F3", width=2, dash="dash"),
        ))

        fig3.add_hline(y=100, line_dash="dot", line_color="gray")
        if release_date:
            fig3.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="Release Day")

        # Find the average bottom
        if len(avg_series) > 5:
            min_idx = avg_series.idxmin()
            min_val = avg_series.min()
            fig3.add_annotation(
                x=min_idx, y=min_val,
                text=f"Average Low: Day {int(min_idx)}<br>Index: {min_val:.1f}",
                showarrow=True, arrowhead=2,
                bgcolor="white", bordercolor="red",
            )

        fig3.update_layout(
            title=f"Average Price Pattern — {selected_set['name']}",
            xaxis_title="Days Since Release",
            yaxis_title="Price Index (100 = Start)",
            hovermode="x unified",
            template="plotly_white",
            height=500,
        )

        st.plotly_chart(fig3, use_container_width=True)

        # Key insight
        if len(avg_series) > 5:
            min_day = int(avg_series.idxmin())
            min_val = avg_series.min()
            current_avg = avg_series.iloc[-1]

            st.markdown("### Key Findings")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Average Bottom", f"Day {min_day}", delta=f"({min_val:.0f} index)")
            with col2:
                drop = min_val - 100
                st.metric("Max Avg Drop", f"{drop:.1f}%")
            with col3:
                recovery = current_avg - min_val
                st.metric("Recovery So Far", f"+{recovery:.1f} pts" if recovery > 0 else f"{recovery:.1f} pts")

            if min_val < 95:
                st.markdown(
                    f"**Insight:** On average, products in **{selected_set['name']}** "
                    f"hit their lowest point around **day {min_day}** after release, "
                    f"dropping to about **{min_val:.0f}%** of their initial price. "
                    + (f"Since then, prices have recovered by **{recovery:.0f} index points**."
                       if recovery > 0 else "Prices are still near or below their low point.")
                )
            else:
                st.markdown(
                    f"**Insight:** Products in **{selected_set['name']}** have generally "
                    f"maintained or increased their value since release."
                )


# --- Summary table ---
st.markdown("### Product Summary Table")

if summary_data:
    summary_df = pd.DataFrame(summary_data)
    summary_df = summary_df.sort_values("Overall Change %", ascending=False)

    display_df = summary_df[[
        "Product", "First Price", "Lowest Price", "Day of Low",
        "Current Price", "Drop from Start %", "Recovery from Low %", "Overall Change %"
    ]].copy()

    display_df["First Price"] = display_df["First Price"].apply(lambda x: f"${x:,.2f}")
    display_df["Lowest Price"] = display_df["Lowest Price"].apply(lambda x: f"${x:,.2f}")
    display_df["Current Price"] = display_df["Current Price"].apply(lambda x: f"${x:,.2f}")
    display_df["Drop from Start %"] = display_df["Drop from Start %"].apply(lambda x: f"{x:+.1f}%")
    display_df["Recovery from Low %"] = display_df["Recovery from Low %"].apply(lambda x: f"{x:+.1f}%")
    display_df["Overall Change %"] = display_df["Overall Change %"].apply(lambda x: f"{x:+.1f}%")

    st.dataframe(display_df, use_container_width=True, hide_index=True)


# --- Disclaimer ---
st.markdown("---")
st.caption(
    "⚠️ Historical data from TCGCSV goes back to February 2024. "
    "Sets released before this date will have incomplete history. "
    "Price patterns vary by set and market conditions. Past performance "
    "does not predict future results. This is not financial advice."
)
