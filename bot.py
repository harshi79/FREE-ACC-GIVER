"""
Fʀᴇᴇ Aᴄᴄ Gɪᴠᴇʀ ── ʙᴏᴛ ᴇɴᴛʀʏ ᴘᴏɪɴᴛ

Run:  python3 bot.py      (from this folder)
The codebase is split across:
    config.py                 all settings (env-overridable)
    bot.py                    wiring / entry point
    core/style.py                 glyph palette + small-caps font
    core/constants.py             callback codes + state tokens
    core/messaging.py             live-menu page engine + result-card memory
    core/views.py                 every screen (text + inline buttons)
    core/animation.py             boot / generation motion
    core/cache.py                 instant counters + pool snapshot + banned state
    core/net.py                   retry-hardened sends
    core/security.py              owner-only gates
    core/health.py                tiny HTTP /healthz server (Render ping)
    core/handlers_users.py        member flows
    core/handlers_owner.py        owner panel + vault manager (hidden from everyone else)
    core/handlers_text.py         text-mode state machine
    data/db.py                    connection pool + schema + vault 2.0 migration
    data/catalog.py               pool registry seeds, slugs, collision rules
    data/store.py                 every database operation (per-pool)

Secrets are NOT in this repo: the bot refuses to start until the
environment provides BOT_TOKEN and BOT_DATABASE_URL (set them in
Render → Environment, or export them locally).
"""
from __future__ import annotations

import asyncio
import logging
import sys

import config
from data import store
from data.db import db

logging.basicConfig(
    format="%(asctime)s · %(name)s · %(levelname)s · %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")

# ── Telegram wiring ────────────────────────────────────────────
from telegram import BotCommand, Update  # noqa: E402
from telegram.constants import ParseMode  # noqa: E402
from telegram.error import BadRequest  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest  # noqa: E402

from core import handlers_owner, handlers_text, handlers_users  # noqa: E402
from core.constants import CB  # noqa: E402
from core.health import start_health_server  # noqa: E402

VISIBLE_COMMANDS = [
    BotCommand("start", "Open the hub"),
    BotCommand("gen", "Pull an account or key"),
    BotCommand("plans", "Tiers & private slots"),
    BotCommand("profile", "Your profile card"),
    BotCommand("status", "Live pool status"),
    BotCommand("contact", "Contact the owner"),
    BotCommand("hits", "Send a hit report"),
    BotCommand("help", "Help & quick keys"),
    BotCommand("cancel", "Abort the current flow"),
]


# ── single callback router ─────────────────────────────────────
def _toast_for(data: str, owner: bool) -> str | None:
    if data.startswith(CB["FB_WORK"] + ":"):
        return "logged ✓"
    if data.startswith(CB["FB_DEAD"] + ":"):
        return "dead logged — owner notified"
    if data.startswith(CB["FB_SKIP"] + ":"):
        return "skipped" if owner else "−1 rep"
    return None


# per-chat lock: taps from ONE chat are processed strictly one at a
# time (no double-tap double-pulls, no interleaved edits on the live
# page), while different chats still run concurrently.
_CHAT_LOCKS: dict[int, asyncio.Lock] = {}


def _chat_lock(chat_id: int) -> asyncio.Lock:
    if len(_CHAT_LOCKS) > 4096:  # keep it bounded
        for key in [k for k, v in _CHAT_LOCKS.items() if not v.locked()]:
            _CHAT_LOCKS.pop(key, None)
    return _CHAT_LOCKS.setdefault(chat_id, asyncio.Lock())


