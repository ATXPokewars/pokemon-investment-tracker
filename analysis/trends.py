"""
Trend detection and analysis algorithms.
Identifies price direction, reversals, and momentum.
"""

import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import argrelextrema


def calculate_moving_average(prices: pd.Series, window: int = 7) -> pd.Series:
    """Simple moving average over a rolling window."""
    return prices.rolling(window=window, min_periods=1).mean()


def calculate_trend_direction(prices: pd.Series, window: int = 14) -> dict:
    """
    Determine if prices are trending up, down, or sideways.
    Uses linear regression over the last `window` data points.

    Returns dict with: direction ('up'/'down'/'sideways'/'insufficient_data'),
    slope_pct (normalized slope as %), r_squared (fit quality)
    """
    if len(prices) < 3:
        return {"direction": "insufficient_data", "slope_pct": 0, "r_squared": 0}

    recent = prices.tail(window).dropna()
    if len(recent) < 3:
        return {"direction": "insufficient_data", "slope_pct": 0, "r_squared": 0}

    x = np.arange(len(recent))
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, recent.values)

    # Normalize slope by mean price to get percentage change per data point
    mean_price = recent.mean()
    if mean_price == 0:
        return {"direction": "sideways", "slope_pct": 0, "r_squared": 0}

    pct_slope = (slope / mean_price) * 100

    if pct_slope > 1.0:
        direction = "up"
    elif pct_slope < -1.0:
        direction = "down"
    else:
        direction = "sideways"

    return {
        "direction": direction,
        "slope_pct": round(pct_slope, 2),
        "r_squared": round(r_value ** 2, 3),
    }


def detect_trend_reversal(prices: pd.Series) -> dict | None:
    """
    Detect when a declining product stops falling and starts rising.
    This is the key 'buy signal' for Pokemon investment.

    Returns dict with: reversal_date, price_at_reversal, current_price,
    gain_since_reversal, or None if no reversal detected.
    """
    if len(prices) < 10:
        return None

    # Smooth prices to reduce noise
    smoothed = calculate_moving_average(prices, window=5)
    values = smoothed.values

    # Find local minima
    local_mins = argrelextrema(values, np.less, order=3)[0]

    if len(local_mins) == 0:
        return None

    last_min_idx = local_mins[-1]

    # Check if prices have been rising since the last minimum
    post_min = prices.iloc[last_min_idx:]
    if len(post_min) >= 3:
        trend = calculate_trend_direction(post_min, window=len(post_min))
        if trend["direction"] == "up":
            reversal_price = float(prices.iloc[last_min_idx])
            current_price = float(prices.iloc[-1])
            gain = ((current_price - reversal_price) / reversal_price) * 100

            return {
                "reversal_date": prices.index[last_min_idx] if hasattr(prices.index, 'strftime') else str(last_min_idx),
                "price_at_reversal": reversal_price,
                "current_price": current_price,
                "gain_since_reversal": round(gain, 1),
            }

    return None


def calculate_volatility(prices: pd.Series) -> float:
    """Calculate price volatility as coefficient of variation (%)."""
    if len(prices) < 2:
        return 0.0
    mean = prices.mean()
    if mean == 0:
        return 0.0
    return round((prices.std() / mean) * 100, 1)


def calculate_price_changes(prices: pd.Series) -> dict:
    """Calculate various price change metrics."""
    result = {
        "change_7d": None,
        "change_30d": None,
        "change_pct_7d": None,
        "change_pct_30d": None,
    }

    if len(prices) < 2:
        return result

    current = float(prices.iloc[-1])

    if len(prices) >= 7:
        price_7d_ago = float(prices.iloc[-7])
        result["change_7d"] = round(current - price_7d_ago, 2)
        if price_7d_ago > 0:
            result["change_pct_7d"] = round(((current - price_7d_ago) / price_7d_ago) * 100, 1)

    if len(prices) >= 30:
        price_30d_ago = float(prices.iloc[-30])
        result["change_30d"] = round(current - price_30d_ago, 2)
        if price_30d_ago > 0:
            result["change_pct_30d"] = round(((current - price_30d_ago) / price_30d_ago) * 100, 1)

    return result
