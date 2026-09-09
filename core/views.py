"""
Vɪᴇᴡꜱ ────────
Every screen the bot can render, as (text, reply_markup) pairs.
Nothing here talks to Telegram; handlers fetch a tiny bit of state,
call these builders and hand the result to core.messaging.

Vault 2.0: the drop vault is a GRID OF POOLS (one per brand / service).
Every screen — home chips, grid, stock page, result cards, feedback,
the owner manager — is pool-aware and pools are never mixed.
"""
from __future__ import annotations

from datetime import datetime

from telegram import InlineKeyboardButton as IB
from telegram import InlineKeyboardMarkup as IM

import config
from core import cache
from core.constants import CB, EP, KEY, MODE, STOCK_LABEL, VERDICT_BADGE
from core.messaging import esc, footer, page_header
from core.style import G, sc
from data import store
from data.catalog import KIND_SHORT, Pool, clip, pool_row_label


# ────────────────────────────────────────────────────────────────
#  tiny helpers
# ────────────────────────────────────────────────────────────────
def _pl(plan: str) -> str:
    return f"{config.PLAN_BADGE.get(plan, G.DIAM)} {sc(config.PLAN_TITLE.get(plan, plan))}"


def _lim(plan: str, daily: int) -> str:
    limit = store.plan_limit(plan)
    return f"{daily}/{limit}" if limit is not None else f"{daily}/∞"


def _pool_btn(pool: Pool, count: int, wide: bool = True) -> IB:
    label = pool_row_label(pool, count)
    prefix = f"{G.BOLT} " if wide else f"{G.ARR} "
    return IB(f"{prefix}{label}", callback_data=f"{CB['POOL']}{pool.category}")


def _btn(text: str, data: str) -> list[IB]:
    return [IB(text=text, callback_data=data)]


def _url_owner() -> str:
    return f"https://t.me/{config.OWNER_USERNAME}"


def _grid_buttons(pools: list[Pool], counts: dict[str, int], *, per_row: int = 2) -> list[list[IB]]:
    rows: list[list[IB]] = []
    row: list[IB] = []
    for p in pools:
        row.append(_pool_btn(p, counts.get(p.category, 0)))
        if len(row) == per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def _grouped(pools: list[Pool]) -> tuple[list[Pool], list[Pool]]:
    return (
        [p for p in pools if p.kind == EP],
        [p for p in pools if p.kind == KEY],
    )


# ────────────────────────────────────────────────────────────────
#  USER SPACE
# ────────────────────────────────────────────────────────────────
async def home(uid: int) -> tuple[str, IM]:
    owner = store.is_owner(uid)
    profile = await store.get_profile(uid)
    await cache.snapshot()
    pools = await cache.pools()
    stock = await cache.stock()
    total_users = await cache.users()

    name = (profile.get("first_name") if profile else None) or "there"
    plan = profile.get("plan") if profile else "free"
    rep = profile.get("reputation") if profile else config.INITIAL_REPUTATION
    daily = int(profile.get("today_count")) if profile else 0
    total_gens = int(profile.get("total_gens")) if profile else 0
    joined = (profile.get("joined_at") if profile else None) or datetime.now()
    fresh = (datetime.now() - joined).total_seconds() < 150

    lines = [
        page_header(config.BOT_NAME),
        G.LINE,
        f"{G.BOLT} fast · smooth · premium drops",
        f"{G.ARR} every brand lives in its own pool — picks never mix.",
        "",
    ]
    if owner:
        lines += [
            f"{G.DOTF} <b>owner relay</b> — every wall is bypassed for you",
            "",
        ]
    if fresh:
        lines.append(f"{G.DOTF} hello <b>{esc(name)}</b> — your slot just came alive [+{config.INITIAL_REPUTATION} {G.REP} rep]")
    else:
        lines.append(f"{G.DOTF} hello <b>{esc(name)}</b> — welcome back, everything is synced")
    lines += [
        f"{G.DIAM} today: {_lim(plan, daily)} pulls" + (" · unlocked again at midnight" if store.plan_limit(plan) else " · unlimited tier"),
        f"{G.REP} reputation: {rep} {G.REP}   ·   {G.DIAM} all-time pulls: {total_gens}",
        "",
        f"{G.CHAT} vault live · {total_users} members · {len(pools)} pools · "
        f"accounts {stock['ep']} · keys {stock['key']}",
        f"{G.STAR} hottest pools — one tap drops a fresh card:",
    ]

    hot = cache.hottest(limit=4)
    kb: list[list[IB]] = []
    for pair in (hot[i : i + 2] for i in range(0, len(hot), 2)):
        kb.append([IB(f"{G.DIAM} {clip(p.label, 16)} [{n}]", callback_data=f"{CB['POOL']}{p.category}") for p, n in pair])
    kb.append([IB(f"{G.GRID} All pools · {len(pools)}", callback_data=CB["VAULT"]),
               IB(f"{G.DOT} Stock", callback_data=CB["STOCK"])])
    kb.append([IB(f"{G.DOTF} Profile", callback_data=CB["PROFILE"]),
               IB(f"{G.STAR} Plans", callback_data=CB["PLANS"])])
    kb.append([IB(f"{G.MAIL} Contact", callback_data=CB["CONTACT"])])
    if owner:
        kb.append([IB(f"{G.BOLT} Owner core", callback_data=CB["OWN_PANEL"])])
    return "\n".join(lines) + footer(), IM(kb)