async def route_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True when the tap was handled (selftest verifies coverage)."""
    query = update.callback_query
    if query is None:
        return False
    data = query.data or ""
    uid = update.effective_user.id if update.effective_user else 0
    chat_id = query.message.chat_id if query.message else uid
    owner = store.is_owner(uid)

    async with _chat_lock(chat_id):
        # owner codes answer themselves (dynamic toasts: errors included)
        if owner and handlers_owner.owner_codes(data):
            if await handlers_owner.owner_callback(update, context):
                return True
            # registered prefix but no branch matched — answer & swallow
            try:
                await query.answer()
            except BadRequest:
                pass
            return True

        # always answer once (stops the client spinner instantly)
        try:
            await query.answer(_toast_for(data, owner), show_alert=False)
        except BadRequest:
            pass

        # member space (also serves the owner's member pages)
        return await handlers_users.user_callback(update, context)


# ── error handling ─────────────────────────────────────────────
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Unhandled exception", exc_info=context.error)
    try:
        if update is not None and getattr(update, "effective_user", None):
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="[!] something slipped — the vault already knows. try again.",
                parse_mode=ParseMode.HTML,
            )
    except Exception:  # noqa: BLE001
        log.exception("Failed to report an error to the user")


# ── main ───────────────────────────────────────────────────────
async def main() -> None:
    # Secrets come from the environment (Render). Die with a clear
    # message instead of booting a half-configured bot.
    missing = config.missing_env()
    if missing:
        print("\n[FATAL] missing required environment variables:")
        for name in missing:
            print(f"  • {name}  —  {config.REQUIRED_LABELS.get(name, '')}")
        print("\nSet them in Render → Environment (or export them locally), then restart.\n")
        raise SystemExit(2)

    assert config.BOT_TOKEN is not None and config.DATABASE_URL is not None
    # Health endpoint: starts BEFORE the DB work, so Render sees the
    # service as "live" instantly and keeps pinging it warm.
    health = start_health_server()

    try:
        await db.connect()
    except Exception:
        if health is not None:
            health.shutdown()
        raise

    builder: ApplicationBuilder = Application.builder().token(config.BOT_TOKEN)
    builder.request(
        HTTPXRequest(
            connection_pool_size=32,
            read_timeout=config.REQUEST_READ_TIMEOUT,
            write_timeout=config.REQUEST_WRITE_TIMEOUT,
            connect_timeout=config.REQUEST_CONNECT_TIMEOUT,
            pool_timeout=10.0,
        )
    )
    builder.get_updates_request(
        HTTPXRequest(
            connection_pool_size=1,
            read_timeout=config.GET_UPDATES_READ_TIMEOUT,
            write_timeout=config.REQUEST_WRITE_TIMEOUT,
            connect_timeout=config.REQUEST_CONNECT_TIMEOUT,
            pool_timeout=10.0,
        )
    )
    builder.concurrent_updates(True)
    app: Application = builder.build()

    # ── member commands ────────────────────────────────────────
    app.add_handler(CommandHandler("start", handlers_users.cmd_start))
    app.add_handler(CommandHandler(["gen", "vault"], handlers_users.cmd_gen))
    app.add_handler(CommandHandler(["profile", "me"], handlers_users.cmd_profile))
    app.add_handler(CommandHandler(["status", "stock"], handlers_users.cmd_status))
    app.add_handler(CommandHandler(["plans", "plan"], handlers_users.cmd_plans))
    app.add_handler(CommandHandler("contact", handlers_users.cmd_contact))
    app.add_handler(CommandHandler("hits", handlers_users.cmd_hits))
    app.add_handler(CommandHandler(["help", "menu"], handlers_users.cmd_help))
    app.add_handler(CommandHandler("cancel", handlers_users.cmd_cancel))

    # ── silent owner hotkeys (never advertised, gated inside) ──
    app.add_handler(CommandHandler("panel", handlers_owner.cmd_panel))
    app.add_handler(CommandHandler("users", handlers_owner.cmd_users))
    app.add_handler(CommandHandler("manage", handlers_owner.cmd_manage))
    app.add_handler(CommandHandler("export", handlers_owner.cmd_export))
    app.add_handler(CommandHandler("admin", handlers_owner.cmd_admin))

    # ── text-mode state machine ────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers_text.process_text))

    # ── one callback router for everything (fast, ordered) ─────
    app.add_handler(CallbackQueryHandler(route_callback))

    app.add_error_handler(on_error)

    await app.initialize()
    await app.bot.set_my_commands(VISIBLE_COMMANDS)
    await app.updater.start_polling(drop_pending_updates=True, timeout=config.POLL_TIMEOUT)
    await app.start()

    log.info("bot is live · owner %s · @%s", config.OWNER_ID, config.OWNER_USERNAME)
    try:
        await asyncio.Event().wait()
    finally:
        log.info("shutting down…")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped.")
    except RuntimeError as exc:
        print(f"\n[FATAL] {exc}\n")
        sys.exit(1)
