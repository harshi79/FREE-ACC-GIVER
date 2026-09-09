"""
Cᴇɴᴛʀᴀʟ ᴄᴏɴꜰɪɢᴜʀᴀᴛɪᴏɴ ────────────────

Everything the bot needs to run lives here. Every value can be
overridden with an environment variable, so you can run:

    BOT_TOKEN=... BOT_OWNER_ID=... python3 bot.py

without touching this file. The defaults below keep it working
out-of-the-box (same token / owner / database as before).
"""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── Identity ────────────────────────────────────────────────────
BOT_TOKEN: str = os.environ.get(
    "BOT_TOKEN",
    "8819857671:AAFgoU1ij4m7h1MWI-9iMRVjrQja4H1vuQY",
)

# The ONLY account that can see / use owner tools. No admins, no roles.
OWNER_ID: int = _int("BOT_OWNER_ID", 7728424218)

# Owner username shown for premium / private / business DMs.
OWNER_USERNAME: str = os.environ.get("BOT_OWNER_USERNAME", "WhoEvenYori")

# Public bot display name (rendered as small caps everywhere).
BOT_NAME: str = os.environ.get("BOT_NAME", "Free Acc Giver")

BOT_TAGLINE: str = os.environ.get("BOT_TAGLINE", "Fast · Smooth · Premium")

# ── Database ────────────────────────────────────────────────────
DATABASE_URL: str = os.environ.get(
    "BOT_DATABASE_URL",
    "postgresql://neondb_owner:npg_vlXzsQ7n2VZg@ep-sweet-smoke-b3rtnp1f-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
)

# ── Plans / limits ──────────────────────────────────────────────
# name -> (daily limit | None = unlimited, cooldown minutes, features)
PLAN_LIMITS: dict[str, int | None] = {"free": 5, "pro": 20, "elite": 50, "unlimited": None}
PLAN_COOLDOWN_MINUTES: dict[str, int] = {"free": 5, "pro": 2, "elite": 0, "unlimited": 0}

# Public "premium tier" texts.
PLAN_ORDER: list[str] = ["free", "pro", "elite", "unlimited"]
PLAN_BADGE: dict[str, str] = {"free": "◈", "pro": "✦", "elite": "✧", "unlimited": "∞"}
PLAN_TITLE: dict[str, str] = {"free": "Free", "pro": "Pro", "elite": "Elite", "unlimited": "Unlimited"}
PLAN_TAG: dict[str, str] = {
    "free": "Starter access · everyday drops",
    "pro": "Priority pool · faster cooldown",
    "elite": "High volume · zero cooldown",
    "unlimited": "No limits · concierge line",
}

INITIAL_REPUTATION: int = _int("BOT_INITIAL_REP", 5)

# ── Pages ───────────────────────────────────────────────────────
USERS_PER_PAGE: int = _int("BOT_PAGE_SIZE", 10)

# ── Caching (keeps everything feeling instant) ──────────────────
STOCK_CACHE_TTL: float = _float("BOT_STOCK_CACHE_TTL", 4.0)
USERS_CACHE_TTL: float = _float("BOT_USERS_CACHE_TTL", 8.0)

# ── Animations ──────────────────────────────────────────────────
ANIM_STEP_SEC: float = _float("BOT_ANIM_STEP", 0.42)   # per boot/gen frame

# ── Network hardening ───────────────────────────────────────────
POLL_TIMEOUT: int = _int("BOT_POLL_TIMEOUT", 10)
REQUEST_READ_TIMEOUT: float = _float("BOT_READ_TIMEOUT", 25.0)
REQUEST_WRITE_TIMEOUT: float = _float("BOT_WRITE_TIMEOUT", 25.0)
REQUEST_CONNECT_TIMEOUT: float = _float("BOT_CONNECT_TIMEOUT", 8.0)
GET_UPDATES_READ_TIMEOUT: float = _float("BOT_GET_UPDATES_TIMEOUT", 30.0)
MAX_RETRIES: int = _int("BOT_MAX_RETRIES", 4)
RETRY_BASE_DELAY: float = _float("BOT_RETRY_DELAY", 0.4)
DB_CONNECT_MAX_ATTEMPTS: int = _int("BOT_DB_ATTEMPTS", 6)

# ── Stock counts shown on buttons (nice, not a leak) ─────────────
SHOW_STOCK_ON_BUTTONS: bool = os.environ.get("BOT_SHOW_STOCK", "1") not in ("0", "false", "False")
