"""
Graded Cards page.
Track PSA and TAG graded card prices over time with historical data
from PriceCharting.com. Supports watchlists, multi-card overlay,
and raw booster pack price comparison on a dual y-axis.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, date
from database.models import get_connection
from database import operations as db
from scrapers.pricecharting_client import PriceChartingClient
from scrapers.tcg_client import TCGCSVClient

GRADING_COMPANIES = ["PSA", "TAG"]

ALL_GRADES = [
    "10", "9.5", "9", "8.5", "8", "7.5", "7", "6.5", "6",
    "5.5", "5", "4.5", "4", "3.5", "3", "2.5", "2", "1.5", "1",
    "Ungraded",
]

CARD_COLORS = [
    "#FF6B35", "#2196F3", "#4CAF50", "#9C27B0", "#FF9800",
    "#E91E63", "#00BCD4", "#795548", "#607D8B", "#3F51B5",
]

PACK_COLOR = "rgba(150, 150, 150, 0.6)"


# ──────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────

def find_set_release_date(tcg_client: TCGCSVClient, set_name: str) -> str | None:
    """Try to find a set's release date from TCGCSV data."""
    if not set_name:
        return None
    try:
        all_sets = tcg_client.get_all_sets()
    except Exception:
        return None

    set_lower = set_name.lower().replace("pokemon ", "").strip()
    best_match = None
    best_score = 0

    for s in all_sets:
        s_name = s["name"].lower()
        # Simple substring match scoring
        if set_lower in s_name or s_name in set_lower:
            score = len(set_lower)
            if score > best_score:
                best_score = score
                best_match = s

    if best_match:
        pub = best_match.get("publishedOn", "")
        return pub[:10] if pub else None
    return None


def get_available_grades(conn, watchlist_ids: list[int],
                          grading_company: str) -> list[str]:
    """Get grades that have data for the selected cards and company."""
    if not watchlist_ids:
        return ALL_GRADES[:6]

    placeholders = ",".join("?" * len(watchlist_ids))
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT DISTINCT grade FROM graded_price_history "
        f"WHERE watchlist_id IN ({placeholders}) AND grading_company = ? "
        f"ORDER BY CAST(grade AS REAL) DESC",
        [*watchlist_ids, grading_company],
    )
    grades = [row["grade"] for row in cursor.fetchall()]
    return grades if grades else ALL_GRADES[:6]


def load_booster_pack_data(conn, watchlist: list[dict],
                            selected_ids: list[int],
                            tcg_client: TCGCSVClient) -> dict[str, pd.DataFrame]:
    """
    Load booster pack price data for the sets corresponding to selected cards.
    Returns {set_name: DataFrame with date + price}.
    """
    pack_data = {}
    seen_sets = set()

    for wid in selected_ids:
        item = next((w for w in watchlist if w["id"] == wid), None)
        if not item:
            continue
        set_name = item.get("set_name", "")
        if not set_name or set_name in seen_sets:
            continue
        seen_sets.add(set_name)

        # Search for booster packs in this set
        products = db.search_products(conn, set_name)
        pack_products = [
            p for p in products
            if "booster pack" in p["name"].lower()
            and p.get("set_name", "").lower() == set_name.lower()
        ]

        # If we don't have local data, try broader match
        if not pack_products:
            pack_products = [
                p for p in products
                if "booster pack" in p["name"].lower()
            ]

        for pp in pack_products[:1]:  # Use the first matching pack
            snapshots = db.get_daily_snapshots(conn, pp["id"])
            if snapshots:
                df = pd.DataFrame(snapshots)
                df["date"] = pd.to_datetime(df["date"])
                df["price"] = df["tcg_market_price"]
                df = df[df["price"].notna()].sort_values("date")
                if not df.empty:
                    pack_data[f"{set_name} Booster Pack"] = df

    return pack_data


