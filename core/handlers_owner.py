"""
Hᴀɴᴅʟᴇʀꜱ · ᴏᴡɴᴇʀ ────────
The entire privileged surface, reachable ONLY by the owner id. Every
route is a button inside the hidden Owner Core panel; the text
commands below are silent hotkeys that never appear in any help or
menu (and do nothing for anyone else).
"""
from __future__ import annotations

import asyncio
import io
import logging

from telegram import InlineKeyboardButton as IB
from telegram import InlineKeyboardMarkup as IM
from telegram import Update
from telegram.ext import ContextTypes

import config
from core import cache, messaging, views
from core.constants import CB, EP, KEY, MODE
from core.messaging import esc, footer, page_header
from core.style import G
from data import store

log = logging.getLogger("owner")

# owner-only callback prefixes — never answered by the user router
_OWNER_PREFIXES = tuple(
    {
        CB["OWN_PANEL"],
        CB["OWN_USERS"],
        CB["OWN_USER_PAGE"],
        CB["OWN_MANAGE"],
        CB["OWN_SEARCH"],
        CB["OWN_PLAN"],
        CB["OWN_REP"],
        CB["OWN_BAN"],
        CB["OWN_ADD_EP"],
        CB["OWN_ADD_KEY"],
        CB["OWN_RESET"],
        CB["OWN_RESET_NO"],
        CB["OWN_EXPORT"],
        CB["OWN_STATS"],
        CB["OWN_BROADCAST"],
        CB["OWN_INBOX"],
        CB["OWN_INBOX_READ"],
        CB["OWN_INBOX_READALL"],
        CB["OWN_INBOX_DEL"],
        CB["OWN_LOGS"],
        CB["OWN_BANNED"],
    }
)


def owner_codes(data: str) -> bool:
    return data.startswith(_OWNER_PREFIXES)


def _simple(title: str, lines: list[str], kb) -> tuple[str, IM]:
    return "\n".join([page_header(title), G.LINE, *lines]) + footer(), IM(kb)


# ────────────────────────────────────────────────────────────────
#  PANEL
# ────────────────────────────────────────────────────────────────
async def _show_panel(context, query=None, chat_id: int | None = None) -> None:
    text, kb = await views.owner_panel()
    if query is not None:
        await messaging.show(context, query, text, kb)
    elif chat_id is not None:
        await messaging.send(context, chat_id, text, kb)


async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not store.is_owner(update.effective_user.id):
        return
    await _show_panel(context, chat_id=update.effective_chat.id)


# ────────────────────────────────────────────────────────────────
#  USERS (list / search / manage)
# ────────────────────────────────────────────────────────────────
async def _users_page(context, query, page: int) -> None:
    text, kb = await views.owner_users(page)
    await messaging.show(context, query, text, kb)


async def _manage(context, query, uid: int) -> None:
    text, kb = await views.owner_manage(uid)
    await messaging.show(context, query, text, kb)


