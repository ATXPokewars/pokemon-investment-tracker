"""
PriceCharting.com scraper for graded Pokemon card prices.
Extracts historical price data from embedded VGPC.chart_data on card detail pages.
No API key needed — uses public pages.

PriceCharting embeds chart data as JavaScript arrays of [timestamp_ms, price_cents].
The chart_data keys map to card grades:
  used       -> Ungraded
  cib        -> Grade 7
  new        -> Grade 8
  graded     -> Grade 9
  boxonly    -> Grade 9.5
  manualonly -> PSA 10 / Grade 10
"""

import re
import json
import time
import random
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from config.settings import REQUEST_DELAY

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# Default mapping from chart_data keys to grade labels.
# This works for most Pokemon cards on PriceCharting.
# The scraper auto-verifies by matching latest chart values to displayed prices.
CHART_KEY_TO_GRADE = {
    "used": "Ungraded",
    "cib": "7",
    "new": "8",
    "graded": "9",
    "boxonly": "9.5",
    "manualonly": "10",
}

SEARCH_URL = "https://www.pricecharting.com/search-products"
BASE_URL = "https://www.pricecharting.com"


class PriceChartingClient:
    """Scrapes graded card price history from PriceCharting.com."""

    def __init__(self):
        self._session = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            ua = random.choice(_USER_AGENTS)
            self._session.headers.update({
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            })
        return self._session

    def search_cards(self, query: str, max_results: int = 20) -> list[dict]:
        """
        Search PriceCharting for Pokemon cards.

        Returns list of dicts: name, set_name, url, current_price
        """
        session = self._get_session()
        params = {"type": "prices", "q": query, "category": "pokemon-cards"}

        try:
            response = session.get(SEARCH_URL, params=params, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"PriceCharting search error: {e}")
            return []

        soup = BeautifulSoup(response.text, "lxml")
        results = []

        # Search results are in table#games_table as <tr> rows
        table = soup.select_one("table#games_table")
        if not table:
            table = soup.select_one("table#games_table_sticky")
        if not table:
            # Fallback: any table with price data
            table = soup.select_one("table")

        if not table:
            return results

        rows = table.select("tr")

        for row in rows[:max_results + 1]:  # +1 for possible header row
            try:
                # Card name — in td.title > a
                title_el = row.select_one("td.title a")
                if not title_el:
                    continue

                name = title_el.get_text(strip=True)
                url = title_el.get("href", "")
                if url and not url.startswith("http"):
                    url = BASE_URL + url

                # Set name — in td.console > a
                set_name = ""
                console_el = row.select_one("td.console a")
                if console_el:
                    set_name = console_el.get_text(strip=True)
                elif "/game/" in url:
                    parts = url.split("/game/")[1].split("/")
                    if parts:
                        set_name = parts[0].replace("-", " ").title()

                # Current price — first td.price
                price = None
                price_el = row.select_one("td.price")
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    price_match = re.search(r"[\d,]+\.?\d*", price_text)
                    if price_match:
                        price = float(price_match.group().replace(",", ""))

                results.append({
                    "name": name,
                    "set_name": set_name,
                    "url": url,
                    "current_price": price,
                    "pricecharting_id": url.split("/")[-1] if url else "",
                })
            except Exception:
                continue

        return results

    def get_card_details(self, url: str) -> dict | None:
        """
        Fetch a card detail page and extract:
        - Grade prices (current)
        - Historical chart data (VGPC.chart_data)
        - Product metadata

        Returns dict with keys: name, set_name, grades, chart_data, product_id
        """
        session = self._get_session()
        time.sleep(REQUEST_DELAY + random.uniform(0, 1))

        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"PriceCharting fetch error: {e}")
            return None

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        result = {
            "url": url,
            "name": "",
            "set_name": "",
            "grades": {},
            "chart_data": {},
            "product_id": None,
        }

        # --- Card name ---
        title_el = soup.select_one("h1#product_name")
        if not title_el:
            title_el = soup.select_one("h1")
        if title_el:
            # Get only direct text, not nested elements like set name links
            name_parts = []
            for child in title_el.children:
                if isinstance(child, str):
                    name_parts.append(child.strip())
                elif child.name == "a" and "/console/" not in child.get("href", ""):
                    name_parts.append(child.get_text(strip=True))
            result["name"] = " ".join(name_parts).strip() or title_el.get_text(strip=True)

        # --- Set name from breadcrumb or URL ---
        breadcrumb = soup.select_one("div#breadcrumbs a:nth-of-type(3), nav.breadcrumb a")
        if breadcrumb:
            result["set_name"] = breadcrumb.get_text(strip=True)
        elif "/game/" in url:
            parts = url.split("/game/")[1].split("/")
            if parts:
                result["set_name"] = parts[0].replace("-", " ").title()

        # --- Current grade prices from the price table ---
        result["grades"] = self._parse_grade_prices(soup)

        # --- Extract VGPC.chart_data from JavaScript ---
        chart_data_raw = self._extract_js_var(html, "VGPC.chart_data")
        if chart_data_raw:
            result["chart_data"] = self._map_chart_data_to_grades(
                chart_data_raw, result["grades"]
            )

        # --- Extract VGPC.product ---
        product_data = self._extract_js_var(html, "VGPC.product")
        if product_data and isinstance(product_data, dict):
            result["product_id"] = product_data.get("id")

        return result

    def _parse_grade_prices(self, soup: BeautifulSoup) -> dict:
        """Parse the grade/price table from the card detail page."""
        grades = {}

        # Look for price comparison section
        price_section = soup.select_one("div#full-prices, div.full-prices, table#attribute")

        # Try to find grade rows - PriceCharting uses various structures
        # Look for dt/dd pairs or table rows with grade labels
        for dt in soup.select("dt"):
            label = dt.get_text(strip=True)
            dd = dt.find_next_sibling("dd")
            if dd:
                price_el = dd.select_one("span.js-price")
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    price_match = re.search(r"[\d,]+\.?\d*", price_text)
                    if price_match:
                        price = float(price_match.group().replace(",", ""))
                        grade_key = self._normalize_grade_label(label)
                        if grade_key:
                            grades[grade_key] = price

        # Fallback: look for the price box with labeled rows
        if not grades:
            for row in soup.select("tr"):
                cells = row.select("td")
                if len(cells) >= 2:
                    label = cells[0].get_text(strip=True)
                    price_el = cells[1].select_one("span.js-price")
                    if not price_el:
                        price_text = cells[1].get_text(strip=True)
                    else:
                        price_text = price_el.get_text(strip=True)
                    price_match = re.search(r"[\d,]+\.?\d*", price_text)
                    if price_match:
                        price = float(price_match.group().replace(",", ""))
                        grade_key = self._normalize_grade_label(label)
                        if grade_key:
                            grades[grade_key] = price

        return grades

    def _normalize_grade_label(self, label: str) -> str | None:
        """Convert grade label text to a normalized grade string."""
        label = label.strip().lower()
        if "ungraded" in label or label == "loose":
            return "Ungraded"
        if "psa 10" in label or "gem mint" in label:
            return "10"
        match = re.search(r"grade\s*(\d+\.?\d*)", label)
        if match:
            return match.group(1)
        # Check for just a number like "9.5" or "10"
        if re.match(r"^\d+\.?\d*$", label):
            return label
        return None

    def _extract_js_var(self, html: str, var_name: str):
        """Extract a JavaScript variable value from page HTML."""
        escaped_name = re.escape(var_name)

        # Try object/array pattern first: VAR = { ... }
        pattern = rf"{escaped_name}\s*=\s*(\{{.*?\}}|\[.*?\])\s*;?"
        match = re.search(pattern, html, re.DOTALL)

        if not match:
            # Try non-greedy match for objects that may contain nested structures
            pattern2 = rf"{escaped_name}\s*=\s*(\{{[^;]*\}})\s*;?"
            match = re.search(pattern2, html, re.DOTALL)

        if not match:
            return None

        json_str = match.group(1)
        # Remove trailing commas before } or ]
        json_str = re.sub(r",\s*([}\]])", r"\1", json_str)
        # Convert JS booleans to JSON
        json_str = json_str.replace(": true", ": true").replace(": false", ": false")
        # Handle unquoted keys: word: -> "word":
        json_str = re.sub(r'(?<=[{,])\s*(\w+)\s*:', r' "\1":', json_str)

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return None

    def _map_chart_data_to_grades(self, chart_data: dict,
                                   grade_prices: dict) -> dict:
        """
        Map chart_data keys to grade labels by matching latest values
        to current displayed prices. Falls back to default mapping.
        """
        mapped = {}

        # Build a lookup: latest chart value (in cents) -> chart key
        latest_values = {}
        for key, data_points in chart_data.items():
            if data_points and isinstance(data_points, list) and len(data_points) > 0:
                last_point = data_points[-1]
                if isinstance(last_point, list) and len(last_point) == 2:
                    latest_values[key] = last_point[1]  # price in cents

        # Try to match by comparing cents to displayed dollar prices
        matched_keys = set()
        matched_grades = set()

        for grade_label, dollar_price in grade_prices.items():
            cents_price = round(dollar_price * 100)
            best_key = None
            best_diff = float("inf")

            for key, chart_cents in latest_values.items():
                if key in matched_keys:
                    continue
                diff = abs(chart_cents - cents_price)
                # Allow 1% tolerance
                if diff < best_diff and diff < cents_price * 0.01 + 100:
                    best_diff = diff
                    best_key = key

            if best_key:
                matched_keys.add(best_key)
                matched_grades.add(grade_label)
                mapped[grade_label] = self._convert_chart_points(
                    chart_data[best_key]
                )

        # For any unmatched chart keys, use default mapping
        for key, data_points in chart_data.items():
            if key not in matched_keys and data_points:
                default_grade = CHART_KEY_TO_GRADE.get(key)
                if default_grade and default_grade not in mapped:
                    mapped[default_grade] = self._convert_chart_points(data_points)

        return mapped

    def _convert_chart_points(self, data_points: list) -> list[dict]:
        """Convert [timestamp_ms, price_cents] pairs to [{date, price}]."""
        converted = []
        for point in data_points:
            if not isinstance(point, list) or len(point) != 2:
                continue
            timestamp_ms, price_cents = point
            if price_cents == 0:
                continue  # Skip zero-price entries
            try:
                dt = datetime.fromtimestamp(timestamp_ms / 1000)
                converted.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "price": price_cents / 100.0,
                })
            except (ValueError, OSError):
                continue
        return converted

    def get_card_history(self, url: str, grading_company: str = "PSA",
                          grade: str = "10") -> list[dict]:
        """
        Convenience method: fetch a card and return its price history
        for a specific grade.

        Returns list of {date, price} dicts sorted by date.
        """
        details = self.get_card_details(url)
        if not details:
            return []

        chart = details.get("chart_data", {})
        # Try exact grade match first
        if grade in chart:
            return chart[grade]

        # Try 'Ungraded' if grade is 'Ungraded'
        if grade.lower() == "ungraded" and "Ungraded" in chart:
            return chart["Ungraded"]

        return []


# Module self-test
if __name__ == "__main__":
    client = PriceChartingClient()

    print("=== Searching PriceCharting for 'Charizard base set' ===")
    results = client.search_cards("Charizard base set")
    print(f"Found {len(results)} results")
    for r in results[:5]:
        print(f"  {r['name']} | {r['set_name']} | ${r['current_price']} | {r['url']}")

    if results:
        print(f"\n=== Fetching details for: {results[0]['name']} ===")
        details = client.get_card_details(results[0]["url"])
        if details:
            print(f"Name: {details['name']}")
            print(f"Set: {details['set_name']}")
            print(f"Grades: {list(details['grades'].keys())}")
            for grade, price in details["grades"].items():
                print(f"  {grade}: ${price:,.2f}")
            print(f"\nChart data grades: {list(details['chart_data'].keys())}")
            for grade, points in details["chart_data"].items():
                if points:
                    print(f"  {grade}: {len(points)} data points "
                          f"({points[0]['date']} to {points[-1]['date']})")