async def vault(uid: int) -> tuple[str, IM]:
    """The pool grid — every pool, grouped by kind, live counts."""
    profile = await store.get_profile(uid)
    plan = profile["plan"] if profile else "free"
    daily = int(profile["today_count"]) if profile else 0
    await cache.snapshot()
    pools = await cache.pools()
    counts = await cache.pool_counts()
    stock = await cache.stock()
    ep_pools, key_pools = _grouped(pools)

    lines = [
        page_header("Drop vault"),
        G.LINE,
        f"{G.ARR} pick a pool — it drops right on the next message.",
    ]
    if store.plan_limit(plan):
        lines.append(f"{G.DIAM} your tier: {_pl(plan)} · {_lim(plan, daily)} used today")
    else:
        lines.append(f"{G.DIAM} your tier: {_pl(plan)} · no pace, no ceiling")
    lines.append(f"{G.DOTF} totals · accounts {stock['ep']} · keys {stock['key']}")
    if ep_pools:
        lines += ["", f"{G.BOLT} {sc('Accounts · email:pass')}  [{stock['ep']}]"]
        lines += [f"  {G.ARR} {clip(p.label, 18)} — {counts.get(p.category, 0)}" for p in ep_pools]
    if key_pools:
        lines += ["", f"{G.BOLT} {sc('Keys · serial / PC')}  [{stock['key']}]"]
        lines += [f"  {G.ARR} {clip(p.label, 18)} — {counts.get(p.category, 0)}" for p in key_pools]

    kb: list[list[IB]] = []
    kb += _grid_buttons(ep_pools, counts)
    kb += _grid_buttons(key_pools, counts)
    kb.append([IB(f"{G.DOT} Stock", callback_data=CB["STOCK"]),
               IB(f"{G.DOTF} Profile", callback_data=CB["PROFILE"])])
    kb.append([IB("◂ Main", callback_data=CB["HOME"])])
    return "\n".join(lines) + footer(), IM(kb)


def result(res: store.ServeResult, *, owner: bool) -> tuple[str, IM]:
    """The drop card — sent as its OWN message, never edited over."""
    item = res.item or {}
    item_id = item.get("id")
    kind = item.get("kind", EP)
    slug = item.get("category", "")
    label = res.pool_label or STOCK_LABEL[kind]

    lines = [
        page_header("Vault drop"),
        G.LINE,
        f"{G.BOLT} pool: <b>{esc(label)}</b>" + (f" · slot #{item_id}" if item_id is not None else ""),
        f"{G.DOT} kind: {KIND_SHORT.get(kind, kind)}",
        "─" * 18,
    ]
    if kind == EP:
        lines += [
            f"{G.ARR} email   {esc(item.get('email', ''))}",
            f"{G.ARR} pass    {esc(item.get('password', ''))}",
        ]
    else:
        lines += [f"{G.ARR} key     {esc(item.get('key', ''))}"]
    lines += [
        "─" * 18,
        f"{G.DOTF} pulls today: {res.daily}{'/∞' if owner or res.limit is None else '/' + str(res.limit)}",
    ]
    if not owner:
        lines += [
            "",
            f"{G.CHAT} did it work? honest feedback = +1 {G.REP}, skip = −1 {G.REP}.",
            f"{G.NO} dead? report it — the owner pings, nothing vanishes.",
        ]
    else:
        lines += ["", f"{G.BOLT} owner pull — no feedback required."]

    kb: list[list[IB]] = []
    if not owner and slug:
        kb.append(
            [IB("✓ Working", callback_data=f"{CB['FB_WORK']}:{slug}:{item_id}"),
             IB("✗ Dead", callback_data=f"{CB['FB_DEAD']}:{slug}:{item_id}")]
        )
        kb.append([IB(f"{G.SKIP} Skip · −1 {G.REP}", callback_data=f"{CB['FB_SKIP']}:{slug}:{item_id}")])
    kb.append([IB(f"{G.BOLT} Pull again", callback_data=f"{CB['GEN_AGAIN']}{slug}"),
               IB("◂ Main", callback_data=CB["HOME"])])
    return "\n".join(lines) + footer(), IM(kb)


def feedback_verdict(fb: store.FeedbackResult, slug: str) -> tuple[str, IM]:
    """
    The verdict strip appended UNDERNEATH the still-visible credentials of
    a result card: the card text is kept, this line + refreshed buttons are
    added — the drop never disappears on feedback.
    """
    if fb.verdict == "working":
        line = f"{G.OK} working · +1 {G.REP} → {fb.new_rep} {G.REP} · pool: {esc(fb.pool_label)}"
    elif fb.verdict == "dead":
        if fb.removed:
            line = f"{G.NO} dead · slot pulled from {esc(fb.pool_label)} · owner notified"
        elif fb.item is not None:
            line = (
                f"{G.NO} dead · logged for the owner — slot stays in "
                f"{esc(fb.pool_label)} until review"
            )
        else:
            line = f"{G.NO} dead · logged — that slot is no longer in the vault"
    else:
        if fb.rep_delta:
            line = f"{G.SKIP} skipped · {fb.rep_delta} {G.REP} → {fb.new_rep} {G.REP}"
        else:
            line = f"{G.SKIP} skipped"
        if fb.banned:
            line += f"\n{G.LOCK} reputation hit zero — the vault lock engaged."
    kb: list[list[IB]] = [[IB(f"{G.BOLT} Pull again", callback_data=f"{CB['GEN_AGAIN']}{slug}"),
                           IB("◂ Main", callback_data=CB["HOME"])]]
    if fb.banned:
        kb = [[IB(f"{G.MAIL} Contact owner", callback_data=CB["CONTACT"])],
              [IB("◂ Main", callback_data=CB["HOME"])]]
    return "\n" + line, IM(kb)


def feedback_done(fb: store.FeedbackResult, slug: str) -> tuple[str, IM]:
    """Standalone confirmation (used when a card's memory is gone)."""
    lines = [page_header("Feedback logged"), G.LINE]
    if fb.verdict == "working":
        lines += [
            f"{G.OK} marked working — {esc(fb.pool_label) or 'the pool'} heard you.",
            f"{G.PLUS} +1 {G.REP} → reputation {fb.new_rep} {G.REP}",
        ]
    elif fb.verdict == "dead":
        if fb.removed:
            lines.append(f"{G.NO} marked dead — the slot was pulled from the pool.")
        elif fb.item is not None:
            lines.append(f"{G.NO} marked dead — kept in the pool, owner notified to review.")
        else:
            lines.append(f"{G.NO} marked dead — logged; that slot is no longer in the vault.")
        lines.append(f"{G.BOLT} pool: {esc(fb.pool_label) or '—'}")
    else:
        if fb.rep_delta:
            lines.append(f"{G.SKIP} skipped · {fb.rep_delta} {G.REP} → reputation {fb.new_rep} {G.REP}")
        else:
            lines.append(f"{G.SKIP} skipped")
        if fb.banned:
            lines += [
                "",
                f"{G.LOCK} reputation hit zero — the vault lock engaged.",
                f"{G.NO} reason: {esc(fb.ban_reason)}",
            ]
    kb: list[list[IB]] = [
        [IB(f"{G.BOLT} Pull again", callback_data=f"{CB['GEN_AGAIN']}{slug}")],
        [IB("◂ Main", callback_data=CB["HOME"])],
    ]
    if fb.banned:
        kb = [
            [IB(f"{G.MAIL} Contact owner", callback_data=CB["CONTACT"])],
            [IB("◂ Main", callback_data=CB["HOME"])],
        ]
    return "\n".join(lines) + footer(), IM(kb)


