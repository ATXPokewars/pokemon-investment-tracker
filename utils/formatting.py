"""Formatting helpers for prices, dates, and display."""


def format_price(price: float | None) -> str:
    """Format a price as $X.XX or 'N/A' if None."""
    if price is None:
        return "N/A"
    return f"${price:,.2f}"


def format_change(change_pct: float | None) -> str:
    """Format a percentage change with + or - prefix."""
    if change_pct is None:
        return "N/A"
    sign = "+" if change_pct >= 0 else ""
    return f"{sign}{change_pct:.1f}%"
