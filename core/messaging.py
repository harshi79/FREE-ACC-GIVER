"""
Mᴇꜱꜱᴀɢɪɴɢ ──────
Menus never stack: navigation, prompts and the boot flow all RENDERS ON
THE SAME live menu message. A generated drop is the one exception — it
lands as its OWN new message (a "card") that navigation must never
overwrite, so earlier results stay on screen. Every later "Pull again"
sends another card instead of replacing the old one.

To make that possible we remember the id of the "live page" (menu)
message per chat (context.user_data["pg"]) so text-mode flows can update
it too, and keep a small card registry (user_data["cards"]) so feedback
can keep editing ITS card while menu navigation hands off. Fallback: if
a message is too old to edit, we quietly send a fresh one.
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


# ── result cards ─────────────────────────────────────────────────
# A generated drop is its OWN message that must never be overwritten by
# navigation or by a later pull. The live-MENU pointer ("pg") therefore
# only tracks menu pages; cards live in a small per-user registry so
# feedback taps can keep editing THEIR card (appending the verdict) and
# so menu navigation can recognise "this message is a card — hands off".
_CARDS_MAX = 8


def register_card(
    context: ContextTypes.DEFAULT_TYPE, message_id: int, meta: dict
) -> None:
    cards = context.user_data.setdefault("cards", {})
    cards[message_id] = meta
    while len(cards) > _CARDS_MAX:
        cards.pop(next(iter(cards)))


def card_meta(context: ContextTypes.DEFAULT_TYPE, message_id: int) -> dict | None:
    cards = context.user_data.get("cards") or {}
    return cards.get(message_id)


def is_card(context: ContextTypes.DEFAULT_TYPE, message_id: int) -> bool:
    cards = context.user_data.get("cards") or {}
    return message_id in cards


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


# ── vault-2.0 page rules ────────────────────────────────────────
# • successful pulls + error states  -> NEW messages (cards/notes)
# • plain menu navigation            -> edits the live MENU message only
# • feedback                          -> edits its own card (appends verdict)
async def send_raw(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Send a message WITHOUT touching the live-page memory (cards, notices)."""
    try:
        return await context.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=markup, parse_mode=PARSE
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("send_raw failed (%s); retrying without parse mode", type(exc).__name__)
        try:
            return await context.bot.send_message(
                chat_id=chat_id, text=text, reply_markup=markup
            )
        except Exception:  # noqa: BLE001
            log.exception("send_raw failed twice")
            return None


async def edit_raw(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Edit a specific message without updating the live-menu memory."""
    try:
        return await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode=PARSE,
        )
    except Exception as exc:  # noqa: BLE001
        if "not modified" in str(exc).lower():
            return None
        log.debug("edit_raw failed (%s)", type(exc).__name__)
        return None


async def show_nav(
    context: ContextTypes.DEFAULT_TYPE,
    query,
    text: str,
    markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """
    Render a MENU page. Navigation edits the live menu message — never a
    result card, so tapping "◂ Main" from a drop card leaves the card with
    its credentials untouched.
    """
    chat_id = query.message.chat_id
    target = None
    pg = current_page(context)
    if pg is not None and pg[0] == chat_id:
        target = pg[1]
    elif not is_card(context, query.message.message_id):
        target = query.message.message_id
    if target is None:  # only a card around — send a fresh menu message
        return await send(context, chat_id, text, markup)
    try:
        msg = await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=target,
            text=text,
            reply_markup=markup,
            parse_mode=PARSE,
        )
        remember_page(context, msg)
        return msg
    except Exception as exc:  # noqa: BLE001
        if "not modified" in str(exc).lower():
            return None
        log.debug("show_nav edit failed (%s) — sending fresh page", type(exc).__name__)
        return await send(context, chat_id, text, markup)
