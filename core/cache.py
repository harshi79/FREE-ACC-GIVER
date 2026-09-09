"""
Cᴀᴄʜᴇ ────────
Tiny in-memory counters with a short TTL so every menu that shows a
stock / user number renders without a database hit. When the bot
itself changes stock it updates the cache inline, so numbers on
buttons stay honest between refreshes.
"""
from __future__ import annotations

import logging
import time

import config
from data import store
from data.db import db

log = logging.getLogger("cache")

_EP: tuple[int, float] | None = None
_KEYS: tuple[int, float] | None = None
_USERS: tuple[int, float] | None = None


async def _live_stock() -> dict[str, int]:
    return await store.stock_counts()


async def stock() -> dict[str, int]:
    """Instant stock counts: memory first, short TTL, DB behind it."""
    global _EP, _KEYS
    now = time.monotonic()
    if _EP is not None and _EP[1] > now:
        ep = _EP[0]
    else:
        ep = await db.fetchval("SELECT COUNT(*) FROM stock_emailpass") or 0
        _EP = (ep, now + config.STOCK_CACHE_TTL)
    if _KEYS is not None and _KEYS[1] > now:
        keys = _KEYS[0]
    else:
        keys = await db.fetchval("SELECT COUNT(*) FROM stock_keys") or 0
        _KEYS = (keys, now + config.STOCK_CACHE_TTL)
    return {"ep": ep, "key": keys}


async def users() -> int:
    """Total users, cached a little longer (rarely changes)."""
    global _USERS
    now = time.monotonic()
    if _USERS is not None and _USERS[1] > now:
        return _USERS[0]
    n = await store.user_count()
    _USERS = (n, now + config.USERS_CACHE_TTL)
    return n


def stock_mutate(kind: str, delta: int) -> None:
    """Adjust the cached counter (called after bot-side adds/removes)."""
    global _EP, _KEYS
    now = time.monotonic()
    cache = _EP if kind == "ep" else _KEYS
    if cache is not None and cache[1] > now:
        val = max(0, cache[0] + delta)
        if kind == "ep":
            _EP = (val, cache[1])
        else:
            _KEYS = (val, cache[1])


def stock_invalidate() -> None:
    global _EP, _KEYS
    _EP = None
    _KEYS = None


def users_invalidate() -> None:
    global _USERS
    _USERS = None


# ── banned state (tiny memory cache; avoids a query on every tap) ──
_BANNED: dict[int, tuple[bool, float]] = {}
_BANNED_TTL = 30.0


async def banned(uid: int) -> bool:
    now = time.monotonic()
    hit = _BANNED.get(uid)
    if hit is not None and hit[1] > now:
        return hit[0]
    flag = await store.banned_flag(uid)
    _BANNED[uid] = (flag, now + _BANNED_TTL)
    return flag


def banned_mark(uid: int, value: bool) -> None:
    _BANNED[uid] = (value, time.monotonic() + _BANNED_TTL)
