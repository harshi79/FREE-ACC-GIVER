"""
Hᴀɴᴅʟᴇʀꜱ · ᴏᴡɴᴇʀ ────────
The entire privileged surface, reachable ONLY by the owner id. Every
route is a button inside the hidden Owner Core panel; the text
commands below are silent hotkeys that never appear in any help or
menu (and do nothing for anyone else).

Vault 2.0: every pool gets its own add / export / remove-by-id / reset
row inside **Vault manager**, and new pools are created from inside the
bot ("＋ New pool" — two inline steps, no code change). Dead reports
notify but never auto-delete (unless BOT_AUTO_REMOVE_DEAD=1).

Every "o*" callback that any owner view renders MUST appear in
_OWNER_PREFIXES below and be answered here — the selftest taps every
button on every owner page and fails if one falls into the void.
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
from data.catalog import Pool, clip, slugify

log = logging.getLogger("owner")

# owner-only callback prefixes — never answered by the user router
_OWNER_PREFIXES = tuple(
    {
        CB["OWN_PANEL"],
        CB["OWN_USER_PAGE"],
        CB["OWN_MANAGE"],
        CB["OWN_SEARCH"],
        CB["OWN_PLAN"],
        CB["OWN_REP"],
        CB["OWN_BAN"],
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
        # vault manager + per-pool actions
        CB["OWN_VAULT_MGR"],
        CB["OWN_NEW_POOL"],
        CB["OWN_NEW_POOL_KIND"],
        CB["OWN_POOL_ADD"],
        CB["OWN_POOL_EXPORT"],
        CB["OWN_POOL_REMOVE"],
        CB["OWN_POOL_RESET"],
        CB["OWN_ADMIN"],
    }
)


def owner_codes(data: str) -> bool:
    return data.startswith(_OWNER_PREFIXES)


def _simple(title: str, lines: list[str], kb) -> tuple[str, IM]:
    return "\n".join([page_header(title), G.LINE, *lines]) + footer(), IM(kb)


async def _answer(query, text: str | None = None) -> None:
    """Instant spinner-stop, with an optional dynamic toast."""
    try:
        await query.answer(text)
    except Exception:  # noqa: BLE001 — already answered / expired query
        pass


# ────────────────────────────────────────────────────────────────
#  helpers
# ────────────────────────────────────────────────────────────────
async def _pool_for(slug: str) -> Pool | None:
    await cache.pools()
    return cache.get_pool(slug)


async def _show_panel(context, query=None, chat_id: int | None = None) -> None:
    text, kb = await views.owner_panel()
    if query is not None:
        await messaging.show_nav(context, query, text, kb)
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
    await messaging.show_nav(context, query, text, kb)


async def _manage(context, query, uid: int) -> None:
    text, kb = await views.owner_manage(uid)
    await messaging.show_nav(context, query, text, kb)


async def _manager(context, query, page: int = 1) -> None:
    text, kb = await views.owner_vault_manager(page)
    await messaging.show_nav(context, query, text, kb)


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


async def _send_document(query, content: str, filename: str, caption: str) -> None:
    buf = io.BytesIO(content.encode("utf-8"))
    buf.name = filename
    await query.message.reply_document(document=buf, filename=filename, caption=caption)


# ────────────────────────────────────────────────────────────────
#  owner callback router — returns True when it consumed the data
# ────────────────────────────────────────────────────────────────
async def owner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not store.is_owner(update.effective_user.id):
        return False  # a non-owner walked into an owner code; user router guards it
    query = update.callback_query
    data = query.data or ""

    # panel / stats -------------------------------------------------
    if data == CB["OWN_PANEL"] or data == CB["OWN_STATS"]:
        await _answer(query)
        await _show_panel(context, query)
        return True

    # users --------------------------------------------------------
    if data.startswith(CB["OWN_USER_PAGE"]):
        page = _as_int(data[len(CB["OWN_USER_PAGE"]):], 1)
        await _answer(query)
        await _users_page(context, query, page)
        return True

    if data.startswith(CB["OWN_MANAGE"]):
        uid = _as_int(data[len(CB["OWN_MANAGE"]):], None)
        await _answer(query)
        if uid is None:
            await _users_page(context, query, 1)
        else:
            await _manage(context, query, uid)
        return True

    if data == CB["OWN_BANNED"]:
        await _answer(query)
        text, kb = await views.owner_banned()
        await messaging.show_nav(context, query, text, kb)
        return True

    if data == CB["OWN_SEARCH"]:
        await _answer(query)
        context.user_data["mode"] = MODE["SEARCH_USER"]
        text, kb = views.text_mode_prompt(MODE["SEARCH_USER"])
        await messaging.show_nav(context, query, text, kb)
        return True

    # manage: plan / rep / ban --------------------------------------
    if data.startswith(CB["OWN_PLAN"]):
        rest = data[len(CB["OWN_PLAN"]):]
        uid_raw, _, plan = rest.partition(":")
        uid = _as_int(uid_raw, None)
        changed = False
        if uid is not None and plan in config.PLAN_ORDER:
            await store.set_plan(uid, plan)
            changed = True
        await _answer(query, f"plan → {plan}" if changed else "no change")
        await _manage(context, query, uid or 0)
        return True

    if data.startswith(CB["OWN_REP"]):
        rest = data[len(CB["OWN_REP"]):]
        uid_raw, _, delta_raw = rest.partition(":")
        uid = _as_int(uid_raw, None)
        delta = _as_int(delta_raw, 0)
        if uid is not None:
            await store.add_rep(uid, delta)
        await _answer(query, f"{delta:+d} rep")
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
            await _answer(query, "locked" if flag else "lifted")
        else:
            await _answer(query, "the owner account is untouchable")
        await _manage(context, query, uid or 0)
        return True

    # vault manager ---------------------------------------------------
    if data.startswith(CB["OWN_VAULT_MGR"]):
        page = _as_int(data[len(CB["OWN_VAULT_MGR"]):], 1)
        await _answer(query)
        await _manager(context, query, page)
        return True

    if data == CB["OWN_NEW_POOL"]:
        await _answer(query, "name it — one word is fine")
        context.user_data["mode"] = MODE["NEW_POOL"]
        text, kb = views.pool_prompt_new()
        await messaging.show_nav(context, query, text, kb)
        return True

    if data.startswith(CB["OWN_NEW_POOL_KIND"]):
        await _create_pool(context, query, data[len(CB["OWN_NEW_POOL_KIND"]):])
        return True

    if data.startswith(CB["OWN_POOL_ADD"]):
        slug = data[len(CB["OWN_POOL_ADD"]):]
        pool = await _pool_for(slug)
        if pool is None:
            await _answer(query, "pool not found")
            return True
        context.user_data["mode"] = MODE["ADD_STOCK"]
        context.user_data["mode_pool"] = slug
        await _answer(query, f"add to {clip(pool.label, 16)}")
        text, kb = views.pool_prompt_add(pool)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data.startswith(CB["OWN_POOL_EXPORT"]):
        slug = data[len(CB["OWN_POOL_EXPORT"]):]
        pool = await _pool_for(slug)
        if pool is None:
            await _answer(query, "pool not found")
            return True
        content, n = await store.export_pool(pool.kind, pool.category)
        if not content.strip():
            await _answer(query, "pool is empty")
            text, kb = _simple(
                "Export",
                [f"{G.WARN} {esc(pool.label)} holds nothing to export."],
                [[IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1")]],
            )
            await messaging.show_nav(context, query, text, kb)
            return True
        await _send_document(
            query, content, f"vault_{pool.category}.txt",
            f"{G.OK} {clip(pool.label, 24)} · {n} slots (this pool only)",
        )
        await _answer(query, f"sent {n} lines")
        return True

    if data.startswith(CB["OWN_POOL_REMOVE"]):
        slug = data[len(CB["OWN_POOL_REMOVE"]):]
        pool = await _pool_for(slug)
        if pool is None:
            await _answer(query, "pool not found")
            return True
        context.user_data["mode"] = MODE["POOL_REMOVE"]
        context.user_data["mode_pool"] = slug
        await _answer(query, "send the item id")
        text, kb = views.pool_prompt_remove(pool)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data.startswith(CB["OWN_POOL_RESET"]):
        slug = data[len(CB["OWN_POOL_RESET"]):]
        pool = await _pool_for(slug)
        if pool is None:
            await _answer(query, "pool not found")
            return True
        context.user_data["mode"] = MODE["RESET_POOL"]
        context.user_data["mode_pool"] = slug
        await _answer(query, "type WIPE to confirm")
        text, kb = views.pool_prompt_reset(pool)
        await messaging.show_nav(context, query, text, kb)
        return True

    # export all -----------------------------------------------------
    if data == CB["OWN_EXPORT"]:
        content, ep_n, key_n = await store.export_stock()
        if not content.strip():
            await _answer(query, "pool is empty")
            text, kb = _simple(
                "Export",
                [f"{G.WARN} nothing to export — every pool is empty."],
                [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
            )
            await messaging.show_nav(context, query, text, kb)
            return True
        await _send_document(
            query, content, "vault_export.txt",
            f"{G.OK} vault export · {ep_n} ep · {key_n} keys · per-pool sections",
        )
        await _answer(query, "file sent")
        await _show_panel(context, query)
        return True

    # reset all (WIPE-gated) ------------------------------------------
    if data == CB["OWN_RESET"]:
        await _answer(query, "type WIPE to confirm")
        context.user_data["mode"] = MODE["RESET_CONFIRM"]
        text, kb = views.reset_confirm()
        await messaging.show_nav(context, query, text, kb)
        return True

    if data == CB["OWN_RESET_NO"]:
        await _answer(query, "cancelled")
        context.user_data.pop("mode", None)
        await _show_panel(context, query)
        return True

    # broadcast --------------------------------------------------------
    if data == CB["OWN_BROADCAST"]:
        if context.bot_data.get("bc_running"):
            await _answer(query, "already running")
            text, kb = _simple(
                "Broadcast",
                [f"{G.BOLT} a broadcast is already running — wait for its receipt."],
                [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
            )
            await messaging.show_nav(context, query, text, kb)
            return True
        await _answer(query)
        context.user_data["mode"] = MODE["BROADCAST"]
        text, kb = views.text_mode_prompt(MODE["BROADCAST"])
        await messaging.show_nav(context, query, text, kb)
        return True

    # inbox ------------------------------------------------------------
    if data.startswith(CB["OWN_INBOX"]):
        kind_idx = data[len(CB["OWN_INBOX"]):]
        kind, _, idx_raw = kind_idx.partition(":")
        if kind not in ("contact", "hit"):
            await _answer(query)
            return True
        idx = _as_int(idx_raw, 0)
        await _answer(query)
        text, kb = await views.owner_inbox(kind, idx)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data.startswith(CB["OWN_INBOX_READ"]):
        kind, _, raw_id = data[len(CB["OWN_INBOX_READ"]):].partition(":")
        item_id = _as_int(raw_id, 0)
        if item_id:
            await store.mailbox_mark_read(kind, item_id)
        await _answer(query, "marked read")
        text, kb = await views.owner_inbox(kind, 0)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data.startswith(CB["OWN_INBOX_DEL"]):
        kind, _, raw_id = data[len(CB["OWN_INBOX_DEL"]):].partition(":")
        item_id = _as_int(raw_id, 0)
        if item_id:
            await store.mailbox_delete(kind, item_id)
        await _answer(query, "deleted")
        text, kb = await views.owner_inbox(kind, 0)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data.startswith(CB["OWN_INBOX_READALL"]):
        kind = data[len(CB["OWN_INBOX_READALL"]):]
        n = await store.mailbox_mark_all_read(kind)
        await _answer(query, f"{n} read")
        text, kb = await views.owner_inbox(kind, 0)
        await messaging.show_nav(context, query, text, kb)
        return True

    # logs -------------------------------------------------------------
    if data == CB["OWN_LOGS"]:
        await _answer(query)
        text, kb = await views.owner_logs()
        await messaging.show_nav(context, query, text, kb)
        return True

    # /admin manual (also reachable via buttons) ------------------------
    if data.startswith(CB["OWN_ADMIN"]):
        page = _as_int(data[len(CB["OWN_ADMIN"]):], 1)
        await _answer(query)
        text, kb = views.owner_admin(page)
        await messaging.show_nav(context, query, text, kb)
        return True

    return False


# ────────────────────────────────────────────────────────────────
#  new pool · creation (name parked by text mode, kind via buttons)
# ────────────────────────────────────────────────────────────────
async def _create_pool(context, query, kind: str) -> None:
    if kind not in (EP, KEY):
        await _answer(query, "unknown kind")
        return
    name = str(context.user_data.pop("new_pool", "") or "").strip()
    context.user_data.pop("mode", None)
    if not name:
        await _answer(query, "send the name first")
        context.user_data["mode"] = MODE["NEW_POOL"]  # re-arm so typing works at once
        text, kb = views.pool_prompt_new()
        await messaging.show_nav(context, query, text, kb)
        return
    slug, err = await store.create_pool(name, kind)
    if err:
        toast = {
            "name_exists": "that pool already exists — pick another name",
            "bad_name": "needs letters or digits in the name",
            "busy": "name is taken — try another",
        }.get(err, "could not create")
        await _answer(query, toast)
        text, kb = _simple(
            "New pool",
            [f"{G.NO} {esc(toast)}", f"{G.ARR} nothing was created — try a different name."],
            [[IB("✕ Try again", callback_data=CB["OWN_NEW_POOL"]),
              IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1")]],
        )
        await messaging.show_nav(context, query, text, kb)
        return
    cache.pools_invalidate()
    # land on the page of the manager that shows the fresh pool
    pools = await cache.pools()
    idx = next((i for i, p in enumerate(pools) if p.category == slug), 0)
    page = idx // views.MANAGER_PER_PAGE + 1
    await _answer(query, f"pool live — {clip(name, 18)} (no code needed)")
    await _manager(context, query, page)


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
            [f"{G.WARN} nothing to export — every pool is empty."],
            [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
        )
        await messaging.send(context, update.effective_chat.id, text, kb)
        return
    buf = io.BytesIO(content.encode("utf-8"))
    buf.name = "vault_export.txt"
    await update.message.reply_document(
        document=buf,
        filename="vault_export.txt",
        caption=f"{G.OK} vault export · {ep_n} ep · {key_n} keys · per-pool sections",
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Silent owner manual — paged, never advertised anywhere."""
    if not store.is_owner(update.effective_user.id):
        return  # anyone else gets absolutely nothing
    page = 1
    if context.args:
        page = _as_int(context.args[0], 1)
    text, kb = views.owner_admin(page)
    await messaging.send(context, update.effective_chat.id, text, kb)


