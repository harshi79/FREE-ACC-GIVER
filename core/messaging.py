"""
Mᴇꜱꜱᴀɢɪɴɢ ──────
The bot never stacks messages. Every page RENDERS ON THE SAME MESSAGE:
buttons edit it in place, animations edit it in place, and when a
flow finishes it edits the last page back to the new state.

To make that possible we remember the id of the "live page" message
per chat (context.user_data["pg"]) so text-mode flows can update it
too. Fallback: if a message is too old to edit, we quietly send a
fresh one.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core import style

log = logging.getLogger("chat")

PARSE = ParseMode.HTML


def page_header(title: str) -> str:
    """Small-caps header with a random shimmer, so pages feel alive."""
    s = style.spark()
    return f"{s} {style.sc(title)} {s}"


def footer() -> str:
    return (
        f"\n{style.LINE_S}\n"
        f"{style.G.BOLT} {style.sc('Fast · Smooth · Premium')} · "
        f"{style.G.DIAM} {style.sc('drop vault')}"
    )


def esc(text: object) -> str:
    """Escape user-provided strings for HTML parse mode."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def remember_page(context: ContextTypes.DEFAULT_TYPE, message: Message | None) -> None:
    if message is not None:
        context.user_data["pg"] = {"chat": message.chat_id, "msg": message.message_id}


def current_page(context: ContextTypes.DEFAULT_TYPE) -> tuple[int, int] | None:
    pg = context.user_data.get("pg")
    if pg and isinstance(pg, dict) and "chat" in pg and "msg" in pg:
        return pg["chat"], pg["msg"]
    return None


async def send(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Send a NEW page message and remember it as the live page."""
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=markup, parse_mode=PARSE
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send failed (%s); retrying without parse mode", type(exc).__name__)
        try:
            msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        except Exception:  # noqa: BLE001
            log.exception("send failed twice")
            return None
    remember_page(context, msg)
    return msg


async def edit(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Edit a page message in place. Falls back to a fresh send when needed."""
    try:
        msg = await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode=PARSE,
        )
        remember_page(context, msg)
        return msg
    except Exception as exc:  # noqa: BLE001
        msg_text = str(exc)
        if "not modified" in msg_text.lower():
            return None
        log.debug("edit failed (%s) — falling back to a fresh page", type(exc).__name__)
        return await send(context, chat_id, text, markup)


async def show(
    context: ContextTypes.DEFAULT_TYPE,
    query_or_chat,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """
    Route a page through the CURRENT live message whenever possible,
    otherwise send a fresh one. `query_or_chat` is a CallbackQuery or
    a chat id (for command replies).
    """
    chat_id: int
    if isinstance(query_or_chat, int):
        chat_id = query_or_chat
        pg = current_page(context)
        if pg is not None and pg[0] == chat_id:
            msg = await edit(context, pg[0], pg[1], text, markup)
            if msg is not None:
                return msg
        return await send(context, chat_id, text, markup)

    # CallbackQuery path: edit its message (our live page).
    query = query_or_chat
    chat_id = query.message.chat_id
    try:
        msg = await query.edit_message_text(
            text=text, reply_markup=markup, parse_mode=PARSE
        )
        remember_page(context, msg)
        return msg
    except Exception as exc:  # noqa: BLE001
        if "not modified" in str(exc).lower():
            return None
        log.debug("callback edit failed (%s) — sending fresh page", type(exc).__name__)
        return await send(context, chat_id, text, markup)
