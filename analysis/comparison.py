"""
Multi-product comparison utilities.
Normalize prices for comparing products at different price points.
"""

import pandas as pd


def normalize_prices(prices_dict: dict[str, pd.Series]) -> dict[str, pd.Series]:
    """
    Normalize all price series to start at 100 (index style).
    This allows comparing products at different price points.

    Args:
        prices_dict: {product_name: pd.Series of prices}

    Returns:
        {product_name: pd.Series of normalized prices starting at 100}
    """
    normalized = {}
    for name, prices in prices_dict.items():
        if len(prices) > 0:
            base = prices.iloc[0]
            if base > 0:
                normalized[name] = (prices / base) * 100
            else:
                normalized[name] = prices
    return normalized


def calculate_comparison_stats(prices_dict: dict[str, pd.Series]) -> list[dict]:
    """
    Calculate comparison statistics for multiple products.

    Returns list of dicts with: name, current_price, total_return_pct,
    volatility, highest, lowest
    """
    from analysis.trends import calculate_volatility

    stats = []
    for name, prices in prices_dict.items():
        if len(prices) < 2:
            continue

        current = float(prices.iloc[-1])
        first = float(prices.iloc[0])
        total_return = ((current - first) / first) * 100 if first > 0 else 0

        stats.append({
            "Name": name,
            "Current Price": current,
            "Start Price": first,
            "Total Return %": round(total_return, 1),
            "Volatility %": calculate_volatility(prices),
            "Highest": float(prices.max()),
            "Lowest": float(prices.min()),
        })

    # Sort by total return descending
    stats.sort(key=lambda x: x["Total Return %"], reverse=True)
    return stats
