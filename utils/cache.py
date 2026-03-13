"""Simple in-memory cache with time-to-live."""

from datetime import datetime, timedelta


class SimpleCache:
    """Time-based cache. Store in st.session_state to persist across Streamlit reruns."""

    def __init__(self, ttl_minutes: int = 60):
        self._cache = {}
        self.ttl = timedelta(minutes=ttl_minutes)

    def get(self, key: str):
        """Get a cached value, or None if expired/missing."""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if datetime.now() - timestamp < self.ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value):
        """Store a value in the cache."""
        self._cache[key] = (value, datetime.now())

    def clear(self):
        """Clear all cached values."""
        self._cache.clear()
