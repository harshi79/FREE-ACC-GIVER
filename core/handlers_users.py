"""
Hᴀɴᴅʟᴇʀꜱ · ᴜꜱᴇʀ ꜱᴘᴀᴄᴇ ────────
Commands and button flows available to every member (owner included):
start splash, home hub, vault grid, drops, feedback, profile, stock,
tiers, contact, inbox-write, hit reports.

Pull rules (vault 2.0):
  • a drop is its OWN new message — "Pull again" never replaces the
    previous card; every earlier result stays on screen untouched;
  • error states (cooldown / daily wall / drained pool) land as their
    own notice message too, so a visible card's credentials can NEVER
    be wiped by a tap;
  • feedback edits its OWN card, appending the verdict line under the
    still-visible credentials;
  • plain menu navigation keeps editing the live menu message.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
from core import animation as anim
from core import cache, messaging, net, views
from core.constants import CB, MODE
from core.messaging import esc, footer
from core.style import G, sc
from data.catalog import Pool
from data import store

log = logging.getLogger("users")


# ────────────────────────────────────────────────────────────────
#  tiny helpers
# ────────────────────────────────────────────────────────────────
def _uid(update: Update) -> int:
    return update.effective_user.id


def _user_card(update: Update) -> tuple[str | None, str | None]:
    u = update.effective_user
    return (u.username or "", u.first_name or "")


async def _banned_page_for(uid: int):
    user = await store.get_user(uid)
    return views.banned_page(user["ban_reason"] if user else None)


async def _lock(context, query, uid: int) -> None:
    text, kb = await _banned_page_for(uid)
    await messaging.show_nav(context, query, text, kb)


async def _pool_for(slug: str) -> Pool | None:
    await cache.pools()
    return cache.get_pool(slug)


# ────────────────────────────────────────────────────────────────
#  /start — boot animation then the hub
# ────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _uid(update)
    username, first_name = _user_card(update)
    await store.ensure_user(uid, username, first_name)
    chat_id = update.effective_chat.id

    frames = [
        f"{G.BOLT} ᴡᴀʀᴍɪɴɢ ᴜᴘ ᴛʜᴇ ʀᴇʟᴀʏ",
        f"{G.DIAM} ᴘᴀʀsɪɴɢ ʏᴏᴜʀ sʟᴏᴛ",
        f"{G.STAR} sʏɴᴄɪɴɢ ᴘʀᴇᴍɪᴜᴍ ᴄʜᴀɴɴᴇʟ",
    ]
    head = f"{sc(config.BOT_NAME)}\n{G.LINE_S}"
    first = await context.bot.send_message(
        chat_id=chat_id, text=f"{head}\n{frames[0]}", parse_mode=messaging.PARSE
    )
    messaging.remember_page(context, first)
    msg_id = first.message_id
    for i, label in enumerate(frames, start=1):
        text = f"{head}\n{label}\n{anim.progress_bar(i, len(frames))}"
        await messaging.edit(context, chat_id, msg_id, text)
        if i < frames and i < len(frames):
            await asyncio.sleep(config.ANIM_STEP_SEC)

    banned = await cache.banned(uid)
    if banned:
        page_text, kb = await _banned_page_for(uid)
    else:
        page_text, kb = await views.home(uid)
    await messaging.edit(context, chat_id, msg_id, page_text, kb)


# ────────────────────────────────────────────────────────────────
#  user commands → a fresh page
# ────────────────────────────────────────────────────────────────
async def cmd_gen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _uid(update)
    if await _guard_banned_cmd(update, context):
        return
    text, kb = await views.vault(uid)
    await messaging.send(context, update.effective_chat.id, text, kb)


async def _guard_banned_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = _uid(update)
    if await cache.banned(uid):
        text, kb = await _banned_page_for(uid)
        await messaging.send(context, update.effective_chat.id, text, kb)
        return True
    return False


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_banned_cmd(update, context):
        return
    text, kb = await views.profile_page(_uid(update))
    await messaging.send(context, update.effective_chat.id, text, kb)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_banned_cmd(update, context):
        return
    text, kb = await views.stock_page()
    await messaging.send(context, update.effective_chat.id, text, kb)


async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_banned_cmd(update, context):
        return
    text, kb = await views.plans_page(_uid(update))
    await messaging.send(context, update.effective_chat.id, text, kb)


async def cmd_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_banned_cmd(update, context):
        return
    text, kb = views.contact_page(_uid(update))
    await messaging.send(context, update.effective_chat.id, text, kb)


async def cmd_hits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_banned_cmd(update, context):
        return
    context.user_data["mode"] = MODE["HIT_REPORT"]
    text, kb = views.text_mode_prompt(MODE["HIT_REPORT"])
    await messaging.send(context, update.effective_chat.id, text, kb)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await _guard_banned_cmd(update, context):
        return
    text, kb = await views.help_page()
    await messaging.send(context, update.effective_chat.id, text, kb)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("mode", None)
    text, kb = await views.home(_uid(update))
    await messaging.send(context, update.effective_chat.id, text, kb)


# ────────────────────────────────────────────────────────────────
#  THE PULL — always a NEW message, one pool only
# ────────────────────────────────────────────────────────────────
async def run_pull(update: Update, context: ContextTypes.DEFAULT_TYPE, pool: Pool) -> None:
    query = update.callback_query
    uid = _uid(update)
    username, first_name = _user_card(update)
    owner = store.is_owner(uid)
    chat_id = query.message.chat_id

    if await cache.banned(uid):
        await _lock(context, query, uid)
        return

    res = await store.serve_claim(
        uid, username, first_name, pool.kind, pool.category,
        owner=owner, pool_label=pool.label,
    )

    if res.status == "ok":
        # per-pool counters refresh on next render
        cache.pools_invalidate()
        text, kb = views.result(res, owner=owner)
        card = await messaging.send_raw(context, chat_id, anim.loading_frame(pool.label), None)
        if card is not None:
            # flourish animates on THIS fresh card only, then the drop lands
            await anim.gen_flourish(
                context.bot, chat_id, card.message_id, pool.label,
                fast=owner, wait=config.ANIM_STEP_SEC,
            )
            final = await messaging.edit_raw(context, chat_id, card.message_id, text, kb)
            mid = final.message_id if final is not None else card.message_id
            if final is None:  # deleted/uneditable — deliver as a new card
                fresh = await messaging.send_raw(context, chat_id, text, kb)
                if fresh is not None:
                    mid = fresh.message_id
        else:
            fresh = await messaging.send_raw(context, chat_id, text, kb)
            mid = fresh.message_id if fresh is not None else None
        if mid is not None:
            messaging.register_card(
                context,
                mid,
                {
                    "body": text.removesuffix(footer()),
                    "slug": pool.category,
                    "kind": pool.kind,
                    "item_id": (res.item or {}).get("id"),
                },
            )
        return

    # every error state is ALSO a fresh notice — a visible card with
    # credentials is never edited by a failed pull.
    if res.status == "cooldown":
        text, kb = views.cooldown(res)
    elif res.status == "limit":
        text, kb = views.limit_wall(res)
    elif res.status == "empty":
        text, kb = views.empty(pool)
    else:  # banned (paranoia)
        text, kb = await _banned_page_for(uid)
    await messaging.send_raw(context, chat_id, text, kb)


# ────────────────────────────────────────────────────────────────
#  feedback — edits the CARD it was tapped on, credentials stay
# ────────────────────────────────────────────────────────────────
async def do_feedback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, verdict: str, slug: str, item_id: int
) -> None:
    query = update.callback_query
    uid = _uid(update)
    owner = store.is_owner(uid)
    chat_id = query.message.chat_id
    mid = query.message.message_id

    pool = await _pool_for(slug)
    if pool is None:
        return  # the pool vanished mid-flight — toast already answered
    fb = await store.record_feedback(
        uid, pool.kind, item_id, verdict, owner=owner,
        category=pool.category, pool_label=pool.label,
    )
    if fb.banned:
        cache.banned_mark(uid, True)
    if verdict == "dead" and (fb.item is not None or fb.removed is not None):
        cache.pools_invalidate()
        await _notify_dead(context, update, fb)

    line, kb = views.feedback_verdict(fb, slug)
    meta = messaging.card_meta(context, mid)
    if meta is not None:
        await messaging.edit_raw(context, chat_id, mid, meta["body"] + line + footer(), kb)
        return
    # card memory gone (e.g. after a restart) — confirm on a new message,
    # the old card is left exactly as it is.
    text, kb2 = views.feedback_done(fb, slug)
    await messaging.send_raw(context, chat_id, text, kb2)


async def _notify_dead(context, update: Update, fb: store.FeedbackResult) -> None:
    try:
        item = fb.item or {}
        if item.get("kind", "ep") == "ep" or "email" in item:
            payload = f"{item.get('email')}:{item.get('password')}"
        else:
            payload = str(item.get("key", ""))
        u = update.effective_user
        handle = f"@{u.username}" if u.username else u.id
        fate = (
            "AUTO-REMOVED from pool" if fb.removed else "KEPT — your call"
        )
        body = (
            f"{G.NO} dead report · pool: <b>{esc(fb.pool_label or '—')}</b>\n{G.LINE_S}\n"
            f"from {esc(str(handle))} · id {u.id}\n"
            f"type: {item.get('kind', 'ep')} #{item.get('id')} · {fate}\n"
            f"value: <code>{esc(payload)}</code>\n"
            f"{G.ARR} vault manager → ✕ remove by id  ·  ⚠ reset pool"
        )
        await net.notify(context, config.OWNER_ID, body, parse_mode=messaging.PARSE)
    except Exception:  # noqa: BLE001
        log.exception("dead-report notification failed")


# ────────────────────────────────────────────────────────────────
#  user callback dispatcher
# ────────────────────────────────────────────────────────────────
async def user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True when it handled the callback."""
    query = update.callback_query
    data = query.data or ""
    uid = _uid(update)

    # navigation always leaves text-modes behind (entry buttons re-arm them)
    context.user_data.pop("mode", None)
    context.user_data.pop("mode_pool", None)

    # text-mode cancel (shared)
    if data == CB["CANCEL_MODE"]:
        text, kb = await views.home(uid)
        await messaging.show_nav(context, query, text, kb)
        return True

    # ---------- navigation (edits the live MENU, never a card) ----------
    if data == CB["HOME"]:
        if await cache.banned(uid):
            text, kb = await _banned_page_for(uid)
        else:
            text, kb = await views.home(uid)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data == CB["VAULT"]:
        text, kb = await views.vault(uid)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data == CB["STOCK"] or data == CB["STOCK_FORCE"]:
        text, kb = await views.stock_page(force=data == CB["STOCK_FORCE"])
        await messaging.show_nav(context, query, text, kb)
        return True

    if data == CB["PROFILE"]:
        text, kb = await views.profile_page(uid)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data == CB["PLANS"]:
        text, kb = await views.plans_page(uid)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data.startswith(CB["PLAN_DETAIL"]):
        plan = data[len(CB["PLAN_DETAIL"]):]
        text, kb = views.plan_detail_page(plan, uid)
        await messaging.show_nav(context, query, text, kb)
        return True

    if data == CB["CONTACT"]:
        text, kb = views.contact_page(uid)
        await messaging.show_nav(context, query, text, kb)
        return True

    # ---------- text-mode entry ----------
    if data == CB["MSG_WRITE"]:
        if await cache.banned(uid):
            await _lock(context, query, uid)
            return True
        context.user_data["mode"] = MODE["WRITE_MSG"]
        text, kb = views.text_mode_prompt(MODE["WRITE_MSG"])
        await messaging.show_nav(context, query, text, kb)
        return True

    # ---------- pulls — ALWAYS a new card, scoped to ONE pool ----------
    if data.startswith(CB["POOL"]):
        slug = data[len(CB["POOL"]):]
        pool = await _pool_for(slug)
        if pool is None:
            text, kb = views.empty(None)
            await messaging.send_raw(context, query.message.chat_id, text, kb)
            return True
        await run_pull(update, context, pool)
        return True

    if data.startswith(CB["GEN_AGAIN"]):
        slug = data[len(CB["GEN_AGAIN"]):]
        pool = await _pool_for(slug)
        if pool is None:
            text, kb = views.empty(None)
            await messaging.send_raw(context, query.message.chat_id, text, kb)
            return True
        await run_pull(update, context, pool)
        return True

    # ---------- feedback (fw|fd|fs):<slug>:<id>) ----------
    for verdict, code in (("working", CB["FB_WORK"]), ("dead", CB["FB_DEAD"]), ("skip", CB["FB_SKIP"])):
        if data.startswith(code + ":"):
            if await cache.banned(uid):
                await _lock(context, query, uid)
                return True
            try:
                _, slug, raw_id = data.split(":")
                await do_feedback(update, context, verdict, slug, int(raw_id))
            except ValueError:
                pass  # expired / malformed — silently ignore
            return True

    # anything else (owner codes land here only for non-owners)
    if data.startswith("o"):
        return True
    return False
