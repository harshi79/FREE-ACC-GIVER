"""
Cᴀᴛᴀʟᴏɢ ────────
The vault is split into POOLS — one per brand / service — and pools are
NEVER mixed: a pull is scoped to exactly one category, adds land in the
chosen category, export / reset / remove are per category too.

Two kinds exist:

    ep   e-mail:pass accounts   -> physical table stock_emailpass
    key  serial / PC keys      -> physical table stock_keys

`vault_categories(category, label, kind, pos)` is the registry: it is
seeded on startup with the pools below and grows at runtime (the owner
adds new pools from inside the bot — no code change needed).

Legacy stock from old builds is imported by the startup migration:
old email:pass rows -> category "vpn", old keys -> category "pc".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import config

# ── physical layout ──────────────────────────────────────────────
TABLE_OF_KIND = {"ep": "stock_emailpass", "key": "stock_keys"}
HISTORY_OF_KIND = {"ep": "user_history_email", "key": "user_history_key"}

# legacy default pools — pre-vault rows fall into these on migration
LEGACY_CATEGORY = {"ep": "vpn", "key": "pc"}

KIND_LABEL = {"ep": "Accounts · email:pass", "key": "Keys · serial / PC"}
KIND_SHORT = {"ep": "Accounts", "key": "Keys"}


@dataclass(frozen=True)
class Pool:
    category: str
    label: str
    kind: str
    pos: int


# ── seed pools (one pool per line, all user-visible) ─────────────
SEED_POOLS: list[Pool] = [
    # Accounts (email:pass)
    Pool("vpn", "VPN Accounts", "ep", 0),
    Pool("expressvpn", "ExpressVPN", "ep", 1),
    Pool("nordvpn", "NordVPN", "ep", 2),
    Pool("surfshark", "Surfshark", "ep", 3),
    Pool("windscribe", "Windscribe", "ep", 4),
    Pool("streaming", "Streaming", "ep", 5),
    Pool("netflix", "Netflix", "ep", 6),
    Pool("spotify", "Spotify", "ep", 7),
    Pool("ai", "AI Accounts", "ep", 8),
    Pool("chatgpt", "ChatGPT", "ep", 9),
    Pool("claude", "Claude", "ep", 10),
    Pool("midjourney", "Midjourney", "ep", 11),
    Pool("characterai", "Character.ai", "ep", 12),
    # Keys
    Pool("pc", "PC & Software Keys", "key", 0),
    Pool("vpnkeys", "VPN & Service Keys", "key", 1),
    Pool("gamekeys", "Game Keys", "key", 2),
    Pool("steam", "Steam", "key", 3),
    Pool("office", "Windows/Office", "key", 4),
    Pool("antivirus", "Antivirus", "key", 5),
]

_KIND_ORDER = ("ep", "key")


def ordered_seed() -> list[Pool]:
    """Seed pools grouped by kind (accounts first), each in pos order."""
    return sorted(SEED_POOLS, key=lambda p: (_KIND_ORDER.index(p.kind), p.pos))


def seed_sql() -> list[tuple[str, str, str, int]]:
    """Registry rows for the startup seed (INSERT .. ON CONFLICT DO NOTHING)."""
    return [(p.category, p.label, p.kind, p.pos) for p in ordered_seed()]


# ── slugs ────────────────────────────────────────────────────────
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Slugify a pool name: letters/digits only, lowercase, capped."""
    slug = _NON_SLUG.sub("", (name or "").strip().lower())
    return slug[: config.POOL_SLUG_MAX]


def free_slug(base: str, taken: set[str]) -> tuple[str, bool]:
    """
    Make `base` unique against `taken` (collision handling).
    Returns (slug, modified). Empty base -> ("", False) — caller errors out.
    """
    if not base:
        return "", False
    if base not in taken:
        return base, False
    for n in range(2, 100):
        cand = f"{base}{n}"[: config.POOL_SLUG_MAX]
        if cand not in taken:
            return cand, True
    return "", False


def label_key(label: str) -> str:
    """Normalised label for duplicate-name detection."""
    return _NON_SLUG.sub("", (label or "").strip().lower())


# ── display helpers ──────────────────────────────────────────────
def clip(text: str, n: int = 26) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def pool_row_label(pool: Pool, count: int | None = None) -> str:
    """Button label for a pool, e.g. 'Netflix [12]'."""
    base = clip(pool.label, 22)
    return f"{base} [{count}]" if count is not None else base
