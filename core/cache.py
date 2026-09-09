"""
Cᴀᴄʜᴇ ────────
Tiny in-memory counters with a short TTL so every menu that shows a
stock / user / pool number renders without a database hit. When the
bot itself changes stock it invalidates the pool snapshot inline, so
numbers on buttons stay honest between refreshes.

Vault 2.0 snapshot = registry (pools, order, labels) + live per-pool
counts + totals, refreshed in ONE pair of fast queries and shared by
home chips, the vault grid, stock pages and the owner's Vault manager.
Adding a new pool (or stock) simply invalidates it — everything else
is instant.
"""
from __future__ import annotations

import logging
import time

import config
from data import store
from data.catalog import Pool

log = logging.getLogger("cache")

_USERS: tuple[int, float] | None = None

# snapshot: (pools, counts, totals, refreshed-at)
_POOLS: list[Pool] = []
_POOLS_AT: float = 0.0
_COUNTS: dict[str, int] = {}
_TOTALS: dict[str, int] = {"ep": 0, "key": 0}
_POOLS_LOADED: bool = False


async def snapshot(force: bool = False) -> None:
    """Refresh pools + counts (registry rarely changes; counts with TTL)."""
    global _POOLS, _POOLS_AT, _COUNTS, _TOTALS, _POOLS_LOADED
    now = time.monotonic()
    if _POOLS_LOADED and not force and _POOLS_AT > now:
        return
    pools, counts = await _load()
    _POOLS, _COUNTS = pools, counts
    _TOTALS = {
        "ep": sum(n for slug, n in counts.items() if slug in {p.category for p in pools if p.kind == "ep"}),
        "key": sum(n for slug, n in counts.items() if slug in {p.category for p in pools if p.kind == "key"}),
    }
    _POOLS_AT = now + config.STOCK_CACHE_TTL
    _POOLS_LOADED = True


async def _load() -> tuple[list[Pool], dict[str, int]]:
    rows = await store.vault_categories()
    pools = [Pool(r["category"], r["label"], r["kind"], int(r["pos"])) for r in rows]
    counts: dict[str, int] = {}
    for r in await store.pool_counts():
        counts[r["category"]] = int(r["n"])
    return pools, counts


async def pools(force: bool = False) -> list[Pool]:
    await snapshot(force=force)
    return list(_POOLS)


def pools_sync() -> list[Pool]:
    """Last-known registry without IO (safe before the first snapshot)."""
    return list(_POOLS)


def get_pool(category: str) -> Pool | None:
    for p in _POOLS:
        if p.category == category:
            return p
    return None


async def pool_counts(force: bool = False) -> dict[str, int]:
    await snapshot(force=force)
    return dict(_COUNTS)


async def count(category: str) -> int:
    await snapshot()
    return _COUNTS.get(category, 0)


async def stock() -> dict[str, int]:
    """Instant totals per kind (memory first, short TTL, DB behind it)."""
    await snapshot()
    return dict(_TOTALS)


async def users() -> int:
    """Total users, cached a little longer (rarely changes)."""
    global _USERS
    now = time.monotonic()
    if _USERS is not None and _USERS[1] > now:
        return _USERS[0]
    n = await store.user_count()
    _USERS = (n, now + config.USERS_CACHE_TTL)
    return n


def pools_invalidate() -> None:
    """Registry or per-pool stock changed — re-pull the snapshot next render."""
    global _POOLS_AT, _POOLS_LOADED
    _POOLS_AT = 0.0
    _POOLS_LOADED = False


def stock_invalidate() -> None:
    """Drop every cached number (stock snapshot + user counter)."""
    pools_invalidate()
    users_invalidate()


def users_invalidate() -> None:
    global _USERS
    _USERS = None


# ── hottest pools (home chips): biggest live counts first ───────
def hottest(limit: int = 4) -> list[tuple[Pool, int]]:
    ranked = sorted(_POOLS, key=lambda p: -_COUNTS.get(p.category, 0))
    out = [(p, _COUNTS.get(p.category, 0)) for p in ranked]
    live = [(p, n) for p, n in out if n > 0]
    return (live or out)[:limit]


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
