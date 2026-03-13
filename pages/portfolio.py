"""
Portfolio tracker page.
Track your Pokemon card/product investments and see gains/losses.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date
from database.models import get_connection
from database import operations as db

st.title("💼 Portfolio Tracker")

conn = get_connection()

# --- Check if we're adding a product from search ---
if "portfolio_add_product_id" in st.session_state:
    st.info(f"Adding **{st.session_state.get('portfolio_add_product_name', '')}** to portfolio")

# --- Add item form ---
with st.expander("Add Investment", expanded=bool(st.session_state.get("portfolio_add_product_id"))):
    products = db.get_all_tracked_products(conn)

    if not products:
        st.warning("No tracked products yet. Search and view a product's chart first to track it.")
    else:
        product_options = {p["id"]: f"{p['name']} ({p.get('set_name', '')})" for p in products}

        # Pre-select product if coming from search page
        default_id = st.session_state.pop("portfolio_add_product_id", None)
        st.session_state.pop("portfolio_add_product_name", None)

        default_idx = 0
        if default_id and default_id in product_options:
            default_idx = list(product_options.keys()).index(default_id)

        with st.form("add_portfolio_item"):
            selected_product = st.selectbox(
                "Product",
                options=list(product_options.keys()),
                format_func=lambda x: product_options[x],
                index=default_idx,
            )

            col1, col2, col3 = st.columns(3)
            with col1:
                quantity = st.number_input("Quantity", min_value=1, value=1)
            with col2:
                purchase_price = st.number_input("Purchase Price ($)", min_value=0.01, value=10.00, step=0.50)
            with col3:
                purchase_date = st.date_input("Purchase Date", value=date.today())

            notes = st.text_input("Notes (optional)", placeholder="e.g., PSA 10, sealed")

            if st.form_submit_button("Add to Portfolio", type="primary"):
                db.add_portfolio_item(
                    conn,
                    product_id=selected_product,
                    quantity=quantity,
                    purchase_price=purchase_price,
                    purchase_date=purchase_date.isoformat(),
                    notes=notes,
                )
                st.success("Added to portfolio!")
                st.rerun()

# --- Load portfolio ---
portfolio = db.get_portfolio(conn)

if not portfolio:
    st.info("Your portfolio is empty. Add investments above to start tracking.")
    conn.close()
    st.stop()

# --- Get current prices for portfolio items ---
portfolio_data = []
total_invested = 0
total_current = 0

for item in portfolio:
    # Get most recent price
    price_history = db.get_price_history(conn, item["product_id"], source="tcgplayer")
    market_prices = [p["price"] for p in price_history if p["price_type"] == "market"]
    current_price = market_prices[-1] if market_prices else None

    invested = item["quantity"] * item["purchase_price"]
    total_invested += invested

    current_value = (item["quantity"] * current_price) if current_price else None
    if current_value:
        total_current += current_value

    gain_loss = (current_value - invested) if current_value else None
    gain_loss_pct = ((gain_loss / invested) * 100) if gain_loss is not None and invested > 0 else None

    portfolio_data.append({
        "Product": item["name"],
        "Set": item.get("set_name", ""),
        "Qty": item["quantity"],
        "Buy Price": item["purchase_price"],
        "Current Price": current_price,
        "Invested": invested,
        "Current Value": current_value,
        "Gain/Loss $": gain_loss,
        "Gain/Loss %": gain_loss_pct,
        "Date": item["purchase_date"],
        "Notes": item.get("notes", ""),
        "portfolio_id": item["id"],
        "product_id": item["product_id"],
    })

conn.close()

# --- Summary metrics ---
st.subheader("Portfolio Summary")
col_a, col_b, col_c, col_d = st.columns(4)

with col_a:
    st.metric("Total Invested", f"${total_invested:,.2f}")
with col_b:
    st.metric("Current Value", f"${total_current:,.2f}" if total_current else "N/A")
with col_c:
    if total_current and total_invested:
        total_gl = total_current - total_invested
        st.metric("Total Gain/Loss", f"${total_gl:+,.2f}",
                  delta=f"{(total_gl / total_invested * 100):+.1f}%")
    else:
        st.metric("Total Gain/Loss", "N/A")
with col_d:
    st.metric("Holdings", str(len(portfolio_data)))

st.markdown("---")

# --- Portfolio allocation pie chart ---
if portfolio_data and any(d["Current Value"] for d in portfolio_data):
    st.subheader("Portfolio Allocation")

    alloc_data = [
        {"Product": d["Product"], "Value": d["Current Value"]}
        for d in portfolio_data
        if d["Current Value"]
    ]

    if alloc_data:
        alloc_df = pd.DataFrame(alloc_data)
        fig = px.pie(
            alloc_df,
            values="Value",
            names="Product",
            hole=0.3,
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)

# --- Holdings table ---
st.subheader("Holdings")

for item in portfolio_data:
    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 1, 1])

        with c1:
            st.markdown(f"**{item['Product']}**")
            st.caption(f"Set: {item['Set']} • Qty: {item['Qty']} • Bought: {item['Date']}")
            if item["Notes"]:
                st.caption(f"Notes: {item['Notes']}")

        with c2:
            st.metric("Buy Price", f"${item['Buy Price']:,.2f}")

        with c3:
            current = item["Current Price"]
            st.metric("Current", f"${current:,.2f}" if current else "N/A")

        with c4:
            gl = item["Gain/Loss $"]
            gl_pct = item["Gain/Loss %"]
            if gl is not None:
                st.metric(
                    "Gain/Loss",
                    f"${gl:+,.2f}",
                    delta=f"{gl_pct:+.1f}%" if gl_pct else None,
                )
            else:
                st.metric("Gain/Loss", "N/A")

        with c5:
            if st.button("📈", key=f"port_chart_{item['portfolio_id']}"):
                st.session_state["selected_product_id"] = item["product_id"]
                st.session_state["selected_product_name"] = item["Product"]
                st.switch_page("pages/price_chart.py")

# --- Disclaimer ---
st.markdown("---")
st.caption(
    "⚠️ Portfolio values are based on TCGPlayer market prices and may not reflect "
    "actual sale prices. This tool is for tracking purposes only, not financial advice."
)