def _not_found(what: str) -> tuple[str, IM]:
    return _simple(
        "Not found",
        [
            f"{G.NO} nothing matches: {esc(what)}",
            f"{G.ARR} try the numeric user id or @username.",
        ],
        [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
    )


async def _resolve_target(raw: str) -> int | None:
    """Accepts a numeric id or @username; returns user id or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():
        return int(raw)
    user = await store.get_user_by_username(raw.lstrip("@"))
    return user["user_id"] if user else None


# ────────────────────────────────────────────────────────────────
#  owner callback router — returns True when it consumed the data
# ────────────────────────────────────────────────────────────────
async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not store.is_owner(update.effective_user.id):
        return False  # a non-owner walked into an owner code; user router guards it
    query = update.callback_query
    data = query.data or ""

    # panel -------------------------------------------------------
    if data == CB["OWN_PANEL"] or data == CB["OWN_STATS"]:
        await _show_panel(context, query)
        return True

    # users -------------------------------------------------------
    if data.startswith(CB["OWN_USER_PAGE"]):
        page = _as_int(data[len(CB["OWN_USER_PAGE"]):], 1)
        await _users_page(context, query, page)
        return True

    if data.startswith(CB["OWN_MANAGE"]):
        uid = _as_int(data[len(CB["OWN_MANAGE"]):], None)
        if uid is None:
            await _users_page(context, query, 1)
        else:
            await _manage(context, query, uid)
        return True

    if data == CB["OWN_BANNED"]:
        text, kb = await views.owner_banned()
        await messaging.show(context, query, text, kb)
        return True

    if data == CB["OWN_SEARCH"]:
        context.user_data["mode"] = MODE["SEARCH_USER"]
        text, kb = views.text_mode_prompt(MODE["SEARCH_USER"])
        await messaging.show(context, query, text, kb)
        return True

    # manage: plan / rep / ban --------------------------------------
    if data.startswith(CB["OWN_PLAN"]):
        rest = data[len(CB["OWN_PLAN"]):]
        uid_raw, _, plan = rest.partition(":")
        uid = _as_int(uid_raw, None)
        if uid is not None and plan in config.PLAN_ORDER:
            await store.set_plan(uid, plan)
        await _manage(context, query, uid or 0)
        return True

    if data.startswith(CB["OWN_REP"]):
        rest = data[len(CB["OWN_REP"]):]
        uid_raw, _, delta_raw = rest.partition(":")
        uid = _as_int(uid_raw, None)
        delta = _as_int(delta_raw, 0)
        if uid is not None:
            await store.add_rep(uid, delta)
        await _manage(context, query, uid or 0)
        return True

    if data.startswith(CB["OWN_BAN"]):
        rest = data[len(CB["OWN_BAN"]):]
        uid_raw, _, flag_raw = rest.partition(":")
        uid = _as_int(uid_raw, None)
        flag = flag_raw == "1"
        if uid is not None and not store.is_owner(uid):  # owner can never be locked
            if flag:
                await store.ban(uid, "Locked by owner")
            else:
                await store.unban(uid)
            cache.banned_mark(uid, flag)
        await _manage(context, query, uid or 0)
        return True

    # add stock ----------------------------------------------------
    if data == CB["OWN_ADD_EP"] or data == CB["OWN_ADD_KEY"]:
        mode = MODE["ADD_EP"] if data == CB["OWN_ADD_EP"] else MODE["ADD_KEY"]
        context.user_data["mode"] = mode
        text, kb = views.text_mode_prompt(mode)
        await messaging.show(context, query, text, kb)
        return True

    # export -------------------------------------------------------
    if data == CB["OWN_EXPORT"]:
        content, ep_n, key_n = await store.export_stock()
        if not content.strip():
            text, kb = _simple(
                "Export",
                [f"{G.WARN} nothing to export — the pool is empty."],
                [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
            )
            await messaging.show(context, query, text, kb)
            return True
        buf = io.BytesIO(content.encode("utf-8"))
        buf.name = "vault_export.txt"
        caption = f"{G.OK} vault export · {ep_n} ep · {key_n} keys"
        await query.message.reply_document(document=buf, filename="vault_export.txt", caption=caption)
        text, kb = await views.owner_panel()
        await messaging.show(context, query, text, kb)
        return True

    # reset ---------------------------------------------------------
    if data == CB["OWN_RESET"]:
        context.user_data["mode"] = MODE["RESET_CONFIRM"]
        text, kb = views.reset_confirm()
        await messaging.show(context, query, text, kb)
        return True

    if data == CB["OWN_RESET_NO"]:
        context.user_data.pop("mode", None)
        await _show_panel(context, query)
        return True

    # broadcast ------------------------------------------------------
    if data == CB["OWN_BROADCAST"]:
        if context.bot_data.get("bc_running"):
            text, kb = _simple(
                "Broadcast",
                [f"{G.BOLT} a broadcast is already running — wait for its receipt."],
                [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
            )
            await messaging.show(context, query, text, kb)
            return True
        context.user_data["mode"] = MODE["BROADCAST"]
        text, kb = views.text_mode_prompt(MODE["BROADCAST"])
        await messaging.show(context, query, text, kb)
        return True

    # inbox ----------------------------------------------------------
    if data.startswith(CB["OWN_INBOX"]):
        kind_idx = data[len(CB["OWN_INBOX"]):]
        kind, _, idx_raw = kind_idx.partition(":")
        if kind not in ("contact", "hit"):
            return True
        idx = _as_int(idx_raw, 0)
        text, kb = await views.owner_inbox(kind, idx)
        await messaging.show(context, query, text, kb)
        return True

    if data.startswith(CB["OWN_INBOX_READ"]):
        kind, _, raw_id = data[len(CB["OWN_INBOX_READ"]):].partition(":")
        item_id = _as_int(raw_id, 0)
        if item_id:
            await store.mailbox_mark_read(kind, item_id)
        text, kb = await views.owner_inbox(kind, 0)
        await messaging.show(context, query, text, kb)
        return True

    if data.startswith(CB["OWN_INBOX_DEL"]):
        kind, _, raw_id = data[len(CB["OWN_INBOX_DEL"]):].partition(":")
        item_id = _as_int(raw_id, 0)
        if item_id:
            await store.mailbox_delete(kind, item_id)
        text, kb = await views.owner_inbox(kind, 0)
        await messaging.show(context, query, text, kb)
        return True

    if data.startswith(CB["OWN_INBOX_READALL"]):
        kind = data[len(CB["OWN_INBOX_READALL"]):]
        await store.mailbox_mark_all_read(kind)
        text, kb = await views.owner_inbox(kind, 0)
        await messaging.show(context, query, text, kb)
        return True

    # logs -------------------------------------------------------------
    if data == CB["OWN_LOGS"]:
        text, kb = await views.owner_logs()
        await messaging.show(context, query, text, kb)
        return True

    return False


def _as_int(raw: str, default: int | None):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# ────────────────────────────────────────────────────────────────
#  silent owner text commands (never listed anywhere)
# ────────────────────────────────────────────────────────────────
async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not store.is_owner(update.effective_user.id):
        return
    page = 1
    if context.args:
        page = _as_int(context.args[0], 1)
    text, kb = await views.owner_users(page)
    await messaging.send(context, update.effective_chat.id, text, kb)


async def cmd_manage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not store.is_owner(update.effective_user.id):
        return
    if not context.args:
        await _show_panel(context, chat_id=update.effective_chat.id)
        return
    target = await _resolve_target(context.args[0])
    if target is None:
        text, kb = _not_found(context.args[0])
        await messaging.send(context, update.effective_chat.id, text, kb)
        return
    text, kb = await views.owner_manage(target)
    await messaging.send(context, update.effective_chat.id, text, kb)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not store.is_owner(update.effective_user.id):
        return
    content, ep_n, key_n = await store.export_stock()
    if not content.strip():
        text, kb = _simple(
            "Export",
            [f"{G.WARN} nothing to export — the pool is empty."],
            [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
        )
        await messaging.send(context, update.effective_chat.id, text, kb)
        return
    buf = io.BytesIO(content.encode("utf-8"))
    buf.name = "vault_export.txt"
    await update.message.reply_document(
        document=buf,
        filename="vault_export.txt",
        caption=f"{G.OK} vault export · {ep_n} ep · {key_n} keys",
    )


# ────────────────────────────────────────────────────────────────
#  text-mode processing (owner flows)
# ────────────────────────────────────────────────────────────────
async def owner_text(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> bool:
    """Handle one owner text reply for the active mode. True = consumed."""
    uid = update.effective_user.id
    if not store.is_owner(uid):
        return False
    text = (update.message.text or "").strip()

    # add stock ----------------------------------------------------
    if mode == MODE["ADD_EP"] or mode == MODE["ADD_KEY"]:
        kind = EP if mode == MODE["ADD_EP"] else KEY
        lines = text.splitlines()
        result = await store.add_items(uid, kind, lines)
        cache.stock_mutate(kind, result.added)
        page_text, kb = views.add_done(kind, result.added, result.failed)
        await _refresh_or_send(context, update, page_text, kb)
        context.user_data.pop("mode", None)
        return True

    # search user ---------------------------------------------------
    if mode == MODE["SEARCH_USER"]:
        target = await _resolve_target(text)
        context.user_data.pop("mode", None)
        if target is None:
            page_text, kb = _not_found(text)
        else:
            page_text, kb = await views.owner_manage(target)
        await _refresh_or_send(context, update, page_text, kb)
        return True

    # broadcast ------------------------------------------------------
    if mode == MODE["BROADCAST"]:
        context.user_data.pop("mode", None)
        await _launch_broadcast(context, update, text)
        return True

    # reset confirm ---------------------------------------------------
    if mode == MODE["RESET_CONFIRM"]:
        context.user_data.pop("mode", None)
        if text.strip().upper() == "WIPE":
            await store.reset_all_stock()
            cache.stock_invalidate()
            page_text, kb = _simple(
                "Pool reset",
                [f"{G.OK} wiped everything — stock and serve history are empty."],
                [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
            )
        else:
            page_text, kb = _simple(
                "Reset aborted",
                [f"{G.OK} nothing was touched (you typed the wrong word anyway)."],
                [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
            )
        await _refresh_or_send(context, update, page_text, kb)
        return True

    return False


async def _refresh_or_send(context, update: Update, text: str, kb) -> None:
    """Prefer updating the live page (the prompt we rendered); else reply."""
    pg = messaging.current_page(context)
    if pg is not None:
        msg = await messaging.edit(context, pg[0], pg[1], text, kb)
        if msg is not None:
            return
    await messaging.send(context, update.effective_chat.id, text, kb)


async def _launch_broadcast(context, update: Update, message_text: str) -> None:
    chat_id = update.effective_chat.id
    context.bot_data["bc_running"] = True

    async def job():
        try:
            ids = await store.all_user_ids()
            delivered = 0
            for n, target in enumerate(ids, start=1):
                if await _notify_plain(context, target, message_text):
                    delivered += 1
                if n % 25 == 0:
                    await asyncio.sleep(0.05)
            receipt = (
                f"{G.OK} broadcast done\n{G.LINE_S}\n"
                f"delivered {delivered}/{len(ids)} members"
            )
            await _deliver_receipt(context, chat_id, receipt)
        finally:
            context.bot_data["bc_running"] = False

    task = asyncio.create_task(job())
    tasks = context.bot_data.setdefault("bc_tasks", [])
    tasks.append(task)
    task.add_done_callback(lambda _t: tasks.remove(task) if task in tasks else None)

    # acknowledge instantly on the live page
    ack, kb = _simple(
        "Broadcast launched",
        [f"{G.BOLT} message is on its way to every member — receipt incoming."],
        [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
    )
    await _refresh_or_send(context, update, ack, kb)


async def _deliver_receipt(context, chat_id: int, receipt: str) -> None:
    pg = messaging.current_page(context)
    if pg is not None:
        try:
            await messaging.edit(context, pg[0], pg[1], receipt, None)
            return
        except Exception:  # noqa: BLE001
            pass
    await messaging.send(context, chat_id, receipt, None)


async def _notify_plain(context, chat_id: int, text: str) -> bool:
    """Broadcast sends raw text (no parse mode — no surprise markdown)."""
    try:
        from core.net import _with_retries

        await _with_retries(lambda: context.bot.send_message(chat_id=chat_id, text=text))
        return True
    except Exception:  # noqa: BLE001
        return False