def build_calendar_chart(card_data: dict, pack_data: dict,
                          company: str, grade: str) -> go.Figure:
    """Build the calendar date x-axis chart with dual y-axis for pack overlay."""
    has_packs = bool(pack_data)

    if has_packs:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
    else:
        fig = go.Figure()

    # Add graded card lines (left y-axis)
    for i, (label, df) in enumerate(card_data.items()):
        color = CARD_COLORS[i % len(CARD_COLORS)]
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["price"],
                mode="lines",
                name=label,
                line=dict(color=color, width=2),
                hovertemplate=f"<b>{label}</b><br>%{{x|%b %d, %Y}}: $%{{y:,.2f}}<extra></extra>",
            ),
            secondary_y=False if has_packs else None,
        )

    # Add booster pack lines (right y-axis)
    if has_packs:
        for pack_label, df in pack_data.items():
            fig.add_trace(
                go.Scatter(
                    x=df["date"],
                    y=df["price"],
                    mode="lines",
                    name=pack_label,
                    line=dict(color=PACK_COLOR, width=2, dash="dot"),
                    hovertemplate=f"<b>{pack_label}</b><br>%{{x|%b %d, %Y}}: $%{{y:,.2f}}<extra></extra>",
                ),
                secondary_y=True,
            )

    title = f"{company} Grade {grade} — Calendar Timeline"
    if has_packs:
        fig.update_yaxes(title_text="Graded Card Price (USD)", secondary_y=False)
        fig.update_yaxes(title_text="Booster Pack Price (USD)", secondary_y=True)
    else:
        fig.update_yaxes(title_text="Price (USD)")

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        hovermode="x unified",
        template="plotly_white",
        height=550,
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.25,
            xanchor="center", x=0.5,
        ),
    )

    return fig


def build_release_chart(card_data: dict, pack_data: dict,
                         release_dates: dict, company: str,
                         grade: str) -> go.Figure:
    """Build the days-since-release (T=0) chart with dual y-axis."""
    has_packs = bool(pack_data)

    if has_packs:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
    else:
        fig = go.Figure()

    for i, (label, df) in enumerate(card_data.items()):
        release = release_dates.get(label)
        if not release:
            # Try to find release date by partial label match
            for rl, rd in release_dates.items():
                if rl in label or label in rl:
                    release = rd
                    break
        if not release:
            continue

        df = df.copy()
        df["days"] = (df["date"] - pd.Timestamp(release)).dt.days
        color = CARD_COLORS[i % len(CARD_COLORS)]

        fig.add_trace(
            go.Scatter(
                x=df["days"],
                y=df["price"],
                mode="lines",
                name=label,
                line=dict(color=color, width=2),
                hovertemplate=f"<b>{label}</b><br>Day %{{x}}: $%{{y:,.2f}}<extra></extra>",
            ),
            secondary_y=False if has_packs else None,
        )

    # Pack overlay on days-since-release axis
    if has_packs:
        for pack_label, df in pack_data.items():
            # Find the matching release date for this pack's set
            pack_release = None
            for rl, rd in release_dates.items():
                if any(word in pack_label.lower() for word in rl.lower().split()[:2]):
                    pack_release = rd
                    break
            if not pack_release:
                # Use the first available release date
                pack_release = next(iter(release_dates.values()), None)
            if not pack_release:
                continue

            df = df.copy()
            df["days"] = (df["date"] - pd.Timestamp(pack_release)).dt.days

            fig.add_trace(
                go.Scatter(
                    x=df["days"],
                    y=df["price"],
                    mode="lines",
                    name=pack_label,
                    line=dict(color=PACK_COLOR, width=2, dash="dot"),
                    hovertemplate=f"<b>{pack_label}</b><br>Day %{{x}}: $%{{y:,.2f}}<extra></extra>",
                ),
                secondary_y=True,
            )

    # Add T=0 marker
    fig.add_vline(x=0, line_dash="dash", line_color="red",
                  annotation_text="Set Release")

    title = f"{company} Grade {grade} — Days Since Set Release"
    if has_packs:
        fig.update_yaxes(title_text="Graded Card Price (USD)", secondary_y=False)
        fig.update_yaxes(title_text="Booster Pack Price (USD)", secondary_y=True)
    else:
        fig.update_yaxes(title_text="Price (USD)")

    fig.update_layout(
        title=title,
        xaxis_title="Days Since Set Release",
        hovermode="x unified",
        template="plotly_white",
        height=550,
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.25,
            xanchor="center", x=0.5,
        ),
    )

    return fig


