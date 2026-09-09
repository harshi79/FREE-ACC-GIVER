"""
Nᴇᴛ ────────
Retry-hardened raw Telegram calls (owner notifications, broadcasts).
Every network hiccup retries with backoff so the bot feels alive even
when Telegram or the host network sneezes.
"""
from __future__ import annotations

import asyncio
import logging

import config
from telegram import InlineKeyboardMarkup
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.ext import ContextTypes

log = logging.getLogger("net")


async def _with_retries(coro_factory):
    attempt = 0
    while True:
        try:
            return await coro_factory()
        except RetryAfter as exc:
            attempt += 1
            if attempt > config.MAX_RETRIES:
                raise
            await asyncio.sleep(max(float(exc.retry_after), 0.5))
        except TimedOut:
            attempt += 1
            if attempt > config.MAX_RETRIES:
                raise
            await asyncio.sleep(config.RETRY_BASE_DELAY * (2 ** (attempt - 1)))
        except NetworkError as exc:
            if isinstance(exc, BadRequest):
                raise
            attempt += 1
            if attempt > config.MAX_RETRIES:
                raise
            await asyncio.sleep(config.RETRY_BASE_DELAY * (2 ** (attempt - 1)))
        except BadRequest:
            raise


async def notify(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> bool:
    """Fire-and-forget send with retries; never raises into handlers."""
    try:
        await _with_retries(
            lambda: context.bot.send_message(
                chat_id=chat_id, text=text, reply_markup=markup, parse_mode=parse_mode
            )
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("notify %s failed after retries: %s", chat_id, type(exc).__name__)
        return False
