"""
Search page: Find Pokemon cards and sealed products.
Search TCGPlayer catalog or eBay sold listings.
"""

import streamlit as st
import pandas as pd
from database.models import get_connection
from database import operations as db
from scrapers.tcg_client import TCGCSVClient
from scrapers.ebay_scraper import EbaySoldScraper
from utils.cache import SimpleCache
from datetime import date

# --- Initialize session state ---
if "cache" not in st.session_state:
    st.session_state.cache = SimpleCache(ttl_minutes=30)

if "tcg_client" not in st.session_state:
    st.session_state.tcg_client = TCGCSVClient()

if "ebay_scraper" not in st.session_state:
    st.session_state.ebay_scraper = EbaySoldScraper()

# --- Page header ---
st.title("🔍 Search Pokemon Cards & Products")

# --- Search controls ---
col1, col2 = st.columns([3, 1])

with col1:
    query = st.text_input(
        "Search for a card, set, or sealed product",
        placeholder="e.g., Charizard, Prismatic Evolutions ETB, Pikachu VMAX...",
    )

with col2:
    source = st.radio(
        "Search source",
        ["TCGPlayer", "eBay Sold"],
        horizontal=True,
    )

search_clicked = st.button("Search", type="primary", use_container_width=True)


# --- Helper: search TCGPlayer ---
def search_tcgplayer(query: str) -> pd.DataFrame:
    """Search TCGCSV for products matching the query."""
    client = st.session_state.tcg_client

    # Check cache first
    cache_key = f"tcg_search_{query.lower()}"
    cached = st.session_state.cache.get(cache_key)
    if cached is not None:
        return cached

    # Search for matching sets first
    matching_sets = client.search_sets(query)

    results = []

    if matching_sets:
        # If query matches a set name, show all products in that set
        for s in matching_sets[:3]:
            try:
                products = client.get_products_with_prices(s["groupId"])
                for p in products:
                    results.append({
                        "Name": p["name"],
                        "Set": s["name"],
                        "Market Price": p.get("marketPrice"),
                        "Low": p.get("lowPrice"),
                        "High": p.get("highPrice"),
                        "Variant": p.get("subTypeName", "Normal"),
                        "productId": p["productId"],
                        "groupId": s["groupId"],
                        "imageUrl": p.get("imageUrl", ""),
                    })
            except Exception:
                continue
    else:
        # Search product names across recent sets
        products = client.search_products_across_sets(query, max_sets=8)
        for p in products:
            results.append({
                "Name": p["name"],
                "Set": p.get("set_name", ""),
                "Market Price": p.get("marketPrice"),
                "Low": p.get("lowPrice"),
                "High": p.get("highPrice"),
                "Variant": p.get("subTypeName", "Normal"),
                "productId": p["productId"],
                "groupId": p.get("groupId"),
                "imageUrl": p.get("imageUrl", ""),
            })

    df = pd.DataFrame(results) if results else pd.DataFrame()
    st.session_state.cache.set(cache_key, df)
    return df


# --- Helper: search eBay ---
def search_ebay(query: str) -> pd.DataFrame:
    """Search eBay sold listings."""
    scraper = st.session_state.ebay_scraper

    cache_key = f"ebay_search_{query.lower()}"
    cached = st.session_state.cache.get(cache_key)
    if cached is not None:
        return cached

    results = scraper.search_sold(query, max_pages=1)

    if results:
        df = pd.DataFrame(results)
        df.columns = ["Title", "Price", "Sold Date", "URL", "Condition"]
    else:
        df = pd.DataFrame()

    st.session_state.cache.set(cache_key, df)
    return df


# --- Helper: save TCGPlayer product to DB and store today's price ---
def save_product_and_price(row: dict) -> int:
    """Save a TCGPlayer product to the database and record today's price."""
    conn = get_connection()
    product_id = db.upsert_product(
        conn,
        name=row["Name"],
        set_name=row.get("Set", ""),
        product_type="card",
        tcg_product_id=row.get("productId"),
        tcg_group_id=row.get("groupId"),
        image_url=row.get("imageUrl", ""),
    )

    # Store today's price if we haven't already
    if row.get("Market Price") and not db.has_price_for_today(conn, product_id, "tcgplayer"):
        market = row["Market Price"]
        db.insert_price_point(conn, product_id, "tcgplayer", market, "market")
        if row.get("Low"):
            db.insert_price_point(conn, product_id, "tcgplayer", row["Low"], "low")
        if row.get("High"):
            db.insert_price_point(conn, product_id, "tcgplayer", row["High"], "high")

        # Also save a daily snapshot
        db.upsert_daily_snapshot(
            conn, product_id,
            tcg_market_price=market,
            tcg_low_price=row.get("Low"),
            tcg_mid_price=row.get("Market Price"),
        )

    conn.close()
    return product_id


# --- Display results ---
if search_clicked and query:
    if source == "TCGPlayer":
        with st.spinner("Searching TCGPlayer catalog..."):
            df = search_tcgplayer(query)

        if df.empty:
            st.warning("No results found. Try a different search term.")
        else:
            st.success(f"Found {len(df)} products")

            # Display results with action buttons
            for idx, row in df.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([4, 2, 1])

                    with c1:
                        st.markdown(f"**{row['Name']}**")
                        st.caption(f"Set: {row['Set']} • Variant: {row['Variant']}")

                    with c2:
                        price = row.get("Market Price")
                        if price:
                            st.metric("Market Price", f"${price:,.2f}")
                        else:
                            st.metric("Market Price", "N/A")

                    with c3:
                        if st.button("📈 Chart", key=f"chart_{idx}"):
                            product_id = save_product_and_price(row.to_dict())
                            st.session_state["selected_product_id"] = product_id
                            st.session_state["selected_product_name"] = row["Name"]
                            st.switch_page("pages/price_chart.py")

                        if st.button("💼 Add", key=f"add_{idx}"):
                            product_id = save_product_and_price(row.to_dict())
                            st.session_state["portfolio_add_product_id"] = product_id
                            st.session_state["portfolio_add_product_name"] = row["Name"]
                            st.switch_page("pages/portfolio.py")

    else:  # eBay
        with st.spinner("Searching eBay sold listings (this may take a moment)..."):
            df = search_ebay(query)

        if df.empty:
            st.warning(
                "No eBay results found. This can happen if eBay's bot detection "
                "is active. Try again in a few minutes, or use TCGPlayer search."
            )
        else:
            st.success(f"Found {len(df)} sold listings")

            # Format and display
            display_df = df.copy()
            if "Price" in display_df.columns:
                display_df["Price"] = display_df["Price"].apply(
                    lambda x: f"${x:,.2f}" if pd.notna(x) else "N/A"
                )

            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "URL": st.column_config.LinkColumn("Link", display_text="View"),
                },
            )

elif search_clicked and not query:
    st.warning("Please enter a search term.")


# --- Show recently tracked products ---
st.markdown("---")
st.subheader("Recently Tracked Products")

conn = get_connection()
tracked = db.get_all_tracked_products(conn)
conn.close()

if tracked:
    for product in tracked[:10]:
        col_a, col_b = st.columns([5, 1])
        with col_a:
            st.write(f"**{product['name']}** — {product.get('set_name', '')}")
        with col_b:
            if st.button("📈", key=f"tracked_{product['id']}"):
                st.session_state["selected_product_id"] = product["id"]
                st.session_state["selected_product_name"] = product["name"]
                st.switch_page("pages/price_chart.py")
else:
    st.info("No products tracked yet. Search for a product above and click '📈 Chart' to start tracking.")
