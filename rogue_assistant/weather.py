"""Weather context — fetches current conditions from wttr.in to enrich the system prompt."""

from __future__ import annotations

import requests


def fetch_weather_context(location: str) -> str | None:
    """Return a one-line weather string for the given location, or None on failure."""
    if not location:
        return None
    try:
        resp = requests.get(
            f"https://wttr.in/{requests.utils.quote(location)}",
            params={"format": "3"},
            timeout=5,
            headers={"User-Agent": "curl/7.0"},
        )
        if resp.ok:
            return resp.content.decode("utf-8").strip()
    except Exception:
        pass
    return None