def cooldown(res: store.ServeResult) -> tuple[str, IM]:
    mins = res.wait_sec // 60
    secs = res.wait_sec % 60
    clock = f"{mins}m" if mins else f"{secs}s"
    if mins and secs:
        clock += f" {secs}s"
    pool = f" · pool: {esc(res.pool_label)}" if res.pool_label else ""
    lines = [
        page_header("Pace keeper"),
        G.LINE,
        f"{G.BOLT} your tier breathes between pulls{pool}.",
        f"{G.DIAM} next slot opens in ~{clock}.",
        "",
        f"{G.CHAT} want a faster pace? move up a tier — one dm to the owner.",
    ]
    kb = [
        [IB(f"{G.GRID} Other pools", callback_data=CB["VAULT"]),
         IB(f"{G.STAR} Plans", callback_data=CB["PLANS"])],
        [IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def limit_wall(res: store.ServeResult) -> tuple[str, IM]:
    pool = f" · pool: {esc(res.pool_label)}" if res.pool_label else ""
    lines = [
        page_header("Daily wall"),
        G.LINE,
        f"{G.LOCK} you used {res.daily}/{res.limit} pulls today — the day resets at midnight.",
        f"{G.ARR} this wall is for {res.plan} — it covers every pool equally{pool}.",
        "",
        f"{G.CHAT} bigger tiers lift the ceiling instantly. dm the owner to upgrade.",
    ]
    kb = [
        [IB(f"{G.MAIL} Contact owner", callback_data=CB["CONTACT"])],
        [IB(f"{G.STAR} Plans", callback_data=CB["PLANS"]),
         IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def empty(pool: Pool | None) -> tuple[str, IM]:
    label = pool.label if pool else "this pool"
    lines = [
        page_header("Pool drained"),
        G.LINE,
        f"{G.WARN} {esc(label)} is dry for this moment — restock lands soon.",
        f"{G.NO} pools never borrow from each other — no silent fallback.",
        f"{G.ARR} meanwhile: another pool, or order a private slot.",
    ]
    kb = [
        [IB(f"{G.GRID} Pick another pool", callback_data=CB["VAULT"])],
        [IB(f"{G.MAIL} Private slot", callback_data=CB["CONTACT"])],
        [IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def banned_page(reason: str | None) -> tuple[str, IM]:
    lines = [
        page_header("Account locked"),
        G.LINE,
        f"{G.LOCK} this slot was locked by the vault.",
        f"{G.NO} reason: {esc(reason or 'no reason given')}",
        "",
        f"{G.MAIL} disputes go straight to the owner — one message.",
    ]
    kb = [
        [IB(f"{G.MAIL} Contact owner", callback_data=CB["CONTACT"])],
        [IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


async def profile_page(uid: int) -> tuple[str, IM]:
    user = await store.get_profile(uid)
    owner = store.is_owner(uid)
    if user is None:
        return await home(uid)
    plan = user["plan"] or "free"
    daily = int(user["today_count"])
    status = "active" if not user["is_banned"] else "banned"
    extra = f" · {esc(user['ban_reason'])}" if user["is_banned"] and user["ban_reason"] else ""
    lines = [
        page_header("Profile"),
        G.LINE,
        f"{G.DIAM} id       {user['user_id']}",
        f"{G.ARR} handle   @{esc(user['username'] or '—')}",
        f"{G.ARR} name     {esc(user['first_name'] or '—')}",
        "",
        f"{G.DOTF} plan     {_pl(plan)}",
        f"{G.REP} rep      {user['reputation']} {G.REP}",
        f"{G.BOLT} today    {_lim(plan, daily)} pulls" + ("" if store.plan_limit(plan) else " · ∞ tier"),
        f"{G.DIAM} total    {user['total_gens']} pulls",
        f"{G.DOT} status   {status}{extra}",
        f"{G.STAR} member   {user['joined_at'].strftime('%d %b %Y') if user['joined_at'] else '—'}",
    ]
    kb = [
        [IB(f"{G.GRID} Drop vault", callback_data=CB["VAULT"]),
         IB(f"{G.STAR} Plans", callback_data=CB["PLANS"])],
        [IB("◂ Main", callback_data=CB["HOME"])],
    ]
    if owner:
        kb.append([IB(f"{G.BOLT} Owner core", callback_data=CB["OWN_PANEL"])])
    return "\n".join(lines) + footer(), IM(kb)


async def stock_page(force: bool = False) -> tuple[str, IM]:
    """Live stock — broken down PER POOL, never mixed."""
    if force:
        cache.pools_invalidate()
    await cache.snapshot()
    pools = await cache.pools()
    counts = await cache.pool_counts()
    stock = await cache.stock()
    total_users = await cache.users()
    ep_pools, key_pools = _grouped(pools)

    lines = [
        page_header("Drop status"),
        G.LINE,
        f"{G.DOTF} members      {total_users}",
        f"{G.BOLT} system       online · relay smooth",
        "",
        f"{G.BOLT} {sc('Accounts')} · {stock['ep']} live · {len(ep_pools)} pools",
    ]
    for p in ep_pools:
        lines.append(f"  {G.DIAM} {clip(p.label, 20):<20} {counts.get(p.category, 0)}")
    lines.append(f"{G.BOLT} {sc('Keys')} · {stock['key']} live · {len(key_pools)} pools")
    for p in key_pools:
        lines.append(f"  {G.DIAM} {clip(p.label, 20):<20} {counts.get(p.category, 0)}")
    kb = [
        [IB(f"{G.GRID} Pick a pool", callback_data=CB["VAULT"]),
         IB(f"{G.LOOP} Refresh", callback_data=CB["STOCK_FORCE"])],
        [IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


async def plans_page(uid: int) -> tuple[str, IM]:
    user = await store.get_user(uid)
    current = user["plan"] if user else "free"
    lines = [
        page_header("Tiers"),
        G.LINE,
        f"{G.CHAT} pick a tier — every upgrade & private order runs through the owner.",
    ]
    for plan in config.PLAN_ORDER:
        limit = store.plan_limit(plan)
        cooldown_min = store.plan_cooldown_minutes(plan)
        pace = "no cooldown" if not cooldown_min else f"1 per {cooldown_min} min"
        ceiling = "unlimited" if limit is None else f"{limit} pulls/day"
        tag = f"{G.DOTF} yours now" if plan == current else ""
        lines.append(f"{_pl(plan)} {tag}")
        lines.append(f"      {G.ARR} {ceiling} · {pace}")
    lines += [
        "",
        f"{G.STAR} limits & pace apply across every pool — no pool hopping.",
        f"{G.STAR} private accounts & custom keys are arranged 1:1 — dm the owner.",
    ]
    kb: list[list[IB]] = []
    for plan in config.PLAN_ORDER:
        kb.append([IB(f"▸ {config.PLAN_TITLE[plan]}", callback_data=f"{CB['PLAN_DETAIL']}{plan}")])
    kb.append([IB(f"{G.MAIL} DM owner", url=_url_owner())])
    kb.append([IB("◂ Main", callback_data=CB["HOME"])])
    return "\n".join(lines) + footer(), IM(kb)


def plan_detail_page(plan: str, uid: int) -> tuple[str, IM]:
    limit = store.plan_limit(plan)
    cooldown_min = store.plan_cooldown_minutes(plan)
    pace = "no cooldown — instant pulls" if not cooldown_min else f"1 pull every {cooldown_min} min"
    ceiling = "no daily ceiling" if limit is None else f"{limit} pulls every day"
    lines = [
        page_header(f"Tier · {config.PLAN_TITLE.get(plan, plan)}"),
        G.LINE,
        f"{G.DIAM} {sc(config.PLAN_TAG.get(plan, ''))}",
        f"{G.ARR} {ceiling}",
        f"{G.ARR} {pace}",
        f"{G.ARR} access: every vault pool — accounts & keys",
        f"{G.ARR} support: owner line, direct",
        "",
        f"{G.CHAT} to activate, dm the owner and say: <i>plan {esc(plan.upper())}</i> — "
        f"your user id is <b>{uid}</b> if asked.",
    ]
    kb = [
        [IB(f"{G.MAIL} DM owner", url=_url_owner())],
        [IB(f"{G.STAR} All tiers", callback_data=CB["PLANS"]),
         IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def contact_page(uid: int) -> tuple[str, IM]:
    lines = [
        page_header("Contact & private"),
        G.LINE,
        f"{G.DOTF} owner      @{config.OWNER_USERNAME}",
        f"{G.ARR} private accounts & custom keys — drop a message at the owner,",
        f"{G.ARR} upgrades · reseller · bulk · business — same line.",
        f"{G.ARR} your user id: {uid}",
        "",
        f"{G.WARN} state your purpose in one line. no hi/hello — the owner filters spam,",
        f"{G.NO} so real messages get answered first.",
    ]
    kb = [
        [IB(f"{G.MAIL} DM owner", url=_url_owner())],
        [IB(f"{G.WRITE} Write a message", callback_data=CB["MSG_WRITE"])],
        [IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def text_mode_prompt(kind: str) -> tuple[str, IM]:
    if kind == MODE["WRITE_MSG"]:
        text = (
            f"{G.WRITE} write to the owner\n"
            f"{G.LINE_S}\n"
            "type your message below — it lands in the owner's inbox, "
            "read-first order. include what you want (plan, private slot, issue)."
        )
    elif kind == MODE["HIT_REPORT"]:
        text = (
            f"{G.CHAT} hit report\n"
            f"{G.LINE_S}\n"
            "tell us how the drop behaved, e.g.:\n"
            f"{G.ARR} email:pass — logged in fine, streams ok\n"
            f"{G.ARR} pc key — activated, all good"
        )
    elif kind == MODE["SEARCH_USER"]:
        text = (
            f"{G.CHAT} find user\n"
            f"{G.LINE_S}\n"
            "send the numeric user id (or a @username) and their card opens."
        )
    elif kind == MODE["BROADCAST"]:
        text = (
            f"{G.BOLT} broadcast\n"
            f"{G.LINE_S}\n"
            "type one message — it is delivered to every member of the vault. "
            "you will get a receipt when it finishes."
        )
    elif kind == MODE["RESET_CONFIRM"]:
        return reset_confirm()
    else:  # pragma: no cover
        text = "paste your input."
    kb = [[IB("✕ Cancel", callback_data=CB["CANCEL_MODE"])]]
    return text + footer(), IM(kb)


# ── owner pool prompts (vault manager flows) ───────────────────
def pool_prompt_add(pool: Pool) -> tuple[str, IM]:
    fmt = "email@x.com:password" if pool.kind == EP else "XXXX-XXXX-XXXX"
    text = (
        f"{G.PLUS} add to pool  {esc(pool.label)}\n"
        f"{G.LINE_S}\n"
        f"one entry per line —  {fmt}\n"
        "duplicates are skipped. rows land ONLY in this pool."
    )
    kb = [[IB("✕ Cancel", callback_data=CB["CANCEL_MODE"])]]
    return text + footer(), IM(kb)


def pool_prompt_remove(pool: Pool) -> tuple[str, IM]:
    text = (
        f"{G.NO} remove by id  ·  {esc(pool.label)}\n"
        f"{G.LINE_S}\n"
        "send the numeric item id (the 'slot #' shown on drop cards).\n"
        f"it is deleted from THIS pool only, served-history included."
    )
    kb = [[IB("✕ Cancel", callback_data=CB["CANCEL_MODE"])]]
    return text + footer(), IM(kb)


def pool_prompt_reset(pool: Pool) -> tuple[str, IM]:
    text = (
        f"{G.WARN} reset pool  ·  {esc(pool.label)}\n"
        f"{G.LINE_S}\n"
        f"this wipes {KIND_SHORT.get(pool.kind, pool.kind)} entries of this single pool\n"
        "and its serve history. other pools are untouched.\n"
        f"{G.DIAM} type the exact word to confirm: <b>WIPE</b>"
    )
    kb = [[IB("✕ Cancel", callback_data=CB["CANCEL_MODE"])]]
    return text + footer(), IM(kb)


def pool_prompt_new() -> tuple[str, IM]:
    text = (
        f"{G.PLUS} new pool\n"
        f"{G.LINE_S}\n"
        "send the pool name (any brand / service), e.g.:\n"
        f"{G.ARR} Disney+   {G.ARR} Epic Games   {G.ARR} Mullvad\n"
        "letters & digits become the slug — duplicates are refused."
    )
    kb = [[IB("✕ Cancel", callback_data=CB["CANCEL_MODE"])]]
    return text + footer(), IM(kb)


def pool_pick_kind(name: str, slug_hint: str) -> tuple[str, IM]:
    text = (
        f"{G.DIAM} pool  <b>{esc(name)}</b>\n"
        f"{G.LINE_S}\n"
        f"slug: <code>{esc(slug_hint)}</code> — now choose what lives in it:"
    )
    kb = [
        [IB(f"{G.BOLT} Accounts (email:pass)", callback_data=f"{CB['OWN_NEW_POOL_KIND']}{EP}")],
        [IB(f"{G.BOLT} PC & Software Keys", callback_data=f"{CB['OWN_NEW_POOL_KIND']}{KEY}")],
        [IB("✕ Cancel", callback_data=CB["CANCEL_MODE"])],
    ]
    return text + footer(), IM(kb)


def message_sent(kind: str) -> tuple[str, IM]:
    if kind == "contact":
        lines = [f"{G.OK} delivered — the owner reads the inbox first-come.",
                 f"{G.BOLT} want it faster? dm directly and mention your user id."]
    else:
        lines = [f"{G.OK} report filed — thank you, it keeps the vault sharp.",
                 f"{G.BOLT} dead drops are flagged for owner review — nothing vanishes."]
    kb = [[IB("◂ Main", callback_data=CB["HOME"])]]
    return "\n".join([page_header("Sent"), G.LINE, *lines]) + footer(), IM(kb)


async def help_page() -> tuple[str, IM]:
    await cache.snapshot()
    pools = await cache.pools()
    lines = [
        page_header("Help"),
        G.LINE,
        f"{G.ARR} everything runs from the menu — one tap swaps the screen, nothing spams.",
        f"{G.ARR} the vault is split into {len(pools)} pools — one per brand. your pull",
        f"{G.ARR} comes from ONE pool only; pools never mix or back each other up.",
        f"{G.ARR} quick keys that still work:",
        "     /gen · /plans · /profile · /status · /contact · /hits · /help",
        "",
        f"{G.CHAT} tip: after a drop, tell us if it worked — you earn {G.REP} rep, ",
        f"{G.NO} dead? report it: the owner reviews it (the item is kept, not deleted).",
    ]
    kb = [
        [IB(f"{G.GRID} Open vault · {len(pools)} pools", callback_data=CB["VAULT"]),
         IB(f"{G.DOT} Stock", callback_data=CB["STOCK"])],
        [IB(f"{G.DOTF} Profile", callback_data=CB["PROFILE"]),
         IB(f"{G.STAR} Plans", callback_data=CB["PLANS"])],
        [IB(f"{G.MAIL} Contact", callback_data=CB["CONTACT"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


# ────────────────────────────────────────────────────────────────
#  OWNER SPACE  (never rendered for anyone else)
# ────────────────────────────────────────────────────────────────
async def owner_panel() -> tuple[str, IM]:
    s = await store.dashboard_stats()
    unread = await store.mailbox_unread_counts()
    await cache.snapshot()
    pools = await cache.pools()
    plan_split = " · ".join(f"{_pl(p).strip()} {s['plans'].get(p, 0)}" for p in config.PLAN_ORDER)
    lines = [
        page_header("Owner core"),
        G.LINE,
        f"{G.DIAM} users      {s['users']}   ({s['banned']} banned)",
        f"{G.DIAM} today      {s['serves_today']} pulls · {s['active_today']} active",
        f"{G.DIAM} all-time   {s['serves_total']} pulls",
        f"{G.DIAM} stock      ep {s['ep']} · keys {s['keys']}",
        f"{G.DIAM} pools      {len(pools)} · live per pool, never mixed",
        f"{G.DIAM} verdicts   {G.OK} {s['working_reports']} · {G.NO} {s['dead_reports']} "
        f"· dead kept{'' if config.AUTO_REMOVE_DEAD else ' (auto-remove off)'}",
        f"{G.DIAM} plan mix   {plan_split}",
    ]
    kb = [
        [IB(f"{G.GRID} Vault manager · {len(pools)} pools", callback_data=f"{CB['OWN_VAULT_MGR']}1")],
        [IB(f"{G.CHAT} Users · {s['users']}", callback_data=f"{CB['OWN_USER_PAGE']}1"),
         IB(f"{G.LOCK} Banned · {s['banned']}", callback_data=CB["OWN_BANNED"])],
        [IB(f"{G.MAIL} Messages · {unread['contact']}", callback_data=f"{CB['OWN_INBOX']}contact:0"),
         IB(f"{G.CHAT} Hits · {unread['hit']}", callback_data=f"{CB['OWN_INBOX']}hit:0")],
        [IB(f"{G.BOLT} Broadcast", callback_data=CB["OWN_BROADCAST"]),
         IB(f"{G.LOOP} Activity log", callback_data=CB["OWN_LOGS"])],
        [IB("⇩ Export all", callback_data=CB["OWN_EXPORT"]),
         IB(f"{G.NO} Reset all", callback_data=CB["OWN_RESET"])],
        [IB(f"{G.LOOP} Refresh", callback_data=CB["OWN_STATS"]),
         IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


# ── vault manager ──────────────────────────────────────────────
MANAGER_PER_PAGE = 8


async def owner_vault_manager(page: int = 1) -> tuple[str, IM]:
    """Every pool as a row + its four per-pool actions, paginated."""
    await cache.snapshot()
    pools = await cache.pools()
    counts = await cache.pool_counts()
    pages = max(1, -(-len(pools) // MANAGER_PER_PAGE))
    page = max(1, min(page, pages))
    window = pools[(page - 1) * MANAGER_PER_PAGE : page * MANAGER_PER_PAGE]

    lines = [
        page_header(f"Vault manager · p{page}/{pages}"),
        G.LINE,
        f"{G.ARR} one pool per brand — add / export / remove / reset are per pool.",
        f"{G.ARR} new pools need NO code — they appear everywhere instantly.",
        "",
    ]
    kb: list[list[IB]] = [
        [IB(f"{G.PLUS} New pool", callback_data=CB["OWN_NEW_POOL"])],
    ]
    if not pools:
        lines.append(f"{G.WARN} no pools yet — create the first one.")
    for p in window:
        n = counts.get(p.category, 0)
        lines.append(f"{G.DIAM} {clip(p.label, 20)}  ·  {KIND_SHORT.get(p.kind, p.kind)}  ·  {n} live")
        kb.append([
            IB("＋", callback_data=f"{CB['OWN_POOL_ADD']}{p.category}"),
            IB("⇩", callback_data=f"{CB['OWN_POOL_EXPORT']}{p.category}"),
            IB("✕", callback_data=f"{CB['OWN_POOL_REMOVE']}{p.category}"),
            IB("⚠", callback_data=f"{CB['OWN_POOL_RESET']}{p.category}"),
        ])
    lines += [
        "",
        f"{G.DOT} row buttons:  ＋ add  ·  ⇩ export  ·  ✕ remove by id  ·  ⚠ reset (WIPE)",
    ]
    nav: list[IB] = []
    if page > 1:
        nav.append(IB("◂", callback_data=f"{CB['OWN_VAULT_MGR']}{page - 1}"))
    nav.append(IB(f"{page}/{pages}", callback_data=CB["OWN_STATS"]))
    if page < pages:
        nav.append(IB("▸", callback_data=f"{CB['OWN_VAULT_MGR']}{page + 1}"))
    kb.append(nav)
    kb.append([IB("◂ Panel", callback_data=CB["OWN_PANEL"])])
    return "\n".join(lines) + footer(), IM(kb)


def owner_add_done(pool: Pool, added: int, failed: int) -> tuple[str, IM]:
    lines = [
        page_header("Stock updated"),
        G.LINE,
        f"{G.OK} added {added} · skipped {failed}",
        f"{G.DIAM} pool: {esc(pool.label)} — nothing else was touched",
    ]
    kb = [
        [IB("＋ Add more", callback_data=f"{CB['OWN_POOL_ADD']}{pool.category}"),
         IB("⇩ Export pool", callback_data=f"{CB['OWN_POOL_EXPORT']}{pool.category}")],
        [IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1"),
         IB("◂ Panel", callback_data=CB["OWN_PANEL"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def owner_removed(pool: Pool, row: dict) -> tuple[str, IM]:
    if pool.kind == EP:
        val = f"{row.get('email')}:{row.get('password')}"
    else:
        val = str(row.get("key", ""))
    lines = [
        page_header("Slot removed"),
        G.LINE,
        f"{G.OK} id {row.get('id')} gone from {esc(pool.label)}",
        f"{G.ARR} served-history reference cleared too",
        "─" * 18,
        f"    {esc(val)}",
    ]
    kb = [
        [IB("✕ Remove another", callback_data=f"{CB['OWN_POOL_REMOVE']}{pool.category}")],
        [IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1"),
         IB("◂ Panel", callback_data=CB["OWN_PANEL"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def owner_reset_done(pool: Pool, wiped: int, aborted: bool) -> tuple[str, IM]:
    if aborted:
        lines = [
            page_header("Reset aborted"),
            G.LINE,
            f"{G.OK} nothing was touched — the word must be exactly WIPE.",
            f"{G.DIAM} pool {esc(pool.label)} still holds {wiped} slots.",
        ]
    else:
        lines = [
            page_header("Pool reset"),
            G.LINE,
            f"{G.OK} {esc(pool.label)} wiped — {wiped} slots + serve history gone.",
            f"{G.NO} every other pool is untouched.",
        ]
    kb = [[IB("◂ Manager", callback_data=f"{CB['OWN_VAULT_MGR']}1"),
           IB("◂ Panel", callback_data=CB["OWN_PANEL"])]]
    return "\n".join(lines) + footer(), IM(kb)


async def owner_users(page: int) -> tuple[str, IM]:
    total = await store.user_count()
    size = config.USERS_PER_PAGE
    pages = max(1, -(-total // size))
    page = max(1, min(page, pages))
    users = await store.users_page(page, size)

    kb: list[list[IB]] = []
    if not users:
        lines = [page_header("Users"), G.LINE, f"{G.WARN} vault is empty — no members yet."]
    else:
        lines = [
            page_header(f"Users · p{page}/{pages}"),
            G.LINE,
            f"{G.ARR} stats on the row — tap the name to open the manage card.",
        ]
        for i, u in enumerate(users, start=1):
            lim = store.plan_limit(u["plan"])
            today = f"{u['today_count']}/{lim}" if lim else f"{u['today_count']}/∞"
            flag = f"{G.NO} banned" if u["is_banned"] else "ok"
            handle = f"@{u['username']}" if u["username"] else "—"
            lines.append(
                f"{i}. {esc(u['first_name'] or '—')}  <code>{u['user_id']}</code>  {esc(handle)}"
            )
            lines.append(
                f"    {_pl(u['plan'])} · {u['reputation']} {G.REP} · today {today} · {flag}"
            )
            kb.append([IB(f"{G.CHAT} manage · {clip(u['first_name'] or u['username'] or str(u['user_id']), 14)}",
                         callback_data=f"{CB['OWN_MANAGE']}{u['user_id']}")])
    nav: list[IB] = []
    if page > 1:
        nav.append(IB("◂ Prev", callback_data=f"{CB['OWN_USER_PAGE']}{page - 1}"))
    nav.append(IB(f"{page}/{pages}", callback_data=CB["OWN_STATS"]))
    if page < pages:
        nav.append(IB("Next ▸", callback_data=f"{CB['OWN_USER_PAGE']}{page + 1}"))
    kb.append(nav)
    kb.append([IB(f"{G.WRITE} Search by id", callback_data=CB["OWN_SEARCH"]),
               IB(f"{G.LOCK} Banned", callback_data=CB["OWN_BANNED"])])
    kb.append([IB("◂ Panel", callback_data=CB["OWN_PANEL"])])
    return "\n".join(lines) + footer(), IM(kb)


async def owner_manage(uid: int) -> tuple[str, IM]:
    user = await store.get_profile(uid)
    if user is None:
        return await owner_users(1)
    lim = store.plan_limit(user["plan"])
    today = f"{user['today_count']}/{lim}" if lim else f"{user['today_count']}/∞"
    status = "banned" if user["is_banned"] else "active"
    reason = f"\n{G.NO} reason: {esc(user['ban_reason'])}" if user["is_banned"] and user["ban_reason"] else ""
    lines = [
        page_header("Manage user"),
        G.LINE,
        f"{G.DIAM} id       {user['user_id']}",
        f"{G.ARR} handle   @{esc(user['username'] or '—')}",
        f"{G.ARR} name     {esc(user['first_name'] or '—')}",
        f"{G.DOTF} plan     {_pl(user['plan'])}",
        f"{G.REP} rep      {user['reputation']} {G.REP}",
        f"{G.BOLT} today    {today} pulls",
        f"{G.DIAM} total    {user['total_gens']} pulls",
        f"{G.DOT} status   {status}{reason}",
    ]
    kb: list[list[IB]] = [
        [IB("−3 rep", callback_data=f"{CB['OWN_REP']}{uid}:-3"),
         IB("+3 rep", callback_data=f"{CB['OWN_REP']}{uid}:3")],
        [
            IB("Free", callback_data=f"{CB['OWN_PLAN']}{uid}:free"),
            IB("Pro", callback_data=f"{CB['OWN_PLAN']}{uid}:pro"),
            IB("Elite", callback_data=f"{CB['OWN_PLAN']}{uid}:elite"),
            IB("∞", callback_data=f"{CB['OWN_PLAN']}{uid}:unlimited"),
        ],
    ]
    if user["is_banned"]:
        kb.append([IB(f"{G.OK} Unban", callback_data=f"{CB['OWN_BAN']}{uid}:0")])
    else:
        kb.append([IB(f"{G.NO} Ban", callback_data=f"{CB['OWN_BAN']}{uid}:1")])
    kb.append([IB(f"{G.LOOP} Refresh", callback_data=f"{CB['OWN_MANAGE']}{uid}"),
               IB("◂ Users", callback_data=f"{CB['OWN_USER_PAGE']}1")])
    return "\n".join(lines) + footer(), IM(kb)


async def owner_banned() -> tuple[str, IM]:
    rows = await store.banned_users()
    kb: list[list[IB]] = []
    if not rows:
        lines = [page_header("Banned"), G.LINE, f"{G.OK} nobody is locked."]
    else:
        lines = [
            page_header(f"Banned · {len(rows)}"),
            G.LINE,
            f"{G.ARR} tap a row to open & lift:",
        ]
        for u in rows:
            lines.append(
                f"{G.NO} <code>{u['user_id']}</code>  @{esc(u['username'] or '—')} — "
                f"{esc(u['ban_reason'] or 'no reason')}"
            )
            kb.append([IB(f"{G.CHAT} manage · {clip(u['first_name'] or u['username'] or str(u['user_id']), 14)}",
                         callback_data=f"{CB['OWN_MANAGE']}{u['user_id']}")])
    kb.append([IB(f"{G.WRITE} Search by id", callback_data=CB["OWN_SEARCH"])])
    kb.append([IB("◂ Users", callback_data=f"{CB['OWN_USER_PAGE']}1"),
               IB("◂ Panel", callback_data=CB["OWN_PANEL"])])
    return "\n".join(lines) + footer(), IM(kb)


async def owner_logs() -> tuple[str, IM]:
    rows = await store.feedback_log(12)
    if not rows:
        lines = [page_header("Activity log"), G.LINE, f"{G.OK} no verdicts yet — the pool is quiet."]
    else:
        lines = [page_header("Activity log · last 12"), G.LINE]
        for r in rows:
            stamp = r["feedback_at"].strftime("%d %b %H:%M") if r["feedback_at"] else "—"
            lines.append(
                f"{VERDICT_BADGE.get(r['feedback_type'], r['feedback_type'])} "
                f"{r['item_type']}#{r['item_id']} · @{esc(r['username'] or '—')} · {stamp}"
            )
    kb = [[IB(f"{G.LOOP} Refresh", callback_data=CB["OWN_LOGS"]),
           IB("◂ Panel", callback_data=CB["OWN_PANEL"])]]
    return "\n".join(lines) + footer(), IM(kb)


async def owner_inbox(kind: str, index: int) -> tuple[str, IM]:
    rows = await store.mailbox_unread(kind, limit=15)
    total_unread = await store.mailbox_unread_counts()
    label = "Messages" if kind == "contact" else "Hit reports"
    count = total_unread["contact" if kind == "contact" else "hit"]
    if not rows:
        lines = [
            page_header(f"{label} · inbox"),
            G.LINE,
            f"{G.OK} inbox clear — nothing unread.",
        ]
        kb = [[IB("◂ Panel", callback_data=CB["OWN_PANEL"])]]
        return "\n".join(lines) + footer(), IM(kb)

    idx = max(0, min(index, len(rows) - 1))
    row = rows[idx]
    content = str(row["content"])
    clipped = content if len(content) <= 420 else content[:420] + " …"
    stamp = row["sent_at"].strftime("%d %b %H:%M") if row["sent_at"] else "—"
    handle = f"@{row['username']}" if row["username"] else ""
    lines = [
        page_header(f"{label} · {count} unread"),
        G.LINE,
        f"#{row['id']} · {esc(handle or row['user_id'])} · id <code>{row['user_id']}</code> · {stamp}",
        "─" * 18,
        esc(clipped),
    ]
    kb: list[list[IB]] = [
        [IB("✓ Read", callback_data=f"{CB['OWN_INBOX_READ']}{kind}:{row['id']}"),
         IB("✕ Delete", callback_data=f"{CB['OWN_INBOX_DEL']}{kind}:{row['id']}")],
    ]
    if row["username"]:
        kb.append([IB(f"{G.MAIL} Open chat", url=f"https://t.me/{row['username']}")])
    kb.append(
        [
            IB("◂ Prev", callback_data=f"{CB['OWN_INBOX']}{kind}:{idx - 1 if idx > 0 else len(rows) - 1}"),
            IB(f"{idx + 1}/{len(rows)}", callback_data=CB["OWN_STATS"]),
            IB("Next ▸", callback_data=f"{CB['OWN_INBOX']}{kind}:{(idx + 1) % len(rows)}"),
        ]
    )
    kb.append([IB(f"{G.OK} Mark all read", callback_data=f"{CB['OWN_INBOX_READALL']}{kind}"),
               IB("◂ Panel", callback_data=CB["OWN_PANEL"])])
    return "\n".join(lines) + footer(), IM(kb)


def reset_confirm() -> tuple[str, IM]:
    lines = [
        page_header("Reset all pools"),
        G.LINE,
        f"{G.WARN} this wipes every email:pass, every key and the serve history",
        f"{G.WARN} across ALL pools — per-pool reset lives in the vault manager.",
        f"{G.NO} users could receive old drops again after the next refill.",
        "",
        f"{G.DIAM} type the exact word to confirm: <b>WIPE</b>",
    ]
    kb = [[IB("✕ Cancel", callback_data=CB["OWN_RESET_NO"])]]
    return "\n".join(lines) + footer(), IM(kb)


# ── /admin · silent owner manual (paged) ───────────────────────
ADMIN_PAGE_SIZE = 4

ADMIN_ENTRIES: list[tuple[str, str, str]] = [
    ("/panel",
     "open the owner core hub — all tools live from here.",
     "/panel"),
    ("/users <page>",
     "paged member list (10/page), stats + tappable rows.",
     "/users 2"),
    ("/manage <id | @user>",
     "open one member's manage card (plan / rep / ban).",
     "/manage 772842 or /manage @someuser"),
    ("/export",
     "download every pool's stock as a .txt, sectioned per pool.",
     "/export"),
    ("/admin",
     "this manual — every owner tool, paged with ◂ ▸.",
     "/admin · /admin pages stay in sync with the panel"),
    ("Owner Core · Vault manager",
     "every pool as a row: ＋ add · ⇩ export · ✕ remove by id · ⚠ reset — per pool only, pools never mix.",
     "tap ⇩ next to NordVPN to export just that pool"),
    ("Owner Core · ＋ New pool",
     "name it (inline prompt), pick the kind (accounts / keys) — no code change, appears everywhere instantly.",
     "send 'Disney+' → Accounts → pool live in home chips + grid"),
    ("Owner Core · Users / Banned",
     "paged lists; every row (also banned rows) is tappable → opens that user's manage card.",
     "Users → tap a name → set plan, ±3 rep, ban"),
    ("Owner Core · Search",
     "find any member by numeric id or @username and their card opens.",
     "Search by id → send 555123"),
    ("Owner Core · Manage card",
     "one-tap plans (Free/Pro/Elite/∞), ±3 rep, Ban/Unban — owner itself can never be locked.",
     "tap ∞ to lift every daily wall for a user"),
    ("Owner Core · Messages / Hits",
     "inboxes with ✓ Read · ✕ Delete · Mark all read · ◂ ▸ paging.",
     "Hits → ✓ Read marks the report seen without deleting"),
    ("Owner Core · Broadcast",
     "type one message → background job with flood-guard → receipt.",
     "Broadcast → 'new stock dropped' → every member notified"),
    ("Owner Core · Activity log",
     "last 12 verdicts (working / dead / skip) across pools.",
     "tap ⟳ Refresh to re-pull"),
    ("Owner Core · Export all / Reset all",
     "full stock file out; global reset needs the word WIPE — per-pool reset is in the manager.",
     "type WIPE only on the reset prompt you meant to land on"),
    ("Owner Core · Refresh",
     "re-render every cached number on the panel instantly.",
     "tap it after bulk adds land"),
    ("Dead feedback policy",
     "a user's ✗ Dead never deletes the row (owner pings, item stays for review). "
     "env BOT_AUTO_REMOVE_DEAD=1 restores auto-pull.",
     "keep it OFF — you decide what leaves a pool"),
]


def owner_admin(page: int = 1) -> tuple[str, IM]:
    pages = max(1, -(-len(ADMIN_ENTRIES) // ADMIN_PAGE_SIZE))
    page = max(1, min(page, pages))
    window = ADMIN_ENTRIES[(page - 1) * ADMIN_PAGE_SIZE : page * ADMIN_PAGE_SIZE]
    lines = [
        page_header(f"Owner manual · p{page}/{pages}"),
        G.LINE,
        f"{G.ARR} silent owner-only — never in /help, invisible to members.",
    ]
    for title, how, example in window:
        lines += [
            "",
            f"{G.BOLT} <b>{sc(title)}</b>",
            f"{G.ARR} {how}",
            f"{G.DOT} e.g.  <code>{esc(example)}</code>",
        ]
    nav: list[IB] = []
    if page > 1:
        nav.append(IB("◂ Prev", callback_data=f"{CB['OWN_ADMIN']}{page - 1}"))
    nav.append(IB(f"{page}/{pages}", callback_data=CB["OWN_STATS"]))
    if page < pages:
        nav.append(IB("Next ▸", callback_data=f"{CB['OWN_ADMIN']}{page + 1}"))
    kb = [nav, [IB(f"{G.BOLT} Panel", callback_data=CB["OWN_PANEL"]),
                IB("◂ Main", callback_data=CB["HOME"])]]
    return "\n".join(lines) + footer(), IM(kb)
