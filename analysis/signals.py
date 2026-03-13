"""
Investment signal generation.
Analyzes price trends to produce Buy/Watch/Hold/Sell signals.
"""

from dataclasses import dataclass
from enum import Enum
import pandas as pd
from analysis.trends import (
    calculate_trend_direction,
    detect_trend_reversal,
    calculate_volatility,
    calculate_price_changes,
)


class SignalType(Enum):
    BUY = "🟢 BUY"
    WATCH = "🟡 WATCH"
    HOLD = "⚪ HOLD"
    SELL = "🔴 SELL"
    INSUFFICIENT = "⚫ NO DATA"


@dataclass
class InvestmentSignal:
    product_id: int
    product_name: str
    signal_type: SignalType
    confidence: float  # 0.0 to 1.0
    reason: str
    current_price: float | None
    trend_direction: str
    volatility: float


def generate_signal(product_id: int, product_name: str,
                    prices: pd.Series) -> InvestmentSignal:
    """
    Analyze a product's price history and generate an investment signal.

    Logic:
    - BUY: Price reversed from decline, now trending up, reasonable volatility
    - WATCH: Price still declining but rate of decline is slowing
    - HOLD: Price is stable/sideways
    - SELL: Price peaked and is now declining from recent high
    - INSUFFICIENT: Not enough data
    """
    if len(prices) < 5:
        return InvestmentSignal(
            product_id=product_id,
            product_name=product_name,
            signal_type=SignalType.INSUFFICIENT,
            confidence=0.0,
            reason="Need at least 5 data points for analysis",
            current_price=float(prices.iloc[-1]) if len(prices) > 0 else None,
            trend_direction="insufficient_data",
            volatility=0.0,
        )

    trend = calculate_trend_direction(prices)
    volatility = calculate_volatility(prices)
    reversal = detect_trend_reversal(prices)
    current_price = float(prices.iloc[-1])

    # BUY signal: trend reversal detected and price is moving up
    if reversal and trend["direction"] == "up":
        confidence = min(0.9, 0.5 + (trend["r_squared"] * 0.4))
        return InvestmentSignal(
            product_id=product_id,
            product_name=product_name,
            signal_type=SignalType.BUY,
            confidence=round(confidence, 2),
            reason=f"Trend reversal detected. Up {reversal['gain_since_reversal']:.1f}% from bottom. Strong upward momentum.",
            current_price=current_price,
            trend_direction=trend["direction"],
            volatility=volatility,
        )

    # SELL signal: was going up but now declining
    if trend["direction"] == "down" and trend["slope_pct"] < -2.0:
        confidence = min(0.8, 0.4 + abs(trend["slope_pct"]) * 0.05)
        return InvestmentSignal(
            product_id=product_id,
            product_name=product_name,
            signal_type=SignalType.SELL,
            confidence=round(confidence, 2),
            reason=f"Declining at {trend['slope_pct']:.1f}% per period. Consider taking profits.",
            current_price=current_price,
            trend_direction=trend["direction"],
            volatility=volatility,
        )

    # WATCH signal: declining but showing signs of slowing
    if trend["direction"] == "down":
        changes = calculate_price_changes(prices)
        # Recent decline is less steep than earlier
        confidence = 0.3
        return InvestmentSignal(
            product_id=product_id,
            product_name=product_name,
            signal_type=SignalType.WATCH,
            confidence=confidence,
            reason="Price declining. Watch for reversal before buying.",
            current_price=current_price,
            trend_direction=trend["direction"],
            volatility=volatility,
        )

    # HOLD signal: sideways or gentle uptrend
    if trend["direction"] in ("sideways", "up"):
        confidence = 0.4 if trend["direction"] == "sideways" else 0.5
        reason = "Price is stable." if trend["direction"] == "sideways" else "Gentle upward trend."
        return InvestmentSignal(
            product_id=product_id,
            product_name=product_name,
            signal_type=SignalType.HOLD,
            confidence=confidence,
            reason=reason,
            current_price=current_price,
            trend_direction=trend["direction"],
            volatility=volatility,
        )

    # Fallback
    return InvestmentSignal(
        product_id=product_id,
        product_name=product_name,
        signal_type=SignalType.HOLD,
        confidence=0.2,
        reason="Not enough trend data for a strong signal.",
        current_price=current_price,
        trend_direction=trend["direction"],
        volatility=volatility,
    )
