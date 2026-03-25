"""
Database CRUD operations.
All functions accept a sqlite3.Connection and use parameterized queries.
"""

import sqlite3
from datetime import datetime, date


# --- Products ---

def upsert_product(conn: sqlite3.Connection, name: str, set_name: str = None,
                   product_type: str = "card", tcg_product_id: int = None,
                   tcg_group_id: int = None, image_url: str = None,
                   rarity: str = None, release_date: str = None) -> int:
    """Insert a product or update it if tcg_product_id already exists. Returns product id."""
    cursor = conn.cursor()

    if tcg_product_id:
        cursor.execute("SELECT id FROM products WHERE tcg_product_id = ?", (tcg_product_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE products SET name=?, set_name=?, product_type=?, tcg_group_id=?, "
                "image_url=?, rarity=?, release_date=?, updated_at=datetime('now') WHERE id=?",
                (name, set_name, product_type, tcg_group_id, image_url, rarity, release_date, row["id"]),
            )
            conn.commit()
            return row["id"]

    cursor.execute(
        "INSERT INTO products (name, set_name, product_type, tcg_product_id, tcg_group_id, "
        "image_url, rarity, release_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, set_name, product_type, tcg_product_id, tcg_group_id, image_url, rarity, release_date),
    )
    conn.commit()
    return cursor.lastrowid


def search_products(conn: sqlite3.Connection, query: str, limit: int = 50) -> list[dict]:
    """Search products by name or set name."""
    cursor = conn.cursor()
    pattern = f"%{query}%"
    cursor.execute(
        "SELECT * FROM products WHERE name LIKE ? OR set_name LIKE ? ORDER BY name LIMIT ?",
        (pattern, pattern, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


def get_product_by_id(conn: sqlite3.Connection, product_id: int) -> dict | None:
    """Get a single product by its database ID."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_all_tracked_products(conn: sqlite3.Connection) -> list[dict]:
    """Get all products that have at least one price point recorded."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT p.* FROM products p "
        "INNER JOIN price_points pp ON p.id = pp.product_id "
        "ORDER BY p.name"
    )
    return [dict(row) for row in cursor.fetchall()]


# --- Price Points ---

def insert_price_point(conn: sqlite3.Connection, product_id: int, source: str,
                       price: float, price_type: str = "market",
                       condition: str = "near_mint", variant: str = "normal",
                       observed_date: str = None) -> int:
    """Record a single price observation."""
    if observed_date is None:
        observed_date = date.today().isoformat()

    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO price_points (product_id, source, price, price_type, condition, "
        "variant, observed_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (product_id, source, price, price_type, condition, variant, observed_date),
    )
    conn.commit()
    return cursor.lastrowid


def get_price_history(conn: sqlite3.Connection, product_id: int,
                      start_date: str = None, end_date: str = None,
                      source: str = None) -> list[dict]:
    """Get price history for a product, optionally filtered by date range and source."""
    query = "SELECT * FROM price_points WHERE product_id = ?"
    params = [product_id]

    if start_date:
        query += " AND observed_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND observed_date <= ?"
        params.append(end_date)
    if source:
        query += " AND source = ?"
        params.append(source)

    query += " ORDER BY observed_date ASC"

    cursor = conn.cursor()
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def has_price_for_today(conn: sqlite3.Connection, product_id: int,
                        source: str) -> bool:
    """Check if we already have a price point for this product/source today."""
    today = date.today().isoformat()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM price_points "
        "WHERE product_id = ? AND source = ? AND observed_date = ?",
        (product_id, source, today),
    )
    return cursor.fetchone()["cnt"] > 0


# --- eBay Listings ---

def insert_ebay_listing(conn: sqlite3.Connection, product_id: int | None,
                        title: str, sold_price: float, sold_date: str = None,
                        listing_url: str = None, condition: str = None) -> int:
    """Store an eBay sold listing."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO ebay_listings (product_id, title, sold_price, sold_date, "
        "listing_url, condition) VALUES (?, ?, ?, ?, ?, ?)",
        (product_id, title, sold_price, sold_date, listing_url, condition),
    )
    conn.commit()
    return cursor.lastrowid


def get_ebay_listings(conn: sqlite3.Connection, product_id: int,
                      limit: int = 100) -> list[dict]:
    """Get stored eBay sold listings for a product."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM ebay_listings WHERE product_id = ? "
        "ORDER BY sold_date DESC LIMIT ?",
        (product_id, limit),
    )
    return [dict(row) for row in cursor.fetchall()]


# --- Daily Snapshots ---

def upsert_daily_snapshot(conn: sqlite3.Connection, product_id: int,
                          snapshot_date: str = None,
                          tcg_market_price: float = None,
                          tcg_low_price: float = None,
                          tcg_mid_price: float = None,
                          ebay_avg_sold: float = None,
                          ebay_median_sold: float = None,
                          ebay_num_sales: int = 0):
    """Insert or update a daily price snapshot for fast charting."""
    if snapshot_date is None:
        snapshot_date = date.today().isoformat()

    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO daily_snapshots (product_id, date, tcg_market_price, tcg_low_price, "
        "tcg_mid_price, ebay_avg_sold, ebay_median_sold, ebay_num_sales) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(product_id, date) DO UPDATE SET "
        "tcg_market_price=excluded.tcg_market_price, tcg_low_price=excluded.tcg_low_price, "
        "tcg_mid_price=excluded.tcg_mid_price, ebay_avg_sold=excluded.ebay_avg_sold, "
        "ebay_median_sold=excluded.ebay_median_sold, ebay_num_sales=excluded.ebay_num_sales",
        (product_id, snapshot_date, tcg_market_price, tcg_low_price, tcg_mid_price,
         ebay_avg_sold, ebay_median_sold, ebay_num_sales),
    )
    conn.commit()


