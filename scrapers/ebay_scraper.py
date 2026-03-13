"""
eBay sold listings scraper.
Scrapes completed/sold listings from eBay search results.
No API key needed — uses public search pages.

Important: Be respectful with request frequency. Default 3s delay between pages.
eBay's current HTML (Jan 2026) uses 's-card' class for listing items.

Note: eBay has bot detection that may occasionally block requests.
The scraper handles this with retries and graceful fallbacks.
"""

import re
import time
import random
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from config.settings import EBAY_SEARCH_URL, REQUEST_DELAY


# Rotate through common Chrome user agents
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


class EbaySoldScraper:
    """Scrapes sold/completed listings from eBay search results."""

    def __init__(self):
        self._session = None
        self._warmed_up = False

    def _get_session(self) -> requests.Session:
        """Create a fresh session with randomized user agent."""
        session = requests.Session()
        ua = random.choice(_USER_AGENTS)
        session.headers.update({
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
        })
        return session

    def _warm_up(self, session: requests.Session):
        """Visit eBay homepage to establish cookies."""
        try:
            session.get("https://www.ebay.com/", timeout=15)
            time.sleep(random.uniform(1.5, 3.0))
        except requests.RequestException:
            pass

    def search_sold(self, query: str, max_pages: int = 2, max_retries: int = 2) -> list[dict]:
        """
        Search eBay for sold/completed listings.

        Args:
            query: Search term (e.g., "Pokemon Charizard ex")
            max_pages: Number of result pages to scrape (each has ~60 items)
            max_retries: Number of retries if blocked

        Returns:
            List of dicts with keys: title, price, sold_date, url, condition
        """
        all_results = []
        formatted_query = query.replace(" ", "+")

        for attempt in range(max_retries + 1):
            session = self._get_session()
            self._warm_up(session)
            blocked = False

            for page in range(1, max_pages + 1):
                url = (
                    f"{EBAY_SEARCH_URL}?_nkw={formatted_query}"
                    f"&_sacat=0&rt=nc&LH_Sold=1&LH_Complete=1&_pgn={page}"
                )

                if page > 1:
                    time.sleep(REQUEST_DELAY + random.uniform(0, 2))

                try:
                    response = session.get(url, timeout=30)
                    if response.status_code != 200:
                        break

                    # Check for bot detection page
                    if len(response.text) < 50000 and "pardon" in response.text.lower():
                        blocked = True
                        break

                    items = self._parse_page(response.text)
                    if not items:
                        break

                    all_results.extend(items)

                except requests.RequestException as e:
                    print(f"Error fetching page {page}: {e}")
                    break

            if blocked and attempt < max_retries:
                all_results = []
                wait = (attempt + 1) * 5 + random.uniform(0, 3)
                print(f"eBay blocked request, retrying in {wait:.0f}s... (attempt {attempt + 2}/{max_retries + 1})")
                time.sleep(wait)
                continue
            else:
                break

        return all_results

    def _parse_page(self, html: str) -> list[dict]:
        """Parse sold listings from a search results page."""
        soup = BeautifulSoup(html, "lxml")
        items = []

        # Find the results container
        results_list = soup.find("ul", class_="srp-results")
        if not results_list:
            return items

        # Current eBay uses s-card class for listing items
        cards = results_list.find_all("li", class_="s-card", recursive=False)

        # Fallback: try s-item class (older eBay layout)
        if not cards:
            cards = results_list.find_all("li", class_="s-item", recursive=False)

        for card in cards:
            try:
                item = self._parse_card(card)
                if item and item["price"] is not None:
                    items.append(item)
            except Exception:
                continue

        return items

    def _parse_card(self, card) -> dict | None:
        """Parse a single listing element (supports s-card and s-item layouts)."""
        # --- Title ---
        title = ""

        # s-card layout: img alt text
        img = card.find("img", class_="s-card__image")
        if img:
            title = img.get("alt", "").strip()

        # s-item layout fallback
        if not title:
            title_div = card.find("div", class_="s-item__title")
            if title_div:
                title = title_div.get_text(strip=True)

        # Generic heading fallback
        if not title:
            heading = card.find("span", role="heading")
            if heading:
                title = heading.get_text(strip=True)

        if not title:
            return None

        skip_titles = {"shop on ebay", "results matching fewer words", ""}
        if title.lower() in skip_titles:
            return None

        # --- URL ---
        url = ""
        for link in card.find_all("a"):
            href = link.get("href", "")
            if "/itm/" in href:
                url = href.split("?")[0]
                break

        # --- Price ---
        price = None
        # s-card layout
        price_el = card.find(class_="s-card__price")
        # s-item layout fallback
        if not price_el:
            price_el = card.find("span", class_="s-item__price")
        if price_el:
            price = self._parse_price(price_el.get_text(strip=True))

        # --- Sold date ---
        sold_date = None
        for span in card.find_all("span"):
            text = span.get_text(strip=True)
            if text.startswith("Sold"):
                sold_date = self._parse_date(text)
                if sold_date:
                    break

        # --- Condition ---
        condition = ""
        known_conditions = {
            "new", "pre-owned", "brand new", "used", "open box",
            "certified - refurbished", "for parts or not working",
        }
        for span in card.find_all("span"):
            text = span.get_text(strip=True)
            if text.lower() in known_conditions:
                condition = text
                break

        return {
            "title": title,
            "price": price,
            "sold_date": sold_date,
            "url": url,
            "condition": condition,
        }

    def _parse_price(self, price_text: str) -> float | None:
        """Extract numeric price from eBay price text."""
        if not price_text:
            return None

        numbers = re.findall(r"[\d,]+\.?\d*", price_text)
        if not numbers:
            return None

        parsed = []
        for n in numbers:
            try:
                parsed.append(float(n.replace(",", "")))
            except ValueError:
                continue

        if not parsed:
            return None

        return sum(parsed) / len(parsed)

    def _parse_date(self, date_text: str) -> str | None:
        """Parse sold date. Input: 'Sold  Jan 15, 2026' -> '2026-01-15'"""
        if not date_text:
            return None

        cleaned = re.sub(r"^Sold\s+", "", date_text, flags=re.IGNORECASE).strip()

        formats = [
            "%b %d, %Y", "%d %b, %Y", "%b %d %Y",
            "%d %b %Y", "%B %d, %Y",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(cleaned, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        return None


# Module self-test
if __name__ == "__main__":
    scraper = EbaySoldScraper()

    print("=== Searching eBay sold listings for 'Pokemon Charizard ex' ===")
    print("(This may take a moment due to rate limiting...)\n")
    results = scraper.search_sold("Pokemon Charizard ex", max_pages=1)
    print(f"Found {len(results)} sold listings\n")

    for item in results[:10]:
        print(f"  Title: {item['title'][:70]}")
        print(f"  Price: ${item['price']:.2f}" if item["price"] else "  Price: N/A")
        print(f"  Sold:  {item['sold_date'] or 'Unknown'}")
        print(f"  Cond:  {item['condition'] or 'N/A'}")
        print(f"  URL:   {item['url'][:60]}")
        print()
