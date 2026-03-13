"""
Application configuration and constants.
Loads settings from .env file and defines paths used throughout the app.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Find the project root (one level up from config/)
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- Paths ---
DATABASE_PATH = PROJECT_ROOT / "database" / "pokemon_cards.db"

# --- Request Settings ---
REQUEST_DELAY = int(os.getenv("REQUEST_DELAY_SECONDS", "3"))

# --- TCGCSV API (free, no key needed) ---
TCGCSV_BASE_URL = "https://tcgcsv.com/tcgplayer"
POKEMON_CATEGORY_ID = "3"

# --- eBay Scraping ---
EBAY_SEARCH_URL = "https://www.ebay.com/sch/i.html"
EBAY_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
