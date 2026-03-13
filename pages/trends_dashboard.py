"""
Trends & Signals dashboard.
Shows investment signals for all tracked products.
"""

import streamlit as st
import pandas as pd
from database.models import get_connection
from database import operations as db
from analysis.signals import generate_signal, SignalType

st.title("📊 Trends & Investment Signals")

# --- Load all tracked products ---
conn = get_connection()
products = db.get_all_tracked_products(conn)

if not products:
    st.info(
        "No products being tracked yet. Go to **Search** and click "
        "'📈 Chart' on a product to start tracking it."
    )
    conn.close()
    st.stop()

st.write(f"Analyzing {len(products)} tracked products...")

# --- Generate signals for each product ---
signals_data = []

for product in products:
    price_history = db.get_price_history(conn, product["id"], source="tcgplayer")

    if price_history:
        prices = pd.Series(
            [p["price"] for p in price_history if p["price_type"] == "market"],
        )
    else:
        prices = pd.Series(dtype=float)

    signal = generate_signal(product["id"], product["name"], prices)

    signals_data.append({
        "Product": signal.product_name,
        "Signal": signal.signal_type.value,
        "Price": f"${signal.current_price:,.2f}" if signal.current_price else "N/A",
        "Trend": signal.trend_direction,
        "Volatility": f"{signal.volatility:.1f}%",
        "Confidence": f"{signal.confidence:.0%}",
        "Reason": signal.reason,
        "product_id": signal.product_id,
        "_signal_order": list(SignalType).index(signal.signal_type),
    })

conn.close()

# --- Sort by signal importance (BUY first, then WATCH, etc.) ---
signals_data.sort(key=lambda x: x["_signal_order"])

# --- Summary metrics ---
signal_counts = {}
for s in signals_data:
    sig = s["Signal"]
    signal_counts[sig] = signal_counts.get(sig, 0) + 1

cols = st.columns(len(signal_counts))
for i, (signal, count) in enumerate(signal_counts.items()):
    with cols[i]:
        st.metric(signal, count)

st.markdown("---")

# --- Signal cards ---
for s in signals_data:
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([3, 1, 1, 1])

        with c1:
            st.markdown(f"**{s['Product']}**")
            st.caption(s["Reason"])

        with c2:
            st.markdown(f"**{s['Signal']}**")

        with c3:
            st.markdown(f"**{s['Price']}**")
            st.caption(f"Vol: {s['Volatility']}")

        with c4:
            if st.button("📈 Chart", key=f"trend_chart_{s['product_id']}"):
                st.session_state["selected_product_id"] = s["product_id"]
                st.session_state["selected_product_name"] = s["Product"]
                st.switch_page("pages/price_chart.py")

# --- Disclaimer ---
st.markdown("---")
st.caption(
    "⚠️ These signals are for informational purposes only and are not financial advice. "
    "Always do your own research before making investment decisions. "
    "Signal accuracy improves with more historical data."
)
