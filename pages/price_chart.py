"""
Price Chart page: Interactive price history visualization for a single product.
Shows TCGPlayer market price over time and eBay sold price scatter.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from database.models import get_connection
from database import operations as db

st.title("📈 Price Chart")

# --- Check if a product is selected ---
product_id = st.session_state.get("selected_product_id")
product_name = st.session_state.get("selected_product_name", "")

if not product_id:
    st.info("Select a product from the **Search** page to view its price chart.")
    st.stop()

# --- Load product info ---
conn = get_connection()
product = db.get_product_by_id(conn, product_id)

if not product:
    st.error("Product not found in database.")
    conn.close()
    st.stop()

st.subheader(product["name"])
if product.get("set_name"):
    st.caption(f"Set: {product['set_name']}")

# --- Date range filter ---
col1, col2 = st.columns(2)
with col1:
    days_back = st.selectbox(
        "Time range",
        [7, 30, 90, 180, 365, 0],
        format_func=lambda x: {
            7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days",
            180: "Last 6 months", 365: "Last year", 0: "All time",
        }[x],
        index=2,
    )

start_date = None
if days_back > 0:
    from datetime import date, timedelta
    start_date = (date.today() - timedelta(days=days_back)).isoformat()

# --- Load price data ---
price_history = db.get_price_history(conn, product_id, start_date=start_date)
daily_snapshots = db.get_daily_snapshots(conn, product_id, start_date=start_date)
ebay_listings = db.get_ebay_listings(conn, product_id)
conn.close()

# --- Build chart ---
fig = go.Figure()

# TCGPlayer daily snapshots (line chart)
if daily_snapshots:
    snap_df = pd.DataFrame(daily_snapshots)
    snap_df["date"] = pd.to_datetime(snap_df["date"])

    if snap_df["tcg_market_price"].notna().any():
        fig.add_trace(go.Scatter(
            x=snap_df["date"],
            y=snap_df["tcg_market_price"],
            mode="lines+markers",
            name="TCGPlayer Market",
            line=dict(color="#FF6B35", width=2),
            marker=dict(size=6),
        ))

    if snap_df["tcg_low_price"].notna().any():
        fig.add_trace(go.Scatter(
            x=snap_df["date"],
            y=snap_df["tcg_low_price"],
            mode="lines",
            name="TCGPlayer Low",
            line=dict(color="#FFA07A", width=1, dash="dot"),
        ))

# TCGPlayer individual price points (if no daily snapshots yet)
if not daily_snapshots and price_history:
    pp_df = pd.DataFrame(price_history)
    pp_df["observed_date"] = pd.to_datetime(pp_df["observed_date"])

    tcg_data = pp_df[pp_df["source"] == "tcgplayer"]
    if not tcg_data.empty:
        market_data = tcg_data[tcg_data["price_type"] == "market"]
        if not market_data.empty:
            fig.add_trace(go.Scatter(
                x=market_data["observed_date"],
                y=market_data["price"],
                mode="lines+markers",
                name="TCGPlayer Market",
                line=dict(color="#FF6B35", width=2),
                marker=dict(size=6),
            ))

# eBay sold listings (scatter)
if ebay_listings:
    ebay_df = pd.DataFrame(ebay_listings)
    ebay_df = ebay_df[ebay_df["sold_date"].notna()]
    if not ebay_df.empty:
        ebay_df["sold_date"] = pd.to_datetime(ebay_df["sold_date"])

        fig.add_trace(go.Scatter(
            x=ebay_df["sold_date"],
            y=ebay_df["sold_price"],
            mode="markers",
            name="eBay Sold",
            marker=dict(color="#2196F3", size=7, opacity=0.6),
            text=ebay_df["title"],
            hovertemplate="<b>%{text}</b><br>Price: $%{y:.2f}<br>Date: %{x}<extra></extra>",
        ))

# Layout
fig.update_layout(
    title=f"Price History: {product['name']}",
    xaxis_title="Date",
    yaxis_title="Price (USD)",
    hovermode="x unified",
    template="plotly_white",
    height=500,
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
)

if fig.data:
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info(
        "No price data yet for this product. "
        "Price data is recorded each time you search for it. "
        "Come back tomorrow to see the chart start building!"
    )

# --- Price statistics ---
if price_history:
    st.markdown("### Price Statistics")
    pp_df = pd.DataFrame(price_history)
    market_prices = pp_df[
        (pp_df["source"] == "tcgplayer") & (pp_df["price_type"] == "market")
    ]["price"]

    if not market_prices.empty:
        col_a, col_b, col_c, col_d = st.columns(4)
        with col_a:
            st.metric("Current", f"${market_prices.iloc[-1]:,.2f}")
        with col_b:
            st.metric("Lowest", f"${market_prices.min():,.2f}")
        with col_c:
            st.metric("Highest", f"${market_prices.max():,.2f}")
        with col_d:
            avg = market_prices.mean()
            st.metric("Average", f"${avg:,.2f}")

        if len(market_prices) >= 2:
            change = market_prices.iloc[-1] - market_prices.iloc[0]
            pct = (change / market_prices.iloc[0]) * 100
            st.metric(
                "Change (period)",
                f"${change:+,.2f}",
                delta=f"{pct:+.1f}%",
            )

# --- Raw data table ---
if price_history:
    with st.expander("View raw price data"):
        raw_df = pd.DataFrame(price_history)
        raw_df = raw_df[["observed_date", "source", "price_type", "price", "variant"]]
        raw_df.columns = ["Date", "Source", "Type", "Price", "Variant"]
        raw_df["Price"] = raw_df["Price"].apply(lambda x: f"${x:,.2f}")
        st.dataframe(raw_df, use_container_width=True, hide_index=True)
