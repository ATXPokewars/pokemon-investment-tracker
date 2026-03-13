"""
Database schema definition and initialization.
Creates all SQLite tables on first run.
"""

import sqlite3
from config.settings import DATABASE_PATH


def get_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row  # Access columns by name
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialize_database():
    """Create all tables if they don't already exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        -- Products: catalog of tracked Pokemon cards and sealed products
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            set_name TEXT,
            product_type TEXT DEFAULT 'card',
            tcg_product_id INTEGER,
            tcg_group_id INTEGER,
            image_url TEXT,
            rarity TEXT,
            release_date TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(tcg_product_id)
        );

        -- Price points: every observed price from any source
        CREATE TABLE IF NOT EXISTS price_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            price REAL NOT NULL,
            price_type TEXT DEFAULT 'market',
            condition TEXT DEFAULT 'near_mint',
            variant TEXT DEFAULT 'normal',
            observed_date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        -- eBay sold listings: detailed records from scraping
        CREATE TABLE IF NOT EXISTS ebay_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            title TEXT NOT NULL,
            sold_price REAL NOT NULL,
            sold_date TEXT,
            listing_url TEXT,
            condition TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        -- Portfolio: user's investment holdings
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            purchase_price REAL NOT NULL,
            purchase_date TEXT NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );

        -- Daily snapshots: aggregated daily prices for fast charting
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            tcg_market_price REAL,
            tcg_low_price REAL,
            tcg_mid_price REAL,
            ebay_avg_sold REAL,
            ebay_median_sold REAL,
            ebay_num_sales INTEGER DEFAULT 0,
            FOREIGN KEY (product_id) REFERENCES products(id),
            UNIQUE(product_id, date)
        );

        -- Indexes for performance
        CREATE INDEX IF NOT EXISTS idx_price_points_product_date
            ON price_points(product_id, observed_date);
        CREATE INDEX IF NOT EXISTS idx_daily_snapshots_product_date
            ON daily_snapshots(product_id, date);
        CREATE INDEX IF NOT EXISTS idx_products_name
            ON products(name);
        CREATE INDEX IF NOT EXISTS idx_ebay_listings_product
            ON ebay_listings(product_id, sold_date);
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    initialize_database()
    print(f"Database initialized at: {DATABASE_PATH}")

    # Quick self-test
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO products (name, set_name, product_type, tcg_product_id) "
        "VALUES (?, ?, ?, ?)",
        ("Charizard ex", "Obsidian Flames", "card", 99999),
    )
    conn.commit()
    cursor.execute("SELECT * FROM products WHERE tcg_product_id = 99999")
    row = cursor.fetchone()
    if row:
        print(f"Test passed: Found product '{row['name']}' in set '{row['set_name']}'")
    # Clean up test data
    cursor.execute("DELETE FROM products WHERE tcg_product_id = 99999")
    conn.commit()
    conn.close()
