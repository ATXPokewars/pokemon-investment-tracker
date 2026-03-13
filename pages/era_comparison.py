"""
Era Comparison page.
Compare booster pack and booster box prices across different Pokemon TCG eras,
aligned to each set's release date. Charts start 30 days before release.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import time
from datetime import date, timedelta, datetime
from database.models import get_connection
from database import operations as db
from scrapers.tcg_client import TCGCSVClient
from scrapers.history_loader import load_history_for_set, get_available_date_range

st.title("🔀 Era Comparison: Booster Packs & Boxes")
st.markdown(
    "Compare how booster pack and booster box prices move across eras. "
    "All charts are aligned to release day (Day 0) and start 30 days before release."
)

# ========================
# ERA DEFINITIONS
# ========================
# Each era maps to a list of (groupId, set_name, release_date) for main expansion sets.
# We exclude promos, trainer kits, McDonald's sets, etc. — only full expansion sets.

ERAS = {
    "Scarlet & Violet (2023-2025)": {
        "color_palette": ["#FF6B35", "#FF8A5C", "#FFA87E", "#FFC6A0", "#FFE4C2",
                          "#E85D26", "#D14F18", "#BA410A", "#A33300", "#8C2500"],
        "sets": [
            (22873, "SV01: Scarlet & Violet", "2023-03-31"),
            (23120, "SV02: Paldea Evolved", "2023-06-09"),
            (23228, "SV03: Obsidian Flames", "2023-08-11"),
            (23286, "SV04: Paradox Rift", "2023-11-03"),
            (23353, "SV: Paldean Fates", "2024-01-26"),
            (23381, "SV05: Temporal Forces", "2024-03-22"),
            (23473, "SV06: Twilight Masquerade", "2024-05-24"),
            (23537, "SV07: Stellar Crown", "2024-09-13"),
            (23651, "SV08: Surging Sparks", "2024-11-08"),
            (23821, "SV: Prismatic Evolutions", "2025-01-17"),
        ],
    },
    "Sword & Shield (2020-2023)": {
        "color_palette": ["#2196F3", "#42A5F5", "#64B5F6", "#90CAF9", "#BBDEFB",
                          "#1976D2", "#1565C0", "#0D47A1", "#0B3D91", "#093380"],
        "sets": [
            (2585, "SWSH01: Sword & Shield", "2020-02-07"),
            (2626, "SWSH02: Rebel Clash", "2020-05-01"),
            (2675, "SWSH03: Darkness Ablaze", "2020-08-14"),
            (2701, "SWSH04: Vivid Voltage", "2020-11-13"),
            (2765, "SWSH05: Battle Styles", "2021-03-19"),
            (2807, "SWSH06: Chilling Reign", "2021-06-18"),
            (2848, "SWSH07: Evolving Skies", "2021-08-27"),
            (2906, "SWSH08: Fusion Strike", "2021-11-12"),
            (2948, "SWSH09: Brilliant Stars", "2022-02-25"),
            (3040, "SWSH10: Astral Radiance", "2022-05-27"),
            (3118, "SWSH11: Lost Origin", "2022-09-09"),
            (3170, "SWSH12: Silver Tempest", "2022-11-11"),
            (17688, "Crown Zenith", "2023-01-20"),
        ],
    },
    "Sun & Moon (2017-2019)": {
        "color_palette": ["#FFC107", "#FFCA28", "#FFD54F", "#FFE082", "#FFECB3",
                          "#FFB300", "#FFA000", "#FF8F00", "#FF6F00", "#E65100"],
        "sets": [
            (1863, "SM: Base Set", "2017-02-03"),
            (1919, "SM: Guardians Rising", "2017-05-05"),
            (1957, "SM: Burning Shadows", "2017-08-04"),
            (2071, "SM: Crimson Invasion", "2017-11-03"),
            (2178, "SM: Ultra Prism", "2018-02-02"),
            (2209, "SM: Forbidden Light", "2018-05-04"),
            (2278, "SM: Celestial Storm", "2018-08-03"),
            (2328, "SM: Lost Thunder", "2018-11-02"),
            (2377, "SM: Team Up", "2019-02-01"),
            (2420, "SM: Unbroken Bonds", "2019-05-03"),
            (2464, "SM: Unified Minds", "2019-08-02"),
            (2534, "SM: Cosmic Eclipse", "2019-11-01"),
        ],
    },
    "XY (2014-2016)": {
        "color_palette": ["#4CAF50", "#66BB6A", "#81C784", "#A5D6A7", "#C8E6C9",
                          "#43A047", "#388E3C", "#2E7D32", "#1B5E20", "#0D4F0D"],
        "sets": [
            (1387, "XY: Base Set", "2014-02-05"),
            (1464, "XY: Flashfire", "2014-05-07"),
            (1481, "XY: Furious Fists", "2014-08-13"),
            (1494, "XY: Phantom Forces", "2014-11-05"),
            (1509, "XY: Primal Clash", "2015-02-04"),
            (1534, "XY: Roaring Skies", "2015-05-06"),
            (1576, "XY: Ancient Origins", "2015-08-12"),
            (1661, "XY: BREAKthrough", "2015-11-04"),
            (1701, "XY: BREAKpoint", "2016-02-03"),
            (1780, "XY: Fates Collide", "2016-05-02"),
            (1815, "XY: Steam Siege", "2016-08-03"),
            (1842, "XY: Evolutions", "2016-11-02"),
        ],
    },
    "Mega Evolution (2025-2026)": {
        "color_palette": ["#9C27B0", "#AB47BC", "#BA68C8", "#CE93D8", "#E1BEE7"],
        "sets": [
            (24380, "ME01: Mega Evolution", "2025-09-26"),
            (24448, "ME02: Phantasmal Flames", "2025-11-14"),
            (24587, "ME03: Perfect Order", "2026-03-27"),
        ],
    },
}


def find_booster_product(products: list[dict], product_type: str) -> dict | None:
    """
    Find the standard booster pack or booster box from a set's product list.
    Avoids sleeved packs, art bundles, cases, code cards, half boxes, etc.
    """
    candidates = []
    for p in products:
        name_lower = p["name"].lower()

        # Skip unwanted variants
        skip_words = [
            "sleeved", "art bundle", "bundle", "case", "code card",
            "set of", "half", "display", "trainer kit", "exclusive",
        ]
        if any(w in name_lower for w in skip_words):
            continue

        if product_type == "pack" and "booster pack" in name_lower:
            candidates.append(p)
        elif product_type == "box" and "booster box" in name_lower:
            candidates.append(p)

    # Return the shortest name (most generic/standard version)
    if candidates:
        return min(candidates, key=lambda p: len(p["name"]))
    return None


def load_set_product_history(group_id: int, set_name: str, product_type: str,
                             release_date_str: str, progress_callback=None):
    """
    Load historical data for a set and return the booster pack or box price series
    aligned to days since release (starting from -30).

    Returns: (product_name, pd.Series indexed by days_since_release) or (None, None)
    """
    release_date = datetime.strptime(release_date_str, "%Y-%m-%d").date()
    earliest_available = date(2024, 2, 8)

    # We want data starting 30 days before release
    data_start = release_date - timedelta(days=30)
    data_start = max(data_start, earliest_available)
    data_end = min(date.today() - timedelta(days=1), date.today())

    # If this set released before our data starts, skip
    if release_date < earliest_available - timedelta(days=30):
        return None, None, "No historical data (set predates Feb 2024 archives)"

    # Load historical data
    stats = load_history_for_set(
        group_id=group_id,
        set_name=set_name,
        start_date=data_start,
        end_date=data_end,
        progress_callback=progress_callback,
    )

    # Find the target product
    client = TCGCSVClient()
    try:
        products = client.get_products_in_set(group_id)
    except Exception:
        return None, None, "Failed to fetch product catalog"

    target = find_booster_product(products, product_type)
    if not target:
        return None, None, f"No standard booster {product_type} found in set"

    # Get price history from database
    conn = get_connection()
    # Find our DB product ID
    db_product = None
    db_products = db.search_products(conn, target["name"])
    for p in db_products:
        if p.get("tcg_product_id") == target["productId"]:
            db_product = p
            break

    if not db_product:
        conn.close()
        return None, None, "Product not found in database after loading"

    snapshots = db.get_daily_snapshots(conn, db_product["id"])
    conn.close()

    if not snapshots:
        return None, None, "No price data available"

    df = pd.DataFrame(snapshots)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["tcg_market_price"].notna()].sort_values("date")

    if df.empty:
        return None, None, "No market price data"

    # Align to days since release
    df["days_since_release"] = (df["date"] - pd.Timestamp(release_date)).dt.days
    series = df.set_index("days_since_release")["tcg_market_price"]

    # Filter to -30 onward
    series = series[series.index >= -30]

    return target["name"], series, None


# ========================
# UI
# ========================

# --- Era selection ---
st.subheader("1. Select Eras to Compare")
selected_eras = st.multiselect(
    "Choose eras",
    options=list(ERAS.keys()),
    default=["Scarlet & Violet (2023-2025)", "Sword & Shield (2020-2023)"],
)

if not selected_eras:
    st.warning("Select at least one era to compare.")
    st.stop()

# --- Product type tabs ---
tab_pack, tab_box = st.tabs(["📦 Booster Pack", "📦 Booster Box"])

# Show which sets have data available
st.subheader("2. Load Historical Data")
st.caption(
    "This downloads daily price archives from TCGCSV (Feb 2024+). "
    "Sets released before Feb 2024 won't have historical data. "
    "Loading may take several minutes for many sets."
)

# Collect all sets from selected eras
all_selected_sets = []
for era_name in selected_eras:
    era = ERAS[era_name]
    for gid, sname, rdate in era["sets"]:
        all_selected_sets.append((era_name, gid, sname, rdate))

# Let user pick how many days of history to load
days_after = st.slider(
    "Days after release to include",
    min_value=30, max_value=730, value=365, step=30,
    help="How many days after release to show in the chart",
)

if st.button(f"Load data for {len(all_selected_sets)} sets across {len(selected_eras)} eras", type="primary"):
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, (era_name, gid, sname, rdate) in enumerate(all_selected_sets):
        release_dt = datetime.strptime(rdate, "%Y-%m-%d").date()
        data_start = max(release_dt - timedelta(days=30), date(2024, 2, 8))
        data_end = min(release_dt + timedelta(days=days_after), date.today() - timedelta(days=1))

        if data_end < data_start:
            continue

        progress_bar.progress((i + 1) / len(all_selected_sets))
        status_text.text(f"Loading {sname} ({i+1}/{len(all_selected_sets)})...")

        try:
            load_history_for_set(
                group_id=gid,
                set_name=sname,
                start_date=data_start,
                end_date=data_end,
            )
        except Exception as e:
            st.warning(f"Error loading {sname}: {e}")

    progress_bar.empty()
    status_text.empty()
    st.success(f"Data loaded for {len(all_selected_sets)} sets!")


# ========================
# BUILD CHARTS
# ========================

def build_era_chart(product_type: str, product_label: str):
    """Build a comparison chart for either 'pack' or 'box'."""
    fig = go.Figure()
    no_data_sets = []
    has_any_data = False

    for era_name in selected_eras:
        era = ERAS[era_name]
        colors = era["color_palette"]

        for i, (gid, sname, rdate) in enumerate(era["sets"]):
            release_dt = datetime.strptime(rdate, "%Y-%m-%d").date()

            # Find the product in the database
            client = st.session_state.get("tcg_client")
            if not client:
                client = TCGCSVClient()
                st.session_state.tcg_client = client

            try:
                products = client.get_products_in_set(gid)
            except Exception:
                no_data_sets.append(sname)
                continue

            target = find_booster_product(products, product_type)
            if not target:
                no_data_sets.append(f"{sname} (no {product_label})")
                continue

            # Get from database
            conn = get_connection()
            db_products = db.search_products(conn, target["name"])
            db_product = None
            for p in db_products:
                if p.get("tcg_product_id") == target["productId"]:
                    db_product = p
                    break

            if not db_product:
                conn.close()
                no_data_sets.append(f"{sname} (not loaded)")
                continue

            snapshots = db.get_daily_snapshots(conn, db_product["id"])
            conn.close()

            if not snapshots:
                no_data_sets.append(f"{sname} (no price data)")
                continue

            df = pd.DataFrame(snapshots)
            df["date"] = pd.to_datetime(df["date"])
            df = df[df["tcg_market_price"].notna()].sort_values("date")

            if df.empty:
                continue

            df["days_since_release"] = (df["date"] - pd.Timestamp(release_dt)).dt.days
            series = df.set_index("days_since_release")["tcg_market_price"]
            series = series[series.index >= -30]

            if len(series) < 2:
                continue

            has_any_data = True
            color = colors[i % len(colors)]

            # Short label for legend
            short_name = sname.split(":")[1].strip() if ":" in sname else sname

            fig.add_trace(go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines",
                name=short_name,
                line=dict(color=color, width=2),
                legendgroup=era_name,
                legendgrouptitle_text=era_name,
                hovertemplate=(
                    f"<b>{short_name}</b><br>"
                    f"Day %{{x}}: $%{{y:.2f}}<extra></extra>"
                ),
            ))

    if not has_any_data:
        st.info(
            f"No {product_label} price data loaded yet. "
            f"Click 'Load data' above to download historical archives."
        )
        return

    # Add vertical line at release day
    fig.add_vline(x=0, line_dash="dash", line_color="red",
                  annotation_text="Release Day", annotation_position="top left")
    fig.add_vline(x=-30, line_dash="dot", line_color="gray",
                  annotation_text="30 Days Pre-Release", annotation_position="top left")

    fig.update_layout(
        title=f"{product_label} Price — Days Since Release (by Era)",
        xaxis_title="Days Since Release",
        yaxis_title="Price (USD)",
        hovermode="x unified",
        template="plotly_white",
        height=650,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
        ),
    )

    st.plotly_chart(fig, use_container_width=True)

    # --- Normalized version ---
    st.markdown(f"#### Normalized {product_label} Price (100 = Release Day Price)")

    fig2 = go.Figure()
    color_idx = 0

    for era_name in selected_eras:
        era = ERAS[era_name]
        colors = era["color_palette"]

        for i, (gid, sname, rdate) in enumerate(era["sets"]):
            release_dt = datetime.strptime(rdate, "%Y-%m-%d").date()

            client = st.session_state.get("tcg_client", TCGCSVClient())
            try:
                products = client.get_products_in_set(gid)
            except Exception:
                continue

            target = find_booster_product(products, product_type)
            if not target:
                continue

            conn = get_connection()
            db_products = db.search_products(conn, target["name"])
            db_product = None
            for p in db_products:
                if p.get("tcg_product_id") == target["productId"]:
                    db_product = p
                    break

            if not db_product:
                conn.close()
                continue

            snapshots = db.get_daily_snapshots(conn, db_product["id"])
            conn.close()

            if not snapshots:
                continue

            df = pd.DataFrame(snapshots)
            df["date"] = pd.to_datetime(df["date"])
            df = df[df["tcg_market_price"].notna()].sort_values("date")

            if df.empty:
                continue

            df["days_since_release"] = (df["date"] - pd.Timestamp(release_dt)).dt.days
            series = df.set_index("days_since_release")["tcg_market_price"]
            series = series[series.index >= -30]

            if len(series) < 2:
                continue

            # Normalize to release day price (day 0 or closest to it)
            release_day_prices = series[(series.index >= -1) & (series.index <= 1)]
            if not release_day_prices.empty:
                base_price = release_day_prices.iloc[0]
            else:
                base_price = series.iloc[0]

            if base_price <= 0:
                continue

            normalized = (series / base_price) * 100
            color = colors[i % len(colors)]
            short_name = sname.split(":")[1].strip() if ":" in sname else sname

            fig2.add_trace(go.Scatter(
                x=normalized.index,
                y=normalized.values,
                mode="lines",
                name=short_name,
                line=dict(color=color, width=2),
                legendgroup=era_name,
                legendgrouptitle_text=era_name,
            ))

    fig2.add_hline(y=100, line_dash="dot", line_color="gray", annotation_text="Release Price")
    fig2.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="Release Day")

    fig2.update_layout(
        title=f"Normalized {product_label} Price Index (100 = Release Day)",
        xaxis_title="Days Since Release",
        yaxis_title="Price Index",
        hovermode="x unified",
        template="plotly_white",
        height=650,
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
    )

    st.plotly_chart(fig2, use_container_width=True)

    # --- Era average comparison ---
    if len(selected_eras) >= 2:
        st.markdown(f"#### Average {product_label} Price Pattern by Era")
        st.caption("Average normalized price across all sets in each era — shows the typical pattern for each generation.")

        fig3 = go.Figure()
        era_primary_colors = {
            "Scarlet & Violet (2023-2025)": "#FF6B35",
            "Sword & Shield (2020-2023)": "#2196F3",
            "Sun & Moon (2017-2019)": "#FFC107",
            "XY (2014-2016)": "#4CAF50",
            "Mega Evolution (2025-2026)": "#9C27B0",
        }

        for era_name in selected_eras:
            era = ERAS[era_name]
            all_norm = {}

            for i, (gid, sname, rdate) in enumerate(era["sets"]):
                release_dt = datetime.strptime(rdate, "%Y-%m-%d").date()
                client = st.session_state.get("tcg_client", TCGCSVClient())

                try:
                    products = client.get_products_in_set(gid)
                except Exception:
                    continue

                target = find_booster_product(products, product_type)
                if not target:
                    continue

                conn = get_connection()
                db_products = db.search_products(conn, target["name"])
                db_product = None
                for p in db_products:
                    if p.get("tcg_product_id") == target["productId"]:
                        db_product = p
                        break

                if not db_product:
                    conn.close()
                    continue

                snapshots = db.get_daily_snapshots(conn, db_product["id"])
                conn.close()

                if not snapshots:
                    continue

                df = pd.DataFrame(snapshots)
                df["date"] = pd.to_datetime(df["date"])
                df = df[df["tcg_market_price"].notna()].sort_values("date")
                if df.empty:
                    continue

                df["days_since_release"] = (df["date"] - pd.Timestamp(release_dt)).dt.days
                series = df.set_index("days_since_release")["tcg_market_price"]
                series = series[series.index >= -30]

                if len(series) < 2:
                    continue

                release_day_prices = series[(series.index >= -1) & (series.index <= 1)]
                base = release_day_prices.iloc[0] if not release_day_prices.empty else series.iloc[0]
                if base > 0:
                    all_norm[sname] = (series / base) * 100

            if all_norm:
                combined = pd.DataFrame(all_norm)
                avg = combined.mean(axis=1).dropna()

                color = era_primary_colors.get(era_name, "#999999")

                fig3.add_trace(go.Scatter(
                    x=avg.index,
                    y=avg.values,
                    mode="lines",
                    name=f"{era_name} ({len(all_norm)} sets)",
                    line=dict(color=color, width=3),
                ))

        fig3.add_hline(y=100, line_dash="dot", line_color="gray")
        fig3.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="Release Day")

        fig3.update_layout(
            title=f"Average {product_label} Price by Era",
            xaxis_title="Days Since Release",
            yaxis_title="Average Price Index (100 = Release)",
            hovermode="x unified",
            template="plotly_white",
            height=550,
        )

        st.plotly_chart(fig3, use_container_width=True)

    # Show sets with missing data
    if no_data_sets:
        with st.expander(f"Sets without {product_label} data ({len(no_data_sets)})"):
            for s in no_data_sets:
                st.caption(f"• {s}")


# --- Render charts in tabs ---
with tab_pack:
    build_era_chart("pack", "Booster Pack")

with tab_box:
    build_era_chart("box", "Booster Box")


# --- Key Insights ---
st.markdown("---")
st.markdown("### How to Read These Charts")
st.markdown("""
- **Day 0** = public release date for each set
- **Days -30 to 0** = pre-release period (prices often inflated due to hype/scarcity)
- **Days 0-90** = initial decline period as supply floods the market
- **Days 90-365+** = stabilization and potential recovery period

**Investment Strategy Insights:**
- Look for the **average bottom** — the day when prices typically stop declining
- Compare eras to see if newer sets decline faster or recover sooner
- Sets that maintain value better may indicate stronger long-term demand
- Pre-release price spikes show the "hype premium" that typically deflates
""")

st.caption(
    "⚠️ Historical data available from Feb 2024 onward. "
    "Older era sets (XY, Sun & Moon) will not have archive data. "
    "Past performance does not predict future results."
)
