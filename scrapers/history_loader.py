"""
Historical price data loader using TCGCSV daily archives.
Downloads compressed daily price snapshots from Feb 2024 onward
and loads them into the local database.

Archives are ~3MB each (7z compressed) and contain prices for ALL
TCGPlayer categories. We extract only Pokemon (category 3) data
for the requested set(s).
"""

import io
import json
import os
import time
import tempfile
from datetime import date, timedelta, datetime
from pathlib import Path

import requests
import py7zr

from config.settings import PROJECT_ROOT, POKEMON_CATEGORY_ID, REQUEST_DELAY
from database.models import get_connection
from database import operations as db

ARCHIVE_BASE_URL = "https://tcgcsv.com/archive/tcgplayer"
CACHE_DIR = PROJECT_ROOT / "data_cache"


def get_available_date_range() -> tuple[date, date]:
    """Return the earliest and latest available archive dates."""
    earliest = date(2024, 2, 8)  # TCGCSV archives start here
    latest = date.today() - timedelta(days=1)  # Yesterday is the latest
    return earliest, latest


def download_and_extract_prices(archive_date: date, group_id: int) -> list[dict] | None:
    """
    Download one day's archive and extract prices for a specific Pokemon set.

    Args:
        archive_date: The date to fetch prices for
        group_id: TCGPlayer group ID for the Pokemon set

    Returns:
        List of price dicts, or None if the archive is unavailable
    """
    date_str = archive_date.isoformat()
    url = f"{ARCHIVE_BASE_URL}/prices-{date_str}.ppmd.7z"

    try:
        response = requests.get(url, timeout=120)
        if response.status_code != 200:
            return None
    except requests.RequestException:
        return None

    # Extract in memory using a temp file (py7zr needs seekable file)
    try:
        with tempfile.NamedTemporaryFile(suffix=".7z", delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        with py7zr.SevenZipFile(tmp_path, mode="r") as archive:
            # Target file path inside the archive
            target = f"{date_str}/{POKEMON_CATEGORY_ID}/{group_id}/prices"
            all_names = archive.getnames()

            if target not in all_names:
                return None  # This set doesn't exist in this archive

            # Extract to temp directory
            tmpdir = tempfile.mkdtemp()
            archive.extractall(path=tmpdir)

        # Read the extracted price file
        price_file = os.path.join(tmpdir, target)
        if not os.path.exists(price_file):
            return None

        with open(price_file) as f:
            data = json.load(f)

        prices = data.get("results", [])

        # Clean up
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
        os.unlink(tmp_path)

        return prices

    except Exception as e:
        # Clean up on error
        try:
            os.unlink(tmp_path)
        except:
            pass
        print(f"Error extracting archive for {date_str}: {e}")
        return None


def load_history_for_set(group_id: int, set_name: str,
                         start_date: date = None, end_date: date = None,
                         progress_callback=None) -> dict:
    """
    Load historical prices for all products in a Pokemon set.

    Downloads daily archives from TCGCSV and stores prices in the database.
    This can take a while for large date ranges (each archive is ~3MB).

    Args:
        group_id: TCGPlayer group ID for the set
        set_name: Display name of the set
        start_date: Earliest date to fetch (default: Feb 8, 2024)
        end_date: Latest date to fetch (default: yesterday)
        progress_callback: Optional function(current, total, date_str) for progress updates

    Returns:
        dict with: dates_loaded, products_found, prices_stored, errors
    """
    earliest, latest = get_available_date_range()

    if start_date is None:
        start_date = earliest
    else:
        start_date = max(start_date, earliest)

    if end_date is None:
        end_date = latest
    else:
        end_date = min(end_date, latest)

    # First, make sure we have the products for this set in our database
    from scrapers.tcg_client import TCGCSVClient
    client = TCGCSVClient()

    conn = get_connection()

    # Fetch and save product catalog for this set
    try:
        products = client.get_products_in_set(group_id)
    except Exception as e:
        conn.close()
        return {"dates_loaded": 0, "products_found": 0, "prices_stored": 0,
                "errors": [f"Failed to fetch products: {e}"]}

    # Map TCG product IDs to our database IDs
    product_id_map = {}  # tcg_product_id -> our_db_id
    for p in products:
        tcg_pid = p["productId"]
        db_id = db.upsert_product(
            conn,
            name=p.get("name", ""),
            set_name=set_name,
            product_type="card",
            tcg_product_id=tcg_pid,
            tcg_group_id=group_id,
            image_url=p.get("imageUrl", ""),
        )
        product_id_map[tcg_pid] = db_id

    # Generate list of dates to fetch
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)

    stats = {
        "dates_loaded": 0,
        "products_found": len(product_id_map),
        "prices_stored": 0,
        "errors": [],
    }

    # Download archives day by day
    for i, d in enumerate(dates):
        if progress_callback:
            progress_callback(i + 1, len(dates), d.isoformat())

        date_str = d.isoformat()

        # Skip if we already have data for this date
        # (Check one product as a proxy)
        if product_id_map:
            sample_db_id = next(iter(product_id_map.values()))
            existing = db.get_price_history(
                conn, sample_db_id,
                start_date=date_str, end_date=date_str,
                source="tcgplayer"
            )
            if existing:
                stats["dates_loaded"] += 1
                continue

        # Download and extract
        prices = download_and_extract_prices(d, group_id)

        if prices is None:
            # Archive might not exist for this date (weekends, gaps)
            continue

        # Store prices for products we know about
        day_count = 0
        for price_entry in prices:
            tcg_pid = price_entry.get("productId")
            if tcg_pid not in product_id_map:
                continue

            our_id = product_id_map[tcg_pid]
            market_price = price_entry.get("marketPrice")
            low_price = price_entry.get("lowPrice")
            mid_price = price_entry.get("midPrice")
            high_price = price_entry.get("highPrice")
            variant = price_entry.get("subTypeName", "Normal")

            if market_price is not None:
                db.insert_price_point(
                    conn, our_id, "tcgplayer", market_price,
                    price_type="market", variant=variant.lower().replace(" ", "_"),
                    observed_date=date_str,
                )
                day_count += 1

            if low_price is not None:
                db.insert_price_point(
                    conn, our_id, "tcgplayer", low_price,
                    price_type="low", variant=variant.lower().replace(" ", "_"),
                    observed_date=date_str,
                )

            if high_price is not None:
                db.insert_price_point(
                    conn, our_id, "tcgplayer", high_price,
                    price_type="high", variant=variant.lower().replace(" ", "_"),
                    observed_date=date_str,
                )

            # Also update daily snapshot
            db.upsert_daily_snapshot(
                conn, our_id,
                snapshot_date=date_str,
                tcg_market_price=market_price,
                tcg_low_price=low_price,
                tcg_mid_price=mid_price,
            )

        stats["prices_stored"] += day_count
        stats["dates_loaded"] += 1

        # Rate limit between archive downloads
        if i < len(dates) - 1:
            time.sleep(0.5)

    conn.close()
    return stats


# Self-test
if __name__ == "__main__":
    print("=== Testing historical data loader ===")
    print("Loading 3 days of Prismatic Evolutions data...")

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=2)

    def progress(current, total, date_str):
        print(f"  [{current}/{total}] {date_str}")

    stats = load_history_for_set(
        group_id=23821,
        set_name="SV: Prismatic Evolutions",
        start_date=start,
        end_date=end,
        progress_callback=progress,
    )

    print(f"\nResults:")
    print(f"  Dates loaded: {stats['dates_loaded']}")
    print(f"  Products found: {stats['products_found']}")
    print(f"  Prices stored: {stats['prices_stored']}")
    if stats["errors"]:
        print(f"  Errors: {stats['errors']}")