# ──────────────────────────────────────────────
# Main Page Flow
# ──────────────────────────────────────────────

st.title("Graded Card Tracker")
st.markdown(
    "Track PSA and TAG graded card prices over time. "
    "Add cards to your watchlist and compare prices against raw booster packs."
)

# Initialize clients
if "pc_client" not in st.session_state:
    st.session_state.pc_client = PriceChartingClient()
if "tcg_client" not in st.session_state:
    st.session_state.tcg_client = TCGCSVClient()

pc_client = st.session_state.pc_client
tcg_client = st.session_state.tcg_client


# ──────────────────────────────────────────────
# Section 1: Search & Add to Watchlist
# ──────────────────────────────────────────────

st.subheader("1. Search & Add Cards")

search_query = st.text_input(
    "Search for a Pokemon card on PriceCharting",
    placeholder="e.g., Charizard Base Set, Pikachu Illustrator",
)

if search_query:
    cache_key = f"pc_search_{search_query}"
    if cache_key not in st.session_state:
        with st.spinner("Searching PriceCharting..."):
            st.session_state[cache_key] = pc_client.search_cards(search_query)

    search_results = st.session_state[cache_key]

    if not search_results:
        st.warning("No results found. Try a different search term.")
    else:
        st.markdown(f"**{len(search_results)} results found:**")

        for i, card in enumerate(search_results[:15]):
            col1, col2 = st.columns([4, 1])
            with col1:
                price_str = (
                    f"${card['current_price']:,.2f}"
                    if card.get("current_price") else "N/A"
                )
                st.markdown(
                    f"**{card['name']}** — "
                    f"{card.get('set_name', 'Unknown Set')} — {price_str}"
                )
            with col2:
                if st.button("Add", key=f"add_{i}", help="Add to watchlist"):
                    with st.spinner("Fetching card details & price history..."):
                        details = pc_client.get_card_details(card["url"])

                    if details:
                        conn = get_connection()
                        set_release = find_set_release_date(
                            tcg_client, details.get("set_name", "")
                        )

                        watchlist_id = db.add_to_graded_watchlist(
                            conn,
                            card_name=details["name"] or card["name"],
                            set_name=details.get("set_name") or card.get("set_name"),
                            set_release_date=set_release,
                            pricecharting_id=card.get("pricecharting_id", ""),
                            pricecharting_url=card["url"],
                        )

                        # Store historical chart data
                        price_records = []
                        for grade_label, points in details.get("chart_data", {}).items():
                            for pt in points:
                                price_records.append({
                                    "grading_company": "PSA",
                                    "grade": grade_label,
                                    "date": pt["date"],
                                    "price": pt["price"],
                                    "source": "pricecharting",
                                })

                        if price_records:
                            db.insert_graded_prices(conn, watchlist_id, price_records)

                        conn.close()
                        st.success(
                            f"Added **{details['name']}** with "
                            f"{len(price_records)} historical price points!"
                        )
                        st.rerun()
                    else:
                        st.error("Could not fetch card details. Try again.")


# ──────────────────────────────────────────────
# Section 2: Watchlist Management
# ──────────────────────────────────────────────

st.markdown("---")
st.subheader("2. Your Watchlist")

conn = get_connection()
watchlist = db.get_graded_watchlist(conn)

if not watchlist:
    st.info("Your watchlist is empty. Search for cards above to add them.")
    conn.close()
    st.stop()

for item in watchlist:
    col1, col2, col3 = st.columns([3, 2, 1])
    with col1:
        st.markdown(f"**{item['card_name']}**")
    with col2:
        st.caption(item.get("set_name") or "Unknown Set")
    with col3:
        if st.button("Remove", key=f"rm_{item['id']}"):
            db.remove_from_graded_watchlist(conn, item["id"])
            st.rerun()


