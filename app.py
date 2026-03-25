"""
Pokemon Card Investment Tracker
Main Streamlit application entry point.

Run with:  streamlit run app.py
"""

import hmac

import streamlit as st
from database.models import initialize_database

# Initialize database on first run
initialize_database()

# --- Page configuration ---
st.set_page_config(
    page_title="Investment Tracker",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --- Authentication ---
def check_password():
    """Simple shared password gate using st.secrets."""
    if st.session_state.get("authenticated"):
        return True

    st.title("Welcome")
    st.markdown("Enter the password to access the Investment Tracker.")
    password = st.text_input("Password", type="password", key="login_password")
    if password:
        if hmac.compare_digest(password, st.secrets["app_password"]):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")
    return False


if not check_password():
    st.stop()


# --- Define pages ---
home_page = st.Page("pages/home.py", title="Home", icon="🏠", default=True)
search_page = st.Page("pages/search.py", title="Search Cards", icon="🔍")
chart_page = st.Page("pages/price_chart.py", title="Price Chart", icon="📈")
set_analysis_page = st.Page("pages/set_analysis.py", title="Set Release Analysis", icon="📅")
era_comparison_page = st.Page("pages/era_comparison.py", title="Era Comparison", icon="🔀")
trends_page = st.Page("pages/trends_dashboard.py", title="Trends & Signals", icon="📊")
compare_page = st.Page("pages/compare.py", title="Compare Products", icon="⚖️")
portfolio_page = st.Page("pages/portfolio.py", title="Portfolio", icon="💼")
graded_page = st.Page("pages/graded_cards.py", title="Graded Cards", icon="🏆")

# --- Navigation (grouped for multi-project framework) ---
nav = st.navigation({
    "Home": [home_page],
    "Pokemon Tracker": [
        search_page, chart_page, set_analysis_page,
        era_comparison_page, trends_page, compare_page, portfolio_page,
        graded_page,
    ],
})

# --- Sidebar ---
st.sidebar.title("Investment Tracker")
st.sidebar.markdown("---")
st.sidebar.caption("Data sources: TCGPlayer (via TCGCSV) | eBay Sold Listings | PriceCharting")
st.sidebar.caption("Tip: Use the app daily to build up price history over time.")

# --- Run selected page ---
nav.run()
