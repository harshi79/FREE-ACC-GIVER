"""
Cᴇɴᴛʀᴀʟ ᴄᴏɴꜰɪɢᴜʀᴀᴛɪᴏɴ ────────────────

Everything the bot needs to run is read from environment variables —
that is how Render (and every other host) injects secrets. Nothing
secret is hardcoded in the repo:

    BOT_TOKEN=... BOT_DATABASE_URL=... python3 bot.py

Required secrets  (set in Render → Environment or a real .env):
    BOT_TOKEN          Telegram bot token from @BotFather
    BOT_DATABASE_URL   PostgreSQL connection string

Optional overrides (safe defaults below, not secret):
    BOT_OWNER_ID / BOT_OWNER_USERNAME / BOT_NAME / BOT_PAGE_SIZE
    BOT_AUTO_REMOVE_DEAD (default "0" — dead reports NEVER auto-delete a
    stock row; the owner reviews it in Vault manager instead) ...
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


def _str(name: str, default: str | None) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


# ── Secrets (REQUIRED from the environment) ────────────────────
BOT_TOKEN: str | None = _str("BOT_TOKEN", None)
DATABASE_URL: str | None = _str("BOT_DATABASE_URL", None)

REQUIRED_ENV = ("BOT_TOKEN", "BOT_DATABASE_URL")
REQUIRED_LABELS = {
    "BOT_TOKEN": "Telegram bot token (create one with @BotFather)",
    "BOT_DATABASE_URL": "PostgreSQL connection string",
}


def missing_env() -> list[str]:
    """Names of required env vars that are not set (for a clear error)."""
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


# ── Identity (safe, non-secret defaults) ────────────────────────
# The ONLY account that can see / use owner tools. No admins, no roles.
OWNER_ID: int = _int("BOT_OWNER_ID", 7728424218)

# Owner username shown for premium / private / business DMs.
OWNER_USERNAME: str = os.environ.get("BOT_OWNER_USERNAME", "WhoEvenYori")

# Public bot display name (rendered as small caps everywhere).
BOT_NAME: str = os.environ.get("BOT_NAME", "Free Acc Giver")

BOT_TAGLINE: str = os.environ.get("BOT_TAGLINE", "Fast · Smooth · Premium")

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

# ── Dead feedback policy ──────────────────────────────────────────
# OFF (default): a [✗] Dead mark NEVER deletes the stock row. The item
# stays in its pool, the owner gets the ping and decides. Set
# BOT_AUTO_REMOVE_DEAD=1 to let dead reports auto-pull the slot.
AUTO_REMOVE_DEAD: bool = os.environ.get("BOT_AUTO_REMOVE_DEAD", "0").strip().lower() in ("1", "true", "yes", "on")

# ── Vault pools ───────────────────────────────────────────────────
# Hard cap for pool slug length (callback payloads stay tiny).
POOL_SLUG_MAX: int = _int("BOT_POOL_SLUG_MAX", 24)
