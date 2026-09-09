"""
Hᴀɴᴅʟᴇʀꜱ · ᴜꜱᴇʀ ꜱᴘᴀᴄᴇ ────────
Commands and button flows available to every member (owner included):
start splash, home hub, drop vault, results, feedback, profile,
stock, tiers, contact, inbox-write, hit reports.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

import config
from core import animation as anim
from core import cache, messaging, net, views
from core.constants import CB, EP, KEY, MODE, STOCK_LABEL
from core.style import G, sc
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
    await messaging.show(context, query, text, kb)


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
        if i < len(frames):
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
#  THE PULL  (generate)
# ────────────────────────────────────────────────────────────────
async def run_pull(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str) -> None:
    query = update.callback_query
    uid = _uid(update)
    username, first_name = _user_card(update)
    owner = store.is_owner(uid)

    if await cache.banned(uid):
        await _lock(context, query, uid)
        return

    label = STOCK_LABEL.get(kind, "item")
    res = await store.serve_claim(uid, username, first_name, kind, owner=owner)

    if res.status == "ok":
        # keep the on-button counters honest right away
        cache.stock_mutate(kind, -1)
        # little flourish, then the drop lands on this very message
        await anim.gen_flourish(
            query, label, fast=owner, wait=config.ANIM_STEP_SEC
        )
        text, kb = views.result(res, owner=owner)
        await messaging.show(context, query, text, kb)
        return

    if res.status == "cooldown":
        text, kb = views.cooldown(res)
    elif res.status == "limit":
        text, kb = views.limit_wall(res)
    elif res.status == "empty":
        text, kb = views.empty(kind)
    else:  # banned (paranoia)
        text, kb = await _banned_page_for(uid)
    await messaging.show(context, query, text, kb)


# ────────────────────────────────────────────────────────────────
#  feedback
# ────────────────────────────────────────────────────────────────
async def do_feedback(
    update: Update, context: ContextTypes.DEFAULT_TYPE, verdict: str, kind: str, item_id: int
) -> None:
    query = update.callback_query
    uid = _uid(update)
    owner = store.is_owner(uid)
    username, first_name = _user_card(update)

    fb = await store.record_feedback(uid, kind, item_id, verdict, owner=owner)
    if fb.banned:
        cache.banned_mark(uid, True)
    if fb.removed:
        cache.stock_mutate(kind, -1)
        await _notify_dead(context, update, fb)

    text, kb = views.feedback_done(fb, kind)
    await messaging.show(context, query, text, kb)


async def _notify_dead(context, update: Update, fb: store.FeedbackResult) -> None:
    try:
        item = fb.removed or {}
        if fb.removed_word == "email":
            payload = f"{item.get('email')}:{item.get('password')}"
        else:
            payload = str(item.get("key", ""))
        u = update.effective_user
        handle = f"@{u.username}" if u.username else u.id
        body = (
            f"{G.NO} dead report\n{G.LINE_S}\n"
            f"from {messaging.esc(str(handle))} · id {u.id}\n"
            f"type: {fb.removed_word} #{item.get('id')}\n"
            f"value: <code>{messaging.esc(payload)}</code>"
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

    # text-mode cancel (shared)
    if data == CB["CANCEL_MODE"]:
        text, kb = await views.home(uid)
        await messaging.show(context, query, text, kb)
        return True

    # ---------- navigation ----------
    if data == CB["HOME"]:
        if await cache.banned(uid):
            text, kb = await _banned_page_for(uid)
        else:
            text, kb = await views.home(uid)
        await messaging.show(context, query, text, kb)
        return True

    if data == CB["STOCK"] or data == CB["STOCK_FORCE"]:
        text, kb = await views.stock_page(force=data == CB["STOCK_FORCE"])
        await messaging.show(context, query, text, kb)
        return True

    if data == CB["PROFILE"]:
        text, kb = await views.profile_page(uid)
        await messaging.show(context, query, text, kb)
        return True

    if data == CB["PLANS"]:
        text, kb = await views.plans_page(uid)
        await messaging.show(context, query, text, kb)
        return True

    if data.startswith(CB["PLAN_DETAIL"]):
        plan = data[len(CB["PLAN_DETAIL"]):]
        text, kb = views.plan_detail_page(plan, uid)
        await messaging.show(context, query, text, kb)
        return True

    if data == CB["CONTACT"]:
        text, kb = views.contact_page(uid)
        await messaging.show(context, query, text, kb)
        return True

    # ---------- text-mode entry ----------
    if data == CB["MSG_WRITE"]:
        if await cache.banned(uid):
            await _lock(context, query, uid)
            return True
        context.user_data["mode"] = MODE["WRITE_MSG"]
        text, kb = views.text_mode_prompt(MODE["WRITE_MSG"])
        await messaging.show(context, query, text, kb)
        return True

    # ---------- pulls ----------
    if data in (CB["GEN_EP"], CB["GEN_KEY"]):
        if await cache.banned(uid):
            await _lock(context, query, uid)
            return True
        await run_pull(update, context, EP if data == CB["GEN_EP"] else KEY)
        return True

    if data.startswith(CB["GEN_AGAIN"]):
        if await cache.banned(uid):
            await _lock(context, query, uid)
            return True
        kind = data.split(":", 1)[1] if ":" in data else KEY
        await run_pull(update, context, kind)
        return True

    # ---------- feedback ----------
    for verdict, code in (("working", CB["FB_WORK"]), ("dead", CB["FB_DEAD"]), ("skip", CB["FB_SKIP"])):
        if data.startswith(code + ":"):
            if await cache.banned(uid):
                await _lock(context, query, uid)
                return True
            try:
                _, kind, raw_id = data.split(":")
                await do_feedback(update, context, verdict, kind, int(raw_id))
            except ValueError:
                pass  # expired / malformed — silently ignore
            return True

    # anything else (owner codes land here only for non-owners)
    if data.startswith("o"):
        return True
    return False