# ──────────────────────────────────────────────
# Section 3: Chart Configuration
# ──────────────────────────────────────────────

st.markdown("---")
st.subheader("3. Chart Settings")

card_options = {
    w["id"]: f"{w['card_name']} ({w.get('set_name', '')})"
    for w in watchlist
}
selected_card_ids = st.multiselect(
    "Select cards to chart",
    options=list(card_options.keys()),
    format_func=lambda x: card_options[x],
    default=list(card_options.keys())[:3],
)

if not selected_card_ids:
    st.info("Select at least one card from your watchlist.")
    conn.close()
    st.stop()

filter_col1, filter_col2 = st.columns(2)
with filter_col1:
    selected_company = st.selectbox("Grading Company", GRADING_COMPANIES)
with filter_col2:
    available = get_available_grades(conn, selected_card_ids, selected_company)
    selected_grade = st.selectbox("Grade", available)

show_pack_overlay = st.checkbox("Overlay raw booster pack prices", value=True)


# ──────────────────────────────────────────────
# Section 4: Load Data & Render Charts
# ──────────────────────────────────────────────

card_data = {}
release_dates = {}

for wid in selected_card_ids:
    item = next(w for w in watchlist if w["id"] == wid)
    label = item["card_name"]
    if len(selected_card_ids) > 1:
        label = label[:35]

    history = db.get_graded_price_history(
        conn, wid,
        grading_company=selected_company,
        grade=selected_grade,
    )

    if history:
        df = pd.DataFrame(history)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
        card_data[label] = df

    release_str = item.get("set_release_date")
    if release_str:
        try:
            release_dates[label] = datetime.strptime(release_str, "%Y-%m-%d").date()
        except ValueError:
            pass

pack_data = {}
if show_pack_overlay:
    pack_data = load_booster_pack_data(conn, watchlist, selected_card_ids, tcg_client)

conn.close()

if not card_data:
    st.warning(
        f"No price data found for {selected_company} Grade {selected_grade}. "
        f"Try a different grade — available data depends on what PriceCharting tracks."
    )
    st.stop()


# ── Chart 1: Calendar Timeline ──

st.markdown("---")
st.subheader("4. Price Charts")
st.markdown(f"### Calendar Timeline — {selected_company} Grade {selected_grade}")

fig1 = build_calendar_chart(card_data, pack_data, selected_company, selected_grade)
st.plotly_chart(fig1, use_container_width=True)


# ── Chart 2: Days Since Release ──

st.markdown(f"### Days Since Set Release — {selected_company} Grade {selected_grade}")

if release_dates:
    fig2 = build_release_chart(
        card_data, pack_data, release_dates,
        selected_company, selected_grade,
    )
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No set release dates available for the selected cards.")


# ── Stats Table ──

if card_data:
    st.markdown("### Price Statistics")
    stats_rows = []
    for label, df in card_data.items():
        prices = df["price"]
        first_p = prices.iloc[0]
        last_p = prices.iloc[-1]
        change = (
            f"{((last_p - first_p) / first_p * 100):+.1f}%"
            if first_p > 0 else "N/A"
        )
        stats_rows.append({
            "Card": label,
            "Earliest": df["date"].min().strftime("%Y-%m-%d"),
            "Latest": df["date"].max().strftime("%Y-%m-%d"),
            "Data Points": len(df),
            "Current": f"${last_p:,.2f}",
            "Low": f"${prices.min():,.2f}",
            "High": f"${prices.max():,.2f}",
            "Change": change,
        })
    st.dataframe(pd.DataFrame(stats_rows), use_container_width=True, hide_index=True)


# ── Disclaimer ──

st.markdown("---")
st.caption(
    "Data sourced from PriceCharting.com (historical) and eBay sold listings. "
    "Prices are based on completed eBay sales. "
    "TAG = Technical Grading and Authentication. "
    "This is not financial advice."
)
