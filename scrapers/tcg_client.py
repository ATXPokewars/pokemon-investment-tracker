"""
TCGPlayer pricing client using the free TCGCSV API.
No API key required. Data is updated ~every 24 hours by TCGCSV.

TCGCSV mirrors TCGPlayer's catalog and pricing for all categories.
Pokemon TCG is category 3.
"""

import requests
import time
from config.settings import TCGCSV_BASE_URL, POKEMON_CATEGORY_ID, REQUEST_DELAY


class TCGCSVClient:
    """Client for the TCGCSV API — free access to TCGPlayer catalog and pricing."""

    def __init__(self):
        self.base_url = TCGCSV_BASE_URL
        self.category_id = POKEMON_CATEGORY_ID
        self.session = requests.Session()
        # Cache sets in memory to avoid re-fetching
        self._sets_cache = None

    def get_all_sets(self) -> list[dict]:
        """
        Fetch all Pokemon TCG sets.
        Returns list of dicts with keys: groupId, name, abbreviation,
        isSupplemental, publishedOn, modifiedOn, categoryId
        """
        if self._sets_cache is not None:
            return self._sets_cache

        url = f"{self.base_url}/{self.category_id}/groups"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        self._sets_cache = data.get("results", [])
        return self._sets_cache

    def search_sets(self, query: str) -> list[dict]:
        """Search sets by name (case-insensitive partial match)."""
        all_sets = self.get_all_sets()
        query_lower = query.lower()
        return [s for s in all_sets if query_lower in s["name"].lower()]

    def get_products_in_set(self, group_id: int) -> list[dict]:
        """
        Fetch all products in a specific set.
        Returns list of dicts with keys: productId, name, cleanName,
        imageUrl, categoryId, groupId, url, extendedData, presaleInfo, etc.
        """
        url = f"{self.base_url}/{self.category_id}/{group_id}/products"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json().get("results", [])

    def get_prices_in_set(self, group_id: int) -> list[dict]:
        """
        Fetch current prices for all products in a set.
        Returns list of dicts with keys: productId, lowPrice, midPrice,
        highPrice, marketPrice, directLowPrice, subTypeName
        """
        url = f"{self.base_url}/{self.category_id}/{group_id}/prices"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json().get("results", [])

    def get_products_with_prices(self, group_id: int) -> list[dict]:
        """
        Fetch products and their prices for a set, merged together.
        Returns list of dicts combining product info and pricing.
        """
        products = self.get_products_in_set(group_id)
        time.sleep(0.5)  # Small delay between requests
        prices = self.get_prices_in_set(group_id)

        # Build a price lookup: productId -> list of price entries
        # (a product can have multiple price entries for different variants)
        price_lookup = {}
        for p in prices:
            pid = p["productId"]
            if pid not in price_lookup:
                price_lookup[pid] = []
            price_lookup[pid].append(p)

        # Merge product info with its pricing
        merged = []
        for product in products:
            pid = product["productId"]
            product_prices = price_lookup.get(pid, [])

            # Use the first price entry (usually "Normal" variant) as the primary
            primary_price = product_prices[0] if product_prices else {}

            merged.append({
                "productId": pid,
                "name": product.get("name", ""),
                "cleanName": product.get("cleanName", ""),
                "imageUrl": product.get("imageUrl", ""),
                "groupId": product.get("groupId"),
                "url": product.get("url", ""),
                "marketPrice": primary_price.get("marketPrice"),
                "lowPrice": primary_price.get("lowPrice"),
                "midPrice": primary_price.get("midPrice"),
                "highPrice": primary_price.get("highPrice"),
                "subTypeName": primary_price.get("subTypeName", "Normal"),
                "all_prices": product_prices,
                "extendedData": product.get("extendedData", []),
            })

        return merged

    def search_products_across_sets(self, query: str, max_sets: int = 10) -> list[dict]:
        """
        Search for products by name across multiple sets.
        First searches for matching sets, then searches product names within those sets.
        Also searches broadly if the query doesn't match a set name.

        This can be slow for broad queries since it checks multiple sets.
        """
        query_lower = query.lower()
        results = []
        searched_group_ids = set()

        # Strategy 1: Search sets whose name matches the query
        matching_sets = self.search_sets(query)
        for s in matching_sets[:3]:  # Limit to first 3 matching sets
            gid = s["groupId"]
            if gid in searched_group_ids:
                continue
            searched_group_ids.add(gid)
            try:
                products = self.get_products_with_prices(gid)
                for p in products:
                    p["set_name"] = s["name"]
                results.extend(products)
                time.sleep(REQUEST_DELAY / 3)  # Lighter delay for API
            except Exception:
                continue

        # Strategy 2: Search products by name in recent popular sets
        # (only if we don't have enough results yet)
        if len(results) < 10:
            all_sets = self.get_all_sets()
            # Sort by most recently published
            sorted_sets = sorted(
                all_sets,
                key=lambda s: s.get("publishedOn", ""),
                reverse=True,
            )
            for s in sorted_sets[:max_sets]:
                gid = s["groupId"]
                if gid in searched_group_ids:
                    continue
                searched_group_ids.add(gid)
                try:
                    products = self.get_products_with_prices(gid)
                    matching = [
                        p for p in products
                        if query_lower in p["name"].lower()
                    ]
                    for p in matching:
                        p["set_name"] = s["name"]
                    results.extend(matching)
                    time.sleep(REQUEST_DELAY / 3)
                except Exception:
                    continue

                if len(results) >= 50:
                    break

        return results


# Module self-test
if __name__ == "__main__":
    client = TCGCSVClient()

    print("=== Fetching all Pokemon TCG sets ===")
    sets = client.get_all_sets()
    print(f"Found {len(sets)} sets")
    print(f"First 5: {[s['name'] for s in sets[:5]]}")

    print("\n=== Fetching products + prices for first set ===")
    first_set = sets[0]
    print(f"Set: {first_set['name']} (groupId: {first_set['groupId']})")
    products = client.get_products_with_prices(first_set["groupId"])
    print(f"Found {len(products)} products")
    for p in products[:3]:
        print(f"  - {p['name']}: ${p['marketPrice']} (market), "
              f"${p['lowPrice']}-${p['highPrice']}")