def get_daily_snapshots(conn: sqlite3.Connection, product_id: int,
                        start_date: str = None, end_date: str = None) -> list[dict]:
    """Get daily snapshots for charting."""
    query = "SELECT * FROM daily_snapshots WHERE product_id = ?"
    params = [product_id]

    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)

    query += " ORDER BY date ASC"

    cursor = conn.cursor()
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


# --- Portfolio ---

def add_portfolio_item(conn: sqlite3.Connection, product_id: int,
                       quantity: int, purchase_price: float,
                       purchase_date: str, notes: str = None) -> int:
    """Add an item to the portfolio."""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO portfolio (product_id, quantity, purchase_price, purchase_date, notes) "
        "VALUES (?, ?, ?, ?, ?)",
        (product_id, quantity, purchase_price, purchase_date, notes),
    )
    conn.commit()
    return cursor.lastrowid


def get_portfolio(conn: sqlite3.Connection) -> list[dict]:
    """Get all portfolio items with product details."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT po.*, p.name, p.set_name, p.image_url "
        "FROM portfolio po "
        "INNER JOIN products p ON po.product_id = p.id "
        "ORDER BY po.purchase_date DESC"
    )
    return [dict(row) for row in cursor.fetchall()]


def delete_portfolio_item(conn: sqlite3.Connection, portfolio_id: int):
    """Remove an item from the portfolio."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM portfolio WHERE id = ?", (portfolio_id,))
    conn.commit()


# --- Graded Card Watchlist ---

def add_to_graded_watchlist(conn: sqlite3.Connection, card_name: str,
                            set_name: str = None, set_release_date: str = None,
                            pricecharting_id: str = None,
                            pricecharting_url: str = None) -> int:
    """Add a card to the graded watchlist. Returns watchlist id."""
    cursor = conn.cursor()
    if pricecharting_id:
        cursor.execute("SELECT id FROM graded_watchlist WHERE pricecharting_id = ?",
                        (pricecharting_id,))
        row = cursor.fetchone()
        if row:
            return row["id"]
    cursor.execute(
        "INSERT OR IGNORE INTO graded_watchlist "
        "(card_name, set_name, set_release_date, pricecharting_id, pricecharting_url) "
        "VALUES (?, ?, ?, ?, ?)",
        (card_name, set_name, set_release_date, pricecharting_id, pricecharting_url),
    )
    conn.commit()
    if cursor.lastrowid:
        return cursor.lastrowid
    cursor.execute("SELECT id FROM graded_watchlist WHERE pricecharting_id = ?",
                    (pricecharting_id,))
    return cursor.fetchone()["id"]


def remove_from_graded_watchlist(conn: sqlite3.Connection, watchlist_id: int):
    """Remove a card from the graded watchlist and its price history."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM graded_price_history WHERE watchlist_id = ?", (watchlist_id,))
    cursor.execute("DELETE FROM graded_watchlist WHERE id = ?", (watchlist_id,))
    conn.commit()


def get_graded_watchlist(conn: sqlite3.Connection) -> list[dict]:
    """Get all cards in the graded watchlist."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM graded_watchlist ORDER BY card_name")
    return [dict(row) for row in cursor.fetchall()]


def insert_graded_prices(conn: sqlite3.Connection, watchlist_id: int,
                          prices: list[dict]):
    """Bulk insert graded price history. Each dict: grading_company, grade, date, price, source."""
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT OR IGNORE INTO graded_price_history "
        "(watchlist_id, grading_company, grade, date, price, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(watchlist_id, p["grading_company"], p["grade"], p["date"],
          p["price"], p.get("source", "pricecharting")) for p in prices],
    )
    conn.commit()


def get_graded_price_history(conn: sqlite3.Connection, watchlist_id: int,
                              grading_company: str = None, grade: str = None,
                              start_date: str = None, end_date: str = None) -> list[dict]:
    """Get graded price history, optionally filtered."""
    query = "SELECT * FROM graded_price_history WHERE watchlist_id = ?"
    params: list = [watchlist_id]
    if grading_company:
        query += " AND grading_company = ?"
        params.append(grading_company)
    if grade:
        query += " AND grade = ?"
        params.append(grade)
    if start_date:
        query += " AND date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date <= ?"
        params.append(end_date)
    query += " ORDER BY date ASC"
    cursor = conn.cursor()
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]


def get_graded_price_history_multi(conn: sqlite3.Connection, watchlist_ids: list[int],
                                    grading_company: str = None,
                                    grade: str = None) -> list[dict]:
    """Get graded price history for multiple watchlist items."""
    if not watchlist_ids:
        return []
    placeholders = ",".join("?" * len(watchlist_ids))
    query = f"SELECT gph.*, gw.card_name, gw.set_name, gw.set_release_date " \
            f"FROM graded_price_history gph " \
            f"JOIN graded_watchlist gw ON gph.watchlist_id = gw.id " \
            f"WHERE gph.watchlist_id IN ({placeholders})"
    params: list = list(watchlist_ids)
    if grading_company:
        query += " AND gph.grading_company = ?"
        params.append(grading_company)
    if grade:
        query += " AND gph.grade = ?"
        params.append(grade)
    query += " ORDER BY gph.date ASC"
    cursor = conn.cursor()
    cursor.execute(query, params)
    return [dict(row) for row in cursor.fetchall()]
