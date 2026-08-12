"""Persistence for the Insight Dashboard.

The core design rule: **we persist the spec, never the values.**

A stored tile says "conversion rate, Rome, line chart" — it does not store any numbers.
Every open re-executes the spec against the warehouse through the governance layer, which
means (a) tiles are always current without any cache to invalidate, and (b) a user whose
role or access changed sees their new entitlement immediately, so a saved dashboard can
never become a stale data leak.
"""

import json
import os
from typing import Dict, List, Optional

STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dashboards.json")


def _read_all() -> Dict[str, List[dict]]:
    if not os.path.exists(STORE_PATH):
        return {}
    try:
        with open(STORE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # A corrupt store should degrade to the role template, not crash the app.
        return {}


def _write_all(data: Dict[str, List[dict]]) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, STORE_PATH)


def load(user_key: str, template: List[str], default_market: str) -> List[dict]:
    """Return the user's saved tiles, or seed from the role template on first visit.

    The template seed is the cold-start answer: a new market manager gets a market
    dashboard out of the box rather than an empty page.
    """
    all_data = _read_all()
    if user_key in all_data:
        return all_data[user_key]

    # The first tile leads the dashboard at full width; the rest pair up two per row.
    tiles = [
        {
            "metric_id": m,
            "market": default_market,
            "source": "template",
            "size": "full" if i == 0 else "half",
        }
        for i, m in enumerate(template)
    ]
    save(user_key, tiles)
    return tiles


def save(user_key: str, tiles: List[dict]) -> None:
    all_data = _read_all()
    all_data[user_key] = tiles
    _write_all(all_data)


def has_tile(user_key: str, metric_id: str, market: str) -> bool:
    """Read-only check. Deliberately does not seed a template, unlike load()."""
    return any(
        t["metric_id"] == metric_id and t["market"] == market
        for t in _read_all().get(user_key, [])
    )


def add_tile(
    user_key: str, metric_id: str, market: str, source: str = "pinned", size: str = "half"
) -> bool:
    """Pin a metric. Returns False if that exact tile is already on the dashboard."""
    tiles = _read_all().get(user_key, [])
    if any(t["metric_id"] == metric_id and t["market"] == market for t in tiles):
        return False
    tiles.append({"metric_id": metric_id, "market": market, "source": source, "size": size})
    save(user_key, tiles)
    return True


def toggle_size(user_key: str, index: int) -> None:
    """Flip a tile between half width (paired) and full width (its own row)."""
    tiles = _read_all().get(user_key, [])
    if 0 <= index < len(tiles):
        tiles[index]["size"] = "full" if tiles[index].get("size", "half") == "half" else "half"
        save(user_key, tiles)


def remove_tile(user_key: str, index: int) -> None:
    tiles = _read_all().get(user_key, [])
    if 0 <= index < len(tiles):
        tiles.pop(index)
        save(user_key, tiles)


def move_tile(user_key: str, index: int, delta: int) -> None:
    tiles = _read_all().get(user_key, [])
    target = index + delta
    if 0 <= index < len(tiles) and 0 <= target < len(tiles):
        tiles[index], tiles[target] = tiles[target], tiles[index]
        save(user_key, tiles)


def reset(user_key: str) -> None:
    """Forget this user's layout so the role template seeds again on next load."""
    all_data = _read_all()
    all_data.pop(user_key, None)
    _write_all(all_data)
