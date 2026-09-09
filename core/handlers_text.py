"""
Hᴀɴᴅʟᴇʀꜱ · ᴛᴇxᴛ ᴍᴏᴅᴇꜱ ────────
Some flows need a typed reply (bulk-stock pastes, messages to the
owner, hit reports, search, broadcast). All of them park the chat in
a short-lived "mode"; the next plain text message is routed here,
executed, and the mode is cleared again.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
from core import cache, handlers_owner, messaging, net, views
from core.constants import MODE
from core.messaging import esc
from core.style import G
from data import store

log = logging.getLogger("text")


async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or not update.message.text:
        return
    mode = context.user_data.get("mode")
    if not mode:
        return

    uid = update.effective_user.id
    content = update.message.text.strip()
    chat_id = update.effective_chat.id

    # banned members may not complete flows
    if await cache.banned(uid):
        context.user_data.pop("mode", None)
        return

    # owner flows (stock, search, broadcast, reset)
    if store.is_owner(uid):
        if await handlers_owner.owner_text(update, context, mode):
            return
        # otherwise fall through to the shared flows below

    if mode == MODE["WRITE_MSG"]:
        context.user_data.pop("mode", None)
        row_id = await store.mailbox_add("contact", uid, content)
        await _notify_owner(context, update, "contact", row_id, content)
        text, kb = views.message_sent("contact")
        await _refresh_or_send(context, chat_id, text, kb)
        return

    if mode == MODE["HIT_REPORT"]:
        context.user_data.pop("mode", None)
        row_id = await store.mailbox_add("hit", uid, content)
        await _notify_owner(context, update, "hit", row_id, content)
        text, kb = views.message_sent("hit")
        await _refresh_or_send(context, chat_id, text, kb)
        return


async def _notify_owner(
    context: ContextTypes.DEFAULT_TYPE,
    update: Update,
    kind: str,
    row_id: int,
    content: str,
) -> None:
    try:
        u = update.effective_user
        label = "message" if kind == "contact" else "hit report"
        handle = f"@{u.username}" if u.username else str(u.id)
        body = (
            f"{G.MAIL if kind == 'contact' else G.CHAT} {label} #{row_id}\n"
            f"{G.LINE_S}\n"
            f"from {esc(handle)} · id {u.id}\n"
            f"link: t.me/{u.username}\n\n"
            f"{esc(content[:2000])}"
        )
        await net.notify(context, config.OWNER_ID, body, parse_mode=messaging.PARSE)
    except Exception:  # noqa: BLE001
        log.exception("owner notification failed")


async def _refresh_or_send(context, chat_id: int, text: str, kb) -> None:
    pg = messaging.current_page(context)
    if pg is not None:
        msg = await messaging.edit(context, pg[0], pg[1], text, kb)
        if msg is not None:
            return
    await messaging.send(context, chat_id, text, kb)