# ────────────────────────────────────────────────────────────────
#  text-mode processing (owner flows)
# ────────────────────────────────────────────────────────────────
async def owner_text(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str) -> bool:
    """Handle one owner text reply for the active mode. True = consumed."""
    uid = update.effective_user.id
    if not store.is_owner(uid):
        return False
    text = (update.message.text or "").strip()

    # add stock INTO the chosen pool ---------------------------------
    if mode == MODE["ADD_STOCK"]:
        slug = context.user_data.pop("mode_pool", None)
        context.user_data.pop("mode", None)
        pool = await _pool_for(slug or "")
        if pool is None:
            page_text, kb = _simple(
                "Unknown pool",
                [f"{G.NO} the target pool vanished — open the manager again."],
                [[IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1")]],
            )
            await _refresh_or_send(context, update, page_text, kb)
            return True
        lines = [ln for ln in text.splitlines() if ln.strip()]
        result = await store.add_items(uid, pool.kind, pool.category, lines)
        cache.pools_invalidate()
        page_text, kb = views.owner_add_done(pool, result.added, result.failed)
        await _refresh_or_send(context, update, page_text, kb)
        return True

    # new pool · step 1: the name -------------------------------------
    if mode == MODE["NEW_POOL"]:
        context.user_data.pop("mode", None)
        name = " ".join(text.split())[:60]
        if not name or not slugify(name):
            page_text, kb = _simple(
                "New pool",
                [f"{G.NO} a pool name needs letters or digits — nothing was created."],
                [[IB("↻ Try again", callback_data=CB["OWN_NEW_POOL"]),
                  IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1")]],
            )
            await _refresh_or_send(context, update, page_text, kb)
            return True
        context.user_data["new_pool"] = name
        page_text, kb = views.pool_pick_kind(name, slugify(name))
        await _refresh_or_send(context, update, page_text, kb)
        return True

    # remove one slot by id (scoped to its pool) -----------------------
    if mode == MODE["POOL_REMOVE"]:
        slug = context.user_data.pop("mode_pool", None)
        context.user_data.pop("mode", None)
        pool = await _pool_for(slug or "")
        if pool is None:
            page_text, kb = _simple(
                "Unknown pool",
                [f"{G.NO} the target pool vanished — open the manager again."],
                [[IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1")]],
            )
            await _refresh_or_send(context, update, page_text, kb)
            return True
        item_id = _as_int(text.split()[0] if text else "", None)
        row = None
        if item_id is not None:
            row = await store.remove_item(pool.kind, pool.category, item_id)
        if row is None:
            page_text, kb = _simple(
                "Nothing removed",
                [
                    f"{G.NO} no id <code>{esc(text[:32])}</code> inside {esc(pool.label)}.",
                    f"{G.ARR} ids are the 'slot #' shown on drop cards / exports.",
                ],
                [[IB("↻ Try again", callback_data=f"{CB['OWN_POOL_REMOVE']}{pool.category}"),
                  IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1")]],
            )
        else:
            cache.pools_invalidate()
            page_text, kb = views.owner_removed(pool, row)
        await _refresh_or_send(context, update, page_text, kb)
        return True

    # per-pool reset (WIPE-gated) ---------------------------------------
    if mode == MODE["RESET_POOL"]:
        slug = context.user_data.pop("mode_pool", None)
        context.user_data.pop("mode", None)
        pool = await _pool_for(slug or "")
        if pool is None:
            page_text, kb = _simple(
                "Unknown pool",
                [f"{G.NO} the target pool vanished — open the manager again."],
                [[IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1")]],
            )
            await _refresh_or_send(context, update, page_text, kb)
            return True
        if text.upper() == "WIPE":
            n = await store.reset_pool(pool.kind, pool.category)
            cache.pools_invalidate()
            page_text, kb = views.owner_reset_done(pool, n, aborted=False)
        else:
            counts = await cache.pool_counts()
            page_text, kb = views.owner_reset_done(pool, counts.get(pool.category, 0), aborted=True)
        await _refresh_or_send(context, update, page_text, kb)
        return True

    # search user ---------------------------------------------------------
    if mode == MODE["SEARCH_USER"]:
        target = await _resolve_target(text)
        context.user_data.pop("mode", None)
        if target is None:
            page_text, kb = _not_found(text)
        else:
            page_text, kb = await views.owner_manage(target)
        await _refresh_or_send(context, update, page_text, kb)
        return True

    # broadcast -------------------------------------------------------------
    if mode == MODE["BROADCAST"]:
        context.user_data.pop("mode", None)
        await _launch_broadcast(context, update, text)
        return True

    # global reset confirm ----------------------------------------------------
    if mode == MODE["RESET_CONFIRM"]:
        context.user_data.pop("mode", None)
        if text.upper() == "WIPE":
            await store.reset_all_stock()
            cache.pools_invalidate()
            page_text, kb = _simple(
                "All pools reset",
                [f"{G.OK} wiped everything — all pools and serve history are empty."],
                [[IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1"),
                  IB("◂ Panel", callback_data=CB["OWN_PANEL"])]],
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


def _as_int(raw, default: int | None):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
