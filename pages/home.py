"""
Home page — landing page for the Investment Tracker.
Lists available projects and their tools.
"""

import streamlit as st

st.title("Investment Tracker")
st.markdown("Welcome! Choose a project from the sidebar to get started.")

st.markdown("---")

# --- Pokemon Tracker ---
st.subheader("Pokemon Tracker")
st.markdown(
    "Analyze Pokemon card and sealed product prices for investment decisions. "
    "Track historical prices, compare eras, and identify buy signals."
)

cols = st.columns(3)

with cols[0]:
    st.markdown("**Search Cards**")
    st.caption("Search the TCGPlayer catalog or eBay sold listings for any Pokemon product.")

    st.markdown("**Price Chart**")
    st.caption("View detailed price history charts for individual products.")

with cols[1]:
    st.markdown("**Set Release Analysis**")
    st.caption("Analyze how prices move after a set's release date — find the bottom.")

    st.markdown("**Era Comparison**")
    st.caption("Compare booster pack and box prices across SV, SWSH, SM, XY, and ME eras.")

with cols[2]:
    st.markdown("**Trends & Signals**")
    st.caption("Get BUY/WATCH/HOLD/SELL signals based on price trend analysis.")

    st.markdown("**Compare Products**")
    st.caption("Side-by-side comparison of multiple products on a single chart.")

st.markdown("---")
st.info(
    "This app runs on Streamlit Community Cloud. Historical data is pre-loaded, "
    "but new price fetches during a session may not persist after the app sleeps. "
    "The pre-loaded dataset covers Feb 2024 onward.",
    icon="ℹ️",
)
