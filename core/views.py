"""
Vɪᴇᴡꜱ ────────
Every screen the bot can render, as (text, reply_markup) pairs.
Nothing here talks to Telegram; handlers fetch a tiny bit of state,
call these builders and hand the result to core.messaging.
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

# ────────────────────────────────────────────────────────────────
#  tiny helpers
# ────────────────────────────────────────────────────────────────
def _pl(plan: str) -> str:
    return f"{config.PLAN_BADGE.get(plan, G.DIAM)} {sc(config.PLAN_TITLE.get(plan, plan))}"


def _count_suffix(kind: str, stock: dict[str, int]) -> str:
    if not config.SHOW_STOCK_ON_BUTTONS:
        return ""
    return f"  [{stock.get(kind, 0)}]"


def _lim(plan: str, daily: int) -> str:
    limit = store.plan_limit(plan)
    return f"{daily}/{limit}" if limit is not None else f"{daily}/∞"


def _btn(text: str, data: str) -> list[IB]:
    return [IB(text=text, callback_data=data)]


def _url_owner() -> str:
    return f"https://t.me/{config.OWNER_USERNAME}"


# ────────────────────────────────────────────────────────────────
#  USER SPACE
# ────────────────────────────────────────────────────────────────
async def home(uid: int) -> tuple[str, IM]:
    owner = store.is_owner(uid)
    profile = await store.get_profile(uid)
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
        f"{G.ARR} email:pass accounts & pc keys — straight from the live vault.",
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
        f"{G.CHAT} vault live now · {total_users} members · "
        f"ep {stock['ep']} · keys {stock['key']}",
    ]

    kb: list[list[IB]] = [
        [IB(f"{G.BOLT} {STOCK_LABEL[EP]}{_count_suffix(EP, stock)}", callback_data=CB["GEN_EP"])],
        [IB(f"{G.BOLT} {STOCK_LABEL[KEY]}{_count_suffix(KEY, stock)}", callback_data=CB["GEN_KEY"])],
        [IB(f"{G.DOT} Stock", callback_data=CB["STOCK"]),
         IB(f"{G.DOTF} Profile", callback_data=CB["PROFILE"])],
        [IB(f"{G.STAR} Plans", callback_data=CB["PLANS"]),
         IB(f"{G.MAIL} Contact", callback_data=CB["CONTACT"])],
    ]
    if owner:
        kb.append([IB(f"{G.BOLT} Owner core", callback_data=CB["OWN_PANEL"])])
    return "\n".join(lines) + footer(), IM(kb)


async def vault(uid: int) -> tuple[str, IM]:
    profile = await store.get_profile(uid)
    plan = profile["plan"] if profile else "free"
    daily = int(profile["today_count"]) if profile else 0
    stock = await cache.stock()
    cooldown = store.plan_cooldown_minutes(plan)

    lines = [
        page_header("Drop vault"),
        G.LINE,
        f"{G.ARR} pick a pool — it drops right on this screen.",
    ]
    if store.plan_limit(plan):
        lines.append(f"{G.DIAM} your tier: {_pl(plan)} · {_lim(plan, daily)} used today")
        if cooldown:
            lines.append(f"{G.BOLT} pace: 1 pull every {cooldown} min")
    else:
        lines.append(f"{G.DIAM} your tier: {_pl(plan)} · no pace, no ceiling")
    kb: list[list[IB]] = [
        [IB(f"{G.BOLT} Email:Pass{_count_suffix(EP, stock)}", callback_data=CB["GEN_EP"])],
        [IB(f"{G.BOLT} PC Key{_count_suffix(KEY, stock)}", callback_data=CB["GEN_KEY"])],
        [IB(f"{G.DOT} Stock", callback_data=CB["STOCK"]),
         IB(f"{G.DOTF} Profile", callback_data=CB["PROFILE"])],
        [IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def result(res: store.ServeResult, *, owner: bool) -> tuple[str, IM]:
    item = res.item or {}
    item_id = item.get("id")
    kind = item.get("kind", EP)
    label = STOCK_LABEL[kind]

    lines = [
        page_header("Vault drop"),
        G.LINE,
        f"{G.BOLT} {label} · slot #{item_id}" if item_id is not None else f"{G.BOLT} {label}",
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
            f"{G.CHAT} did it work? your call keeps the vault clean. "
            f"honest feedback = +1 {G.REP}, skip = −1 {G.REP}.",
        ]
    else:
        lines += ["", f"{G.BOLT} owner pull — no feedback required."]

    kb: list[list[IB]] = []
    if not owner:
        kb.append(
            [IB("✓ Working", callback_data=f"{CB['FB_WORK']}:{kind}:{item_id}"),
             IB("✗ Dead", callback_data=f"{CB['FB_DEAD']}:{kind}:{item_id}")]
        )
        kb.append([IB(f"{G.SKIP} Skip · −1 {G.REP}", callback_data=f"{CB['FB_SKIP']}:{kind}:{item_id}")])
    kb.append([IB(f"{G.BOLT} Pull again", callback_data=f"{CB['GEN_AGAIN']}:{kind}"),
               IB("◂ Main", callback_data=CB["HOME"])])
    return "\n".join(lines) + footer(), IM(kb)


def feedback_done(fb: store.FeedbackResult, kind: str) -> tuple[str, IM]:
    lines = [page_header("Feedback logged"), G.LINE]
    if fb.verdict == "working":
        lines += [
            f"{G.OK} marked working — the pool heard you.",
            f"{G.PLUS} +1 {G.REP} → reputation {fb.new_rep} {G.REP}",
        ]
    elif fb.verdict == "dead":
        lines += [
            f"{G.NO} marked dead — the slot was pulled from the pool.",
            f"{G.BOLT} owner already got the ping.",
        ]
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
        [IB(f"{G.BOLT} Pull again", callback_data=f"{CB['GEN_AGAIN']}:{kind}")],
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
    lines = [
        page_header("Pace keeper"),
        G.LINE,
        f"{G.BOLT} your tier breathes between pulls.",
        f"{G.DIAM} next slot opens in ~{clock}.",
        "",
        f"{G.CHAT} want a faster pace? move up a tier — one dm to the owner.",
    ]
    kb = [
        [IB(f"{G.ARR} Email:Pass", callback_data=CB["GEN_EP"]),
         IB(f"{G.ARR} PC Key", callback_data=CB["GEN_KEY"])],
        [IB(f"{G.STAR} Plans", callback_data=CB["PLANS"]),
         IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def limit_wall(res: store.ServeResult) -> tuple[str, IM]:
    lines = [
        page_header("Daily wall"),
        G.LINE,
        f"{G.LOCK} you used {res.daily}/{res.limit} pulls today — the day resets at midnight.",
        "",
        f"{G.CHAT} bigger tiers lift the ceiling instantly. dm the owner to upgrade.",
    ]
    kb = [
        [IB(f"{G.MAIL} Contact owner", callback_data=CB["CONTACT"])],
        [IB(f"{G.STAR} Plans", callback_data=CB["PLANS"]),
         IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def empty(kind: str) -> tuple[str, IM]:
    other = KEY if kind == EP else EP
    lines = [
        page_header("Pool drained"),
        G.LINE,
        f"{G.WARN} {STOCK_LABEL[kind]} is dry for this moment — restock lands soon.",
        f"{G.ARR} meanwhile: try {STOCK_LABEL[other]} or order a private slot.",
    ]
    kb = [
        [IB(f"{G.ARR} {STOCK_LABEL[other]}", callback_data=CB["GEN_" + ("EP" if other == EP else "KEY")])],
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
        [IB(f"{G.BOLT} Email:Pass", callback_data=CB["GEN_EP"]),
         IB(f"{G.BOLT} PC Key", callback_data=CB["GEN_KEY"])],
        [IB(f"{G.STAR} Plans", callback_data=CB["PLANS"]),
         IB("◂ Main", callback_data=CB["HOME"])],
    ]
    if owner:
        kb.append([IB(f"{G.BOLT} Owner core", callback_data=CB["OWN_PANEL"])])
    return "\n".join(lines) + footer(), IM(kb)


async def stock_page(force: bool = False) -> tuple[str, IM]:
    if force:
        cache.stock_invalidate()
    stock = await cache.stock()
    total_users = await cache.users()
    lines = [
        page_header("Drop status"),
        G.LINE,
        f"{G.DOT} email:pass   {stock['ep']}",
        f"{G.DOT} pc keys      {stock['key']}",
        f"{G.DOTF} members      {total_users}",
        f"{G.BOLT} system       online · relay smooth",
    ]
    kb = [
        [IB(f"{G.BOLT} Email:Pass", callback_data=CB["GEN_EP"]),
         IB(f"{G.BOLT} PC Key", callback_data=CB["GEN_KEY"])],
        [IB(f"{G.LOOP} Refresh", callback_data=CB["STOCK_FORCE"]),
         IB("◂ Main", callback_data=CB["HOME"])],
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
        cooldown = store.plan_cooldown_minutes(plan)
        pace = "no cooldown" if not cooldown else f"1 per {cooldown} min"
        ceiling = "unlimited" if limit is None else f"{limit} pulls/day"
        tag = f"{G.DOTF} yours now" if plan == current else ""
        lines.append(f"{_pl(plan)} {tag}")
        lines.append(f"      {G.ARR} {ceiling} · {pace}")
    lines += [
        "",
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
    cooldown = store.plan_cooldown_minutes(plan)
    pace = "no cooldown — instant pulls" if not cooldown else f"1 pull every {cooldown} min"
    ceiling = "no daily ceiling" if limit is None else f"{limit} pulls every day"
    lines = [
        page_header(f"Tier · {config.PLAN_TITLE.get(plan, plan)}"),
        G.LINE,
        f"{G.DIAM} {sc(config.PLAN_TAG.get(plan, ''))}",
        f"{G.ARR} {ceiling}",
        f"{G.ARR} {pace}",
        f"{G.ARR} access: email:pass pool + pc key pool",
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
    elif kind == MODE["ADD_EP"]:
        text = (
            f"{G.PLUS} add email:pass\n"
            f"{G.LINE_S}\n"
            "paste lines, one account per line:\n"
            "  email@x.com:password\n"
            "duplicates are skipped automatically."
        )
    elif kind == MODE["ADD_KEY"]:
        text = (
            f"{G.PLUS} add pc keys\n"
            f"{G.LINE_S}\n"
            "paste keys, one per line — duplicates are skipped automatically."
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
    else:  # pragma: no cover
        text = "paste your input."
    kb = [[IB("✕ Cancel", callback_data=CB["CANCEL_MODE"])]]
    return text + footer(), IM(kb)


def message_sent(kind: str) -> tuple[str, IM]:
    if kind == "contact":
        lines = [f"{G.OK} delivered — the owner reads the inbox first-come.",
                 f"{G.BOLT} want it faster? dm directly and mention your user id."]
    else:
        lines = [f"{G.OK} report filed — thank you, it keeps the vault sharp.",
                 f"{G.BOLT} dead drops get pulled automatically."]
    kb = [[IB("◂ Main", callback_data=CB["HOME"])]]
    return "\n".join([page_header("Sent"), G.LINE, *lines]) + footer(), IM(kb)


async def help_page() -> tuple[str, IM]:
    stock = await cache.stock()
    lines = [
        page_header("Help"),
        G.LINE,
        f"{G.ARR} everything runs from the menu — one tap swaps the screen, nothing spams.",
        f"{G.ARR} quick keys that still work:",
        "     /gen · /plans · /profile · /status · /contact · /hits · /help",
        "",
        f"{G.CHAT} tip: after a drop, tell us if it worked — you earn {G.REP} rep, "
        f"the vault gets cleaner.",
    ]
    kb = [
        [IB(f"{G.BOLT} Email:Pass{_count_suffix(EP, stock)}", callback_data=CB["GEN_EP"]),
         IB(f"{G.BOLT} PC Key{_count_suffix(KEY, stock)}", callback_data=CB["GEN_KEY"])],
        [IB(f"{G.DOT} Stock", callback_data=CB["STOCK"]),
         IB(f"{G.DOTF} Profile", callback_data=CB["PROFILE"])],
        [IB(f"{G.STAR} Plans", callback_data=CB["PLANS"]),
         IB(f"{G.MAIL} Contact", callback_data=CB["CONTACT"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


# ────────────────────────────────────────────────────────────────
#  OWNER SPACE  (never rendered for anyone else)
# ────────────────────────────────────────────────────────────────
async def owner_panel() -> tuple[str, IM]:
    s = await store.dashboard_stats()
    unread = await store.mailbox_unread_counts()
    plan_split = " · ".join(f"{_pl(p).strip()} {s['plans'].get(p, 0)}" for p in config.PLAN_ORDER)
    lines = [
        page_header("Owner core"),
        G.LINE,
        f"{G.DIAM} users      {s['users']}   ({s['banned']} banned)",
        f"{G.DIAM} today      {s['serves_today']} pulls · {s['active_today']} active",
        f"{G.DIAM} all-time   {s['serves_total']} pulls",
        f"{G.DIAM} stock      ep {s['ep']} · keys {s['keys']}",
        f"{G.DIAM} verdicts   {G.OK} {s['working_reports']} · {G.NO} {s['dead_reports']}",
        f"{G.DIAM} plan mix   {plan_split}",
    ]
    kb = [
        [IB(f"{G.PLUS} Email:Pass", callback_data=CB["OWN_ADD_EP"]),
         IB(f"{G.PLUS} PC Keys", callback_data=CB["OWN_ADD_KEY"])],
        [IB(f"{G.CHAT} Users · {s['users']}", callback_data=f"{CB['OWN_USER_PAGE']}1"),
         IB(f"{G.LOCK} Banned · {s['banned']}", callback_data=CB["OWN_BANNED"])],
        [IB(f"{G.MAIL} Messages · {unread['contact']}", callback_data=f"{CB['OWN_INBOX']}contact:0"),
         IB(f"{G.CHAT} Hits · {unread['hit']}", callback_data=f"{CB['OWN_INBOX']}hit:0")],
        [IB(f"{G.BOLT} Broadcast", callback_data=CB["OWN_BROADCAST"]),
         IB(f"{G.LOOP} Activity log", callback_data=CB["OWN_LOGS"])],
        [IB("⇩ Export .txt", callback_data=CB["OWN_EXPORT"]),
         IB(f"{G.NO} Reset pool", callback_data=CB["OWN_RESET"])],
        [IB(f"{G.LOOP} Refresh", callback_data=CB["OWN_STATS"]),
         IB("◂ Main", callback_data=CB["HOME"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


async def owner_users(page: int) -> tuple[str, IM]:
    total = await store.user_count()
    size = config.USERS_PER_PAGE
    pages = max(1, -(-total // size))
    page = max(1, min(page, pages))
    users = await store.users_page(page, size)

    if not users:
        lines = [page_header("Users"), G.LINE, f"{G.WARN} vault is empty — no members yet."]
    else:
        lines = [page_header(f"Users · p{page}/{pages}"), G.LINE]
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
    kb: list[list[IB]] = []
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
    if not rows:
        lines = [page_header("Banned"), G.LINE, f"{G.OK} nobody is locked."]
    else:
        lines = [page_header(f"Banned · {len(rows)}"), G.LINE]
        for u in rows:
            lines.append(
                f"{G.NO} <code>{u['user_id']}</code>  @{esc(u['username'] or '—')} — "
                f"{esc(u['ban_reason'] or 'no reason')}"
            )
    kb = [
        [IB(f"{G.WRITE} Search by id", callback_data=CB["OWN_SEARCH"])],
        [IB("◂ Users", callback_data=f"{CB['OWN_USER_PAGE']}1"),
         IB("◂ Panel", callback_data=CB["OWN_PANEL"])],
    ]
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


def add_done(kind: str, added: int, failed: int) -> tuple[str, IM]:
    lines = [
        page_header("Stock updated"),
        G.LINE,
        f"{G.OK} added {added} · skipped {failed}",
        f"{G.DIAM} pool: {STOCK_LABEL[kind]}",
    ]
    kb = [
        [IB(f"{G.PLUS} Add more", callback_data=CB["OWN_ADD_EP"] if kind == EP else CB["OWN_ADD_KEY"]),
         IB("◂ Panel", callback_data=CB["OWN_PANEL"])],
    ]
    return "\n".join(lines) + footer(), IM(kb)


def reset_confirm() -> tuple[str, IM]:
    lines = [
        page_header("Reset pool"),
        G.LINE,
        f"{G.WARN} this wipes every email:pass, every key and the serve history.",
        f"{G.NO} users could receive old drops again after the next refill.",
        "",
        f"{G.DIAM} type the exact word to confirm: <b>WIPE</b>",
    ]
    kb = [[IB("✕ Cancel", callback_data=CB["OWN_RESET_NO"])]]
    return "\n".join(lines) + footer(), IM(kb)
