"""
Sᴇʟꜰᴛᴇꜱᴛ ────────
Offline harness: renders EVERY screen with a fake data layer and
verifies the invariants that keep the bot premium & fast:
  • every page text ≤ 4096 chars (Telegram limit), payloads ≤ 64 bytes
  • no color-emoji leaks into rendered text
  • owner routes never resolve for non-owners; every owner button is
    registered, routed and answered (no silent branches)
  • menus edit ONE live message; a generated drop is its OWN new card
    — a second pull never replaces the first, feedback on an old card
    still works, error states never wipe credentials
  • pools never mix: claims/adds/exports/resets are category-scoped
    (checked at the SQL level), dead feedback keeps the row unless
    BOT_AUTO_REMOVE_DEAD is on
Run:  .venv/bin/python -m tests.selftest
"""
from __future__ import annotations

import asyncio
import contextlib
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, ".")

import config  # noqa: E402

config.ANIM_STEP_SEC = 0.01  # keep the harness snappy

import data.catalog as catalog  # noqa: E402
import data.store as store  # noqa: E402
import core.cache as cache  # noqa: E402
from core.style import sc as _sc  # noqa: E402

EPOCH = datetime.now() - timedelta(days=3)
OWN = config.OWNER_ID
UID = 555


# ── fake data layer ─────────────────────────────────────────────
def _fake_profile(uid: int) -> dict:
    return {
        "user_id": uid, "username": "tester", "first_name": "Test User",
        "plan": "pro", "reputation": 7, "is_banned": uid == 999, "ban_reason": "test" if uid == 999 else None,
        "total_gens": 14, "joined_at": EPOCH, "last_username": "tester",
        "today_count": 2, "last_gen": None,
    }


async def _f_get_profile(uid: int):
    return _fake_profile(uid)


async def _f_get_user(uid: int):
    p = dict(_fake_profile(uid))
    p.pop("today_count", None)
    p.pop("last_gen", None)
    return p


async def _f_user_count() -> int:
    return 120


async def _f_users_page(page: int, size: int = 10):
    base = max(0, (page - 1) * size)
    return [dict(_fake_profile(base + i), user_id=base + i, username=f"u{base + i}") for i in range(1, size + 1)]


async def _f_banned_users():
    return [{"user_id": 999, "username": "locked", "first_name": "Locked", "ban_reason": "test"}]


async def _f_feedback_log(_limit=12):
    return [{
        "user_id": 1, "item_type": "email", "item_id": 4, "feedback_type": "working",
        "feedback_at": datetime.now(), "username": "tester", "first_name": "T",
    }]


async def _f_mailbox_unread(kind: str, limit=12):
    return [{
        "id": 7, "user_id": 42, "username": "sender", "first_name": "S",
        "sent_at": datetime.now(), "content": "i would like a pro plan upgrade please",
    }]


async def _f_mailbox_counts():
    return {"contact": 2, "hit": 1}


async def _f_dashboard():
    return {
        "users": 120, "banned": 3, "ep": 11, "keys": 4, "active_today": 88,
        "serves_today": 140, "serves_total": 9300, "dead_reports": 2,
        "working_reports": 90, "plans": {"free": 100, "pro": 12, "elite": 5, "unlimited": 3},
    }


async def _f_export():
    return "── Netflix  (2)\nemail:pass:\nx@y.com:pw\n── Steam  (1)\nkeys:\nKEY-1", 2, 1


async def _noop(*_a, **_k):
    return None


# originals of the SQL-level store functions (the tap-flow fakes below
# replace the module attributes; these keep the REAL implementations so
# the pool-scoping checks exercise the actual SQL)
REAL = {
    name: getattr(store, name)
    for name in (
        "serve_claim", "record_feedback", "remove_item", "reset_pool",
        "add_items", "export_pool", "create_pool", "vault_categories", "pool_counts",
    )
}


# ── fake pool registry (the REAL seed, so pools match production) ──
POOL_LIST: list[catalog.Pool] = list(catalog.ordered_seed())
POOL_COUNTS: dict[str, int] = {
    "vpn": 12, "expressvpn": 5, "nordvpn": 7, "surfshark": 0, "windscribe": 0,
    "streaming": 4, "netflix": 6, "spotify": 3, "ai": 9, "chatgpt": 8,
    "claude": 2, "midjourney": 0, "characterai": 1,
    "pc": 3, "vpnkeys": 4, "gamekeys": 9, "steam": 5, "office": 0, "antivirus": 1,
}
CREATED_POOLS: list[tuple[str, str]] = []  # (label, kind) created in-bot


async def _f_vault_categories():
    return [
        {"category": p.category, "label": p.label, "kind": p.kind, "pos": p.pos}
        for p in POOL_LIST
    ]


async def _f_pool_counts():
    return [
        {"kind": p.kind, "category": p.category, "n": POOL_COUNTS.get(p.category, 0)}
        for p in POOL_LIST
    ]


async def _f_create_pool(label: str, kind: str):
    # mirrors store.create_pool rules against the fake registry
    clean = " ".join((label or "").split())
    if not clean or not catalog.slugify(clean):
        return "", "bad_name"
    if catalog.label_key(clean) in {catalog.label_key(p.label) for p in POOL_LIST}:
        return "", "name_exists"
    taken = {p.category for p in POOL_LIST}
    slug, _ = catalog.free_slug(catalog.slugify(clean), taken)
    if not slug:
        return "", "busy"
    POOL_LIST.append(catalog.Pool(slug, clean, kind, 99))
    POOL_COUNTS.setdefault(slug, 0)
    CREATED_POOLS.append((clean, kind))
    return slug, ""


async def _f_reset_pool(kind: str, category: str) -> int:
    n = POOL_COUNTS.get(category, 0)
    POOL_COUNTS[category] = 0
    return n


async def _f_export_pool(kind: str, category: str):
    if category == "office":  # an empty pool stays empty
        return "", 0
    lines = ["x@y.com:pw", "a@b.co:q"] if kind == "ep" else ["KEY-1", "KEY-2"]
    return "\n".join(lines), len(lines)


async def _f_remove_item(kind: str, category: str, item_id: int):
    if item_id == 12:
        POOL_COUNTS[category] = max(0, POOL_COUNTS.get(category, 0) - 1)
        if kind == "ep":
            return {"id": 12, "category": category, "email": "doomed@x.com", "password": "zz"}
        return {"id": 12, "category": category, "key": "DOOMED-KEY"}
    return None


store.get_profile = _f_get_profile
store.get_user = _f_get_user
store.user_count = _f_user_count
store.users_page = _f_users_page
store.banned_users = _f_banned_users
store.feedback_log = _f_feedback_log
store.mailbox_unread_counts = _f_mailbox_counts
store.mailbox_unread = _f_mailbox_unread
store.dashboard_stats = _f_dashboard
store.export_stock = _f_export
store.ensure_user = _noop
store.serve_claim = _noop
store.record_feedback = _noop
store.mailbox_add = _noop
store.mailbox_mark_read = _noop
store.mailbox_mark_all_read = _noop
store.mailbox_delete = _noop
store.set_plan = _noop
store.add_rep = _noop
store.ban = _noop
store.unban = _noop
store.reset_all_stock = _noop
store.get_user_by_username = _f_get_user
store.all_user_ids = _noop

store.vault_categories = _f_vault_categories
store.pool_counts = _f_pool_counts
store.create_pool = _f_create_pool
store.reset_pool = _f_reset_pool
store.export_pool = _f_export_pool
store.remove_item = _f_remove_item


async def _f_all_user_ids() -> list[int]:
    return [2, 3]


store.all_user_ids = _f_all_user_ids

# ── fake cache (pool snapshot on top of the fake registry) ─────
async def _f_snapshot(force: bool = False) -> None:
    return None


async def _f_pools(force: bool = False) -> list[catalog.Pool]:
    return list(POOL_LIST)


async def _f_pool_counts_dict(force: bool = False) -> dict[str, int]:
    return dict(POOL_COUNTS)


async def _f_stock() -> dict[str, int]:
    kinds = {p.category: p.kind for p in POOL_LIST}
    return {
        "ep": sum(n for c, n in POOL_COUNTS.items() if kinds.get(c) == "ep"),
        "key": sum(n for c, n in POOL_COUNTS.items() if kinds.get(c) == "key"),
    }


def _f_hottest(limit: int = 4):
    ranked = sorted(POOL_LIST, key=lambda p: -POOL_COUNTS.get(p.category, 0))
    return [(p, POOL_COUNTS.get(p.category, 0)) for p in ranked[:limit]]


cache.snapshot = _f_snapshot
cache.pools = _f_pools
cache.get_pool = lambda slug: next((p for p in POOL_LIST if p.category == slug), None)
cache.pool_counts = _f_pool_counts_dict
cache.stock = _f_stock
cache.hottest = _f_hottest
cache.pools_invalidate = lambda: None
cache.stock_invalidate = lambda: None
cache.users = _f_user_count
cache.users_invalidate = lambda: None
cache.banned = _noop
cache.banned_mark = lambda *a, **k: None

# ── meaningful serve/feedback fakes (pool-scoped) ───────────────
SERVE_STATE = {"status": "ok"}
SERVED_ITEMS = {"ep": 11, "key": 5}
ADD_CALLS: list[tuple[str, int]] = []      # (category, lines)
FB_CALLS: list[tuple[str, str]] = []       # (verdict, category)


async def _f_serve(uid, username, first_name, kind, category, *, owner=False, pool_label=""):
    st = SERVE_STATE["status"]
    if st != "ok":
        return store.ServeResult(
            status=st, plan="pro", wait_sec=95, daily=5,
            limit=5 if st == "limit" else 20, pool_label=pool_label,
        )
    if kind == "ep":
        SERVED_ITEMS["ep"] += 1
        item = {"id": SERVED_ITEMS["ep"], "kind": "ep", "category": category,
                "email": f"a{category}@b.co", "password": "pw1"}
    else:
        SERVED_ITEMS["key"] += 1
        item = {"id": SERVED_ITEMS["key"], "kind": "key", "category": category,
                "key": f"KEY-{category.upper()}-77"}
    POOL_COUNTS[category] = max(0, POOL_COUNTS.get(category, 0) - 1)
    return store.ServeResult(status="ok", plan="pro", daily=3, limit=20,
                             item=item, pool_label=pool_label)


async def _f_feedback(uid, kind, item_id, verdict, *, owner=False, category="", pool_label=""):
    FB_CALLS.append((verdict, category))
    res = store.FeedbackResult(verdict=verdict, pool_label=pool_label or category)
    if verdict == "working":
        res.rep_delta, res.new_rep = 1, 8
    elif verdict == "dead":
        if kind == "ep":
            res.item = {"id": item_id, "category": category, "kind": kind,
                        "email": "dead@x.com", "password": "pw"}
        else:
            res.item = {"id": item_id, "category": category, "kind": kind, "key": "DEAD-KEY"}
        if config.AUTO_REMOVE_DEAD:
            res.removed, res.removed_word = res.item, "email" if kind == "ep" else "key"
        else:
            res.kept = True
    else:
        res.rep_delta, res.new_rep = -1, 4
    return res


async def _f_add_items(uid, kind, category, lines):
    ADD_CALLS.append((category, len(lines)))
    return store.AddResult(added=len(lines), failed=0)


async def _f_mailbox_add(kind, uid, content) -> int:
    return 1


store.serve_claim = _f_serve
store.record_feedback = _f_feedback
store.add_items = _f_add_items
store.mailbox_add = _f_mailbox_add

NOTIFIES: list[str] = []


async def _f_notify(context, chat_id, text, markup=None, parse_mode=None):
    NOTIFIES.append(text)
    return True


import core.net as net  # noqa: E402
net.notify = _f_notify


# ── verification helpers ────────────────────────────────────────
PROBLEMS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'ok' if ok else '!!'}] {label}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        PROBLEMS.append(f"{label}: {detail}")


EMOJI_FOOTPRINT = set(
    "😀😂🥺😎😈🤖👻🙏👍👎🙌💪🫶💀☠️❤️💙🔥✨⭐🌟💫⚡❄️☀️🌙🎉🎊🎁🚀"
    "📧📨📩💌🔑🗝️🔐📊📈📉👤👥✅❌⛔🚫❗❓❕➡️⬅️⬆️⬇️↗️↘️💬🗨️📢📣"
    "🕐⏳⏰🎯🧠🛡️💎🏆🥇🥈🥉♻️🔄↩️↪️☑️✔️✖️➕➖➗🆓🅿️🈁✈️🌐🔗🌊☁️🔥"
)
def emoji_leak(text: str) -> str | None:
    """
    No color emoji anywhere. The curated text-glyph palette (⚠ ↯ ✦ ▸ ✓ ✗ …)
    is allowed — but ⚠ only as a PLAIN glyph, never in its emoji form
    (U+FE0F variation selector) — so the bot stays 100 % emoji-free.
    """
    for i, ch in enumerate(text):
        if ord(ch) >= 0x1F000:
            return ch
        if ch == "\u26a0":  # ⚠ — legal unless followed by an emoji selector
            if i + 1 < len(text) and text[i + 1] in ("\ufe0f",):
                return "⚠️"
            continue
        if ch in EMOJI_FOOTPRINT:
            return ch
    return None


# ── render all views ────────────────────────────────────────────
async def render_views() -> dict:
    from core import views

    pool_netflix = cache.get_pool("netflix")
    pool_steam = cache.get_pool("steam")

    renderers: dict[str, object] = {
        "home": lambda: views.home(UID),
        "home_owner": lambda: views.home(OWN),
        "vault": lambda: views.vault(UID),
        "profile": lambda: views.profile_page(UID),
        "stock": lambda: views.stock_page(),
        "plans": lambda: views.plans_page(UID),
        "contact": lambda: views.contact_page(UID),
        "help": lambda: views.help_page(),
        "owner_panel": lambda: views.owner_panel(),
        "owner_users": lambda: views.owner_users(1),
        "owner_manage": lambda: views.owner_manage(4444),
        "owner_banned": lambda: views.owner_banned(),
        "owner_logs": lambda: views.owner_logs(),
        "owner_inbox_contact": lambda: views.owner_inbox("contact", 0),
        "owner_inbox_hit": lambda: views.owner_inbox("hit", 0),
        "vault_manager_1": lambda: views.owner_vault_manager(1),
        "vault_manager_2": lambda: views.owner_vault_manager(2),
        "vault_manager_3": lambda: views.owner_vault_manager(3),
        "owner_admin_1": lambda: views.owner_admin(1),
        "owner_admin_2": lambda: views.owner_admin(2),
        "owner_admin_last": lambda: views.owner_admin(99),
        "write_prompt": lambda: views.text_mode_prompt("write_msg"),
        "hit_prompt": lambda: views.text_mode_prompt("hit_report"),
        "search_prompt": lambda: views.text_mode_prompt("search_user"),
        "bc_prompt": lambda: views.text_mode_prompt("broadcast"),
        "add_prompt_ep": lambda: views.pool_prompt_add(pool_netflix),
        "add_prompt_key": lambda: views.pool_prompt_add(pool_steam),
        "remove_prompt": lambda: views.pool_prompt_remove(pool_netflix),
        "reset_pool_prompt": lambda: views.pool_prompt_reset(pool_netflix),
        "new_pool_prompt": lambda: views.pool_prompt_new(),
        "kind_prompt": lambda: views.pool_pick_kind("Disney+", "disney"),
        "reset_confirm": lambda: views.reset_confirm(),
        "msg_sent": lambda: views.message_sent("contact"),
        "hit_sent": lambda: views.message_sent("hit"),
        "add_done": lambda: views.owner_add_done(pool_netflix, 5, 2),
        "removed": lambda: views.owner_removed(pool_netflix, {"id": 12, "email": "a@b.c", "password": "p"}),
        "reset_done": lambda: views.owner_reset_done(pool_netflix, 4, False),
        "reset_abort": lambda: views.owner_reset_done(pool_netflix, 4, True),
        "banned": lambda: views.banned_page("because"),
    }
    for plan in config.PLAN_ORDER:
        renderers[f"plan_detail:{plan}"] = lambda p=plan: views.plan_detail_page(p, UID)

    sr_ep = store.ServeResult(
        status="ok", plan="pro", daily=2, limit=20,
        item={"id": 9, "kind": "ep", "category": "netflix", "email": "x@y.com", "password": "pw"},
        pool_label="Netflix",
    )
    sr_key = store.ServeResult(
        status="ok", plan="pro", daily=2, limit=20,
        item={"id": 3, "kind": "key", "category": "steam", "key": "ABCD-1234"},
        pool_label="Steam",
    )
    sr_unlim = store.ServeResult(
        status="ok", plan="unlimited", daily=7, limit=None,
        item={"id": 4, "kind": "ep", "category": "vpn", "email": "u@y.com", "password": "p"},
        pool_label="VPN Accounts",
    )
    fb_ok = store.FeedbackResult(verdict="working", rep_delta=1, new_rep=8, pool_label="Netflix")
    fb_dead = store.FeedbackResult(
        verdict="dead", kept=True, pool_label="Netflix",
        item={"id": 9, "category": "netflix", "kind": "ep", "email": "x@y.com", "password": "pw"},
    )
    fb_dead_rm = store.FeedbackResult(
        verdict="dead", pool_label="Netflix",
        removed={"id": 9, "email": "x@y.com", "password": "pw"}, removed_word="email",
    )
    fb_skip = store.FeedbackResult(verdict="skip", rep_delta=-1, new_rep=4)
    fb_ban = store.FeedbackResult(verdict="skip", rep_delta=-1, new_rep=0, banned=True, ban_reason="rep 0")
    cooldown = store.ServeResult(status="cooldown", plan="free", wait_sec=95, pool_label="Netflix")
    wall = store.ServeResult(status="limit", plan="free", daily=5, limit=5, pool_label="NordVPN")
    renderers.update({
        "result_ep": lambda: views.result(sr_ep, owner=False),
        "result_ep_owner": lambda: views.result(sr_ep, owner=True),
        "result_key": lambda: views.result(sr_key, owner=False),
        "result_unlim": lambda: views.result(sr_unlim, owner=False),
        "fb_verdict_working": lambda: views.feedback_verdict(fb_ok, "netflix"),
        "fb_verdict_dead": lambda: views.feedback_verdict(fb_dead, "netflix"),
        "fb_verdict_dead_removed": lambda: views.feedback_verdict(fb_dead_rm, "netflix"),
        "fb_verdict_skip": lambda: views.feedback_verdict(fb_skip, "netflix"),
        "fb_verdict_ban": lambda: views.feedback_verdict(fb_ban, "netflix"),
        "feedback_working": lambda: views.feedback_done(fb_ok, "netflix"),
        "feedback_dead": lambda: views.feedback_done(fb_dead, "netflix"),
        "feedback_skip": lambda: views.feedback_done(fb_skip, "netflix"),
        "feedback_banned": lambda: views.feedback_done(fb_ban, "netflix"),
        "cooldown": lambda: views.cooldown(cooldown),
        "limit_wall": lambda: views.limit_wall(wall),
        "empty": lambda: views.empty(cache.get_pool("netflix")),
        "empty_unknown": lambda: views.empty(None),
    })

    import inspect

    all_cbs: dict[str, set[str]] = {}
    for name, fn in renderers.items():
        try:
            out = fn()  # type: ignore[misc]
            text, kb = await out if inspect.iscoroutine(out) else out  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            check(f"render {name}", False, f"raised {type(exc).__name__}: {exc}")
            continue
        check(f"render {name} ≤4096", len(text) <= 4096, f"len={len(text)}")
        leak = emoji_leak(text)
        check(f"render {name} clean", leak is None, f"emoji {leak!r}")
        rows = kb.inline_keyboard if kb is not None else []
        check(f"render {name} ≤8/row", all(len(r) <= 8 for r in rows))
        cbs: set[str] = set()
        for row in rows:
            for b in row:
                if b.callback_data:
                    cbs.add(b.callback_data)
                    check(
                        f"render {name} payload ≤64",
                        len(b.callback_data.encode()) <= 64,
                        f"{b.callback_data!r} len={len(b.callback_data.encode())}",
                    )
        all_cbs[name] = cbs
        if name.startswith(("owner", "vault_manager")):
            for cb in cbs:
                if cb.startswith("o"):
                    from core import handlers_owner
                    check(f"prefix registered {name}:{cb}", handlers_owner.owner_codes(cb), cb)

    # ── vault 2.0 grid/manager/stock coverage ──
    grid_text = (await views.vault(UID))[0]
    for p in POOL_LIST:
        check(f"grid shows pool {p.category}", catalog.clip(p.label, 18) in grid_text)
    check("grid groups by kind", _sc("Accounts · email:pass") in grid_text and _sc("Keys · serial / PC") in grid_text)
    check("grid shows live totals", "totals" in grid_text)
    mgr_text = ""
    for pg in range(1, 4):
        mgr_text += (await views.owner_vault_manager(pg))[0]
    for p in POOL_LIST:
        check(f"manager shows pool {p.category}", catalog.clip(p.label, 20) in mgr_text)
    check("manager row actions", all(s in mgr_text for s in ("＋ add", "⇩ export", "✕ remove by id", "⚠ reset")))
    st_text = (await views.stock_page())[0]
    check("stock page per-pool counts", "pools" in st_text and "Netflix" in st_text and "VPN Accounts" in st_text)

    home_text, home_kb = await views.home(UID)
    check("home shows live totals", "members" in home_text and "120" in home_text)
    home_btns = [b.text for r in home_kb.inline_keyboard for b in r]
    check("home hottest chips", any("VPN Accounts [12]" in t for t in home_btns), str(home_btns))
    home_cbs = all_cbs["home"]
    check("home chips pull from ONE pool", any(c.startswith("g:vpn") for c in home_cbs), str(home_cbs))
    check("home links the grid", "vg" in home_cbs)

    res_text = views.result(sr_ep, owner=False)[0]
    check("result card names the pool", "pool: " in res_text and "Netflix" in res_text and "Steam" not in res_text)
    check("result feedback pool-scoped", {"fw:netflix:9", "fd:netflix:9", "fs:netflix:9", "ga:netflix"} <= all_cbs["result_ep"])
    check("owner result has no feedback btns", not any(c.startswith("fw:") for c in all_cbs["result_ep_owner"]))
    check("key result references its pool", "Steam" in views.result(sr_key, owner=False)[0])

    dead_line = views.feedback_verdict(fb_dead, "netflix")[0]
    check("dead verdict says kept", "stays" in dead_line and "pulled" not in dead_line, dead_line)
    check("dead verdict auto-remove wording only when removed",
          "pulled" in views.feedback_verdict(fb_dead_rm, "netflix")[0])

    # /admin manual: keep in sync with the real owner surface
    admin_all = ""
    for pg in range(1, 7):
        admin_all += views.owner_admin(pg)[0]
    for cmd in ("/panel", "/users", "/manage", "/export", "/admin"):
        check(f"admin manual lists {cmd}", _sc(cmd) in admin_all or cmd in admin_all)
    for group in ("Vault manager", "New pool", "Users / Banned", "Search", "Messages / Hits",
                  "Broadcast", "Activity log", "Export all", "Reset all", "Refresh"):
        check(f"admin manual covers {group}", group in admin_all or _sc(group) in admin_all)

    print("\n--- unique glyphs used across all pages ---")
    glyphs = set()
    for name, fn in renderers.items():
        try:
            out = fn()  # type: ignore[misc]
            text, _kb = await out if inspect.iscoroutine(out) else out  # type: ignore[misc]
            glyphs |= {c for c in text if ord(c) > 127}
        except Exception:
            pass
    print(" ".join(sorted(glyphs)))
    print()
    return all_cbs


# ── store-level SQL checks (pool isolation + dead policy) ─────
class _NullTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class FakeConn:
    def __init__(self, log: list):
        self.log = log

    def transaction(self):
        return _NullTx()

    async def execute(self, q, *a):
        self.log.append(("E", " ".join(q.split()), a))
        return "OK"

    async def fetchrow(self, q, *a):
        qq = " ".join(q.split())
        self.log.append(("F1", qq, a))
        if "plan, is_banned" in qq:
            return {"plan": "free", "is_banned": False}
        if "FROM stock_emailpass s" in qq:
            return {"id": 7, "category": "netflix", "email": "e@f.g", "password": "pw"}
        if "FROM stock_emailpass WHERE id = $1 AND category = $2" in qq:
            if len(a) >= 2 and a[1] == "netflix":
                return {"id": 7, "category": "netflix", "email": "x@y.z", "password": "pw"}
            return None
        if "FROM stock_emailpass WHERE id = $1" in qq:
            return {"id": 7, "category": "netflix", "email": "x@y.z", "password": "pw"}
        return None

    async def fetchval(self, q, *a):
        qq = " ".join(q.split())
        self.log.append(("FV", qq, a))
        if "last_gen" in qq:
            return None
        if "label FROM vault_categories" in qq:
            return "Netflix"
        if "count FROM user_limits" in qq:
            return 1
        if "COUNT" in qq:
            return 3
        return 0


@contextlib.asynccontextmanager
async def _fake_conn_cm(conn):
    yield conn


async def store_sql_checks() -> None:
    from data.db import db

    log_sql: list = []
    conn = FakeConn(log_sql)
    saved = (db.conn, db.execute, db.fetch, db.fetchrow, db.fetchval)

    @contextlib.asynccontextmanager
    async def _f_conn():
        yield conn

    async def _f_execute(q, *a):
        log_sql.append(("E", " ".join(q.split()), a))

    async def _f_fetch(q, *a):
        log_sql.append(("FT", " ".join(q.split()), a))
        return []

    async def _f_fetchrow(q, *a):
        log_sql.append(("FR", " ".join(q.split()), a))
        return None

    async def _f_fetchval(q, *a):
        log_sql.append(("FV", " ".join(q.split()), a))
        return 0

    try:
        db.conn, db.execute, db.fetch, db.fetchrow, db.fetchval = _f_conn, _f_execute, _f_fetch, _f_fetchrow, _f_fetchval

        # 1) serving is scoped to exactly ONE pool (category is a filter)
        res = await REAL["serve_claim"](1, "u", "n", "ep", "netflix", pool_label="Netflix")
        claims = [q for kind, q, _a in log_sql if kind == "F1" and "FROM stock_emailpass s" in q]
        check("claim is pool-scoped", any("s.category = $2" in q for q in claims), str(claims))
        check("claim still dedupes per user", any("h.item_id IS NULL" in q for q in claims))
        check("serve keeps pool label", res.status == "ok" and res.pool_label == "Netflix"
              and res.item and res.item["category"] == "netflix")

        # 2) dead feedback: row KEPT by default …
        log_sql.clear()
        fb = await REAL["record_feedback"](2, "ep", 7, "dead", category="netflix", pool_label="Netflix")
        dels = [q for k, q, _a in log_sql if k == "E" and q.startswith("DELETE FROM stock_emailpass")]
        check("dead: row kept by default", not dels, str(dels))
        check("dead: result carries the item", fb.item is not None and fb.kept)
        check("dead: still logged", any(q.startswith("INSERT INTO feedback_log") for k, q, _a in log_sql if k == "E"))

        #    … and DOES delete when the flag is ON (history cleaned too)
        log_sql.clear()
        config.AUTO_REMOVE_DEAD = True
        try:
            fb2 = await REAL["record_feedback"](2, "ep", 7, "dead", category="netflix")
        finally:
            config.AUTO_REMOVE_DEAD = False
        dels = [q for k, q, _a in log_sql if k == "E" and q.startswith("DELETE FROM stock_emailpass")]
        check("dead: removed when flag ON", bool(dels))
        check("dead: flag ON clears history",
              any(q.startswith("DELETE FROM user_history_email") for k, q, _a in log_sql if k == "E"))
        check("dead: flag ON reports removal", fb2.removed is not None and not fb2.kept)
        check("dead: owner gets the pool label", fb2.pool_label == "Netflix")

        # 3) manual remove-by-id is pool-scoped + clears served history
        log_sql.clear()
        row = await REAL["remove_item"]("ep", "netflix", 7)
        sel = [q for k, q, _a in log_sql if k == "F1"]
        check("remove: scoped to pool", any("WHERE id = $1 AND category = $2" in q for q in sel), str(sel))
        check("remove: stock deleted", any(k == "E" and q == "DELETE FROM stock_emailpass WHERE id = $1" for k, q, _a in log_sql))
        check("remove: history cleared", any(k == "E" and q == "DELETE FROM user_history_email WHERE item_id = $1" for k, q, _a in log_sql))
        check("remove: returns row", row is not None and row["id"] == 7)
        log_sql.clear()
        none_row = await REAL["remove_item"]("ep", "nordvpn", 7)
        check("remove: wrong pool refuses", none_row is None)

        # 4) per-pool reset only touches that category
        log_sql.clear()
        n = await REAL["reset_pool"]("ep", "netflix")
        check("reset pool: count", n == 3)
        check("reset pool: category-scoped deletes",
              all("category = $1" in q for k, q, _a in log_sql if k == "E" and q.startswith("DELETE FROM stock_emailpass")),
              str([q for k, q, _a in log_sql if k == "E"]))
        check("reset pool: history scoped too",
              all("category = $1" in q for k, q, _a in log_sql if k == "E" and q.startswith("DELETE FROM user_history_email")))

        # 5) adds land INTO the chosen pool (category param on every insert)
        log_sql.clear()
        out = await REAL["add_items"](1, "ep", "nordvpn", ["a@b.c:pw", "bad-line", "c@d.e:pw2"])
        ins = [a for k, q, a in log_sql if k == "E" and q.startswith("INSERT INTO stock_emailpass")]
        check("add: into pool only", len(ins) == 2 and all(len(a) >= 3 and a[2] == "nordvpn" for a in ins), str(ins))
        check("add: malformed skipped", out.added == 2 and out.failed == 1)

        # 6) export is per-pool and the full export is sectioned
        log_sql.clear()
        content, cnt = await REAL["export_pool"]("ep", "nordvpn")
        check("export pool query scoped", any("WHERE category = $1" in q for k, q, _a in log_sql if k == "FT"))
        check("export pool rows", cnt == 0 and content == "")
    finally:
        db.conn, db.execute, db.fetch, db.fetchrow, db.fetchval = saved


# ── router wiring: constants ↔ prefixes ↔ handlers stay in sync ─
def constant_sync_checks() -> None:
    from core import handlers_owner
    from core.constants import CB

    registered = set(handlers_owner._OWNER_PREFIXES)
    for name, val in CB.items():
        if not name.startswith("OWN_"):
            continue
        check(f"prefix registered {name}={val}", val in registered, name)
        check(f"route handled {name}", f'CB["{name}"]' in _owner_src(), name)
    for prefix in registered:
        check(f"no orphan prefix {prefix}", prefix in set(CB.values()), prefix)


_OWNER_SRC_CACHE: list[str] = []


def _owner_src() -> str:
    if not _OWNER_SRC_CACHE:
        with open("core/handlers_owner.py", encoding="utf-8") as fh:
            _OWNER_SRC_CACHE.append(fh.read())
    return _OWNER_SRC_CACHE[0]


# ── catalog / slug rules ────────────────────────────────────────
def slug_checks() -> None:
    s = catalog.slugify
    check("slugify expressvpn", s("ExpressVPN") == "expressvpn", s("ExpressVPN"))
    check("slugify dots+digits", s("Character.ai") == "characterai", s("Character.ai"))
    check("slugify symbols", s("Windows/Office") == "windowsoffice", s("Windows/Office"))
    check("slugify ampersand", s("PC & Software Keys") == "pcsoftwarekeys", s("PC & Software Keys"))
    check("slugify pure glyphs → empty", s("……") == "", repr(s("……")))
    taken = {"games", "gamekeys", "gamekeys2"}
    got, mod = catalog.free_slug("gamekeys", taken)
    check("slug collision → suffix", got == "gamekeys3" and mod, got)
    check("slug free passes", catalog.free_slug("disney", taken) == ("disney", False))
    check("seed covers both kinds",
          {p.kind for p in catalog.SEED_POOLS} == {"ep", "key"} and len(catalog.SEED_POOLS) == 19)
    check("seed pools unique", len({p.category for p in catalog.SEED_POOLS}) == len(catalog.SEED_POOLS))
    check("legacy maps to seeded pools",
          catalog.LEGACY_CATEGORY["ep"] in {p.category for p in catalog.SEED_POOLS}
          and catalog.LEGACY_CATEGORY["key"] in {p.category for p in catalog.SEED_POOLS})
    check("config AUTO_REMOVE_DEAD defaults off", config.AUTO_REMOVE_DEAD is False)
    check("owner id pinned", config.OWNER_ID == 7728424218)
    check("no secrets in config defaults", config.BOT_TOKEN is None or config.BOT_TOKEN == "")


# ── simulated taps ─────────────────────────────────────────────
class FakeBot:
    def __init__(self):
        self.sent: list[tuple[str, int]] = []
        self.edited: list[tuple[int, int]] = []
        self.messages: dict[tuple[int, int], str] = {}

    async def send_message(self, chat_id=None, text="", **_kw):
        msg = SimpleMessage(chat_id=chat_id, message_id=9000 + len(self.sent) + 1, bot=self)
        self.sent.append((text, chat_id))
        self.messages[(chat_id, msg.message_id)] = text
        return msg

    async def edit_message_text(self, chat_id=None, message_id=None, text="", **_kw):
        self.edited.append((chat_id, message_id))
        self.messages[(chat_id, message_id)] = text
        return SimpleMessage(chat_id=chat_id, message_id=message_id, bot=self)


class SimpleMessage:
    DOCUMENTS: list[tuple[int, str, str]] = []

    def __init__(self, chat_id: int, message_id: int, bot=None):
        self.chat_id = chat_id
        self.message_id = message_id
        self._bot = bot

    async def reply_document(self, document, filename="", caption="", **_kw):
        SimpleMessage.DOCUMENTS.append((self.message_id, filename, caption))
        return self


class FakeQuery:
    def __init__(self, data: str, who: int = UID, username: str = "tester", msg_id: int = 1000):
        self.data = data
        self.message = SimpleMessage(chat_id=who, message_id=msg_id)
        self.answers: list[str] = []
        self.from_user = SimpleNamespace(id=who, username=username, first_name="Test User")

    async def answer(self, text=None, **_kw):
        self.answers.append(text or "")

    async def edit_message_text(self, text, reply_markup=None, **_kw):
        return self.message


class FakeCtx:
    def __init__(self):
        self.user_data: dict = {}
        self.bot_data: dict = {}
        self.chat_data: dict = {}
        self.args: list[str] = []
        self.bot = FakeBot()


class FakeUpdate:
    def __init__(self, query: FakeQuery):
        self.callback_query = query
        self.effective_user = query.from_user
        self.effective_chat = SimpleNamespace(id=query.from_user.id)


class TextUpdate:
    def __init__(self, who: int, text: str, username: str = "tester"):
        self.effective_user = SimpleNamespace(id=who, username=username, first_name="T")
        self.effective_chat = SimpleNamespace(id=who)
        self.message = SimpleNamespace(text=text, chat_id=who)


class _CmdUpdate:
    def __init__(self, who: int, args: list[str]):
        self.effective_user = SimpleNamespace(id=who, username="owner" if who == OWN else "tester", first_name="O")
        self.effective_chat = SimpleNamespace(id=who)
        self.message = SimpleNamespace(text="/cmd", chat_id=who)
        self.args = args


def page(ctx: FakeCtx, who: int, mid: int = 1000) -> str:
    return ctx.bot.messages.get((who, mid), "")


async def tap_flows() -> None:
    import bot as bot_mod  # central router (answers + routes)
    from core import views as _views

    async def tap(ctx: FakeCtx, data: str, who: int = UID, username: str = "tester",
                  msg_id: int = 1000) -> tuple[FakeQuery, bool]:
        q = FakeQuery(data, who=who, username=username, msg_id=msg_id)
        handled = await bot_mod.route_callback(FakeUpdate(q), ctx)
        return q, bool(handled)

    # member chain: navigation edits the ONE live message
    ctx = FakeCtx()
    q, ok = await tap(ctx, "h")
    check("tap home edits live page", ok and page(ctx, UID) and (UID, 1000) in ctx.bot.edited)
    check("tap home: no extra message", len(ctx.bot.sent) == 0, f"{len(ctx.bot.sent)} sends")
    check("home answered (spinner off)", len(q.answers) == 1)

    q, ok = await tap(ctx, "vg")
    check("vault grid edits the same message", ok and (UID, 1000) in ctx.bot.edited and len(ctx.bot.sent) == 0)

    # ── section 7: each generation is its OWN new message ──
    q, ok = await tap(ctx, "g:nordvpn")
    check("pull sends a NEW card message", ok and len(ctx.bot.sent) == 1, f"{len(ctx.bot.sent)} sends")
    card1 = (UID, 9001)
    txt1 = page(ctx, UID, 9001)
    check("card 1 landed via flourish+final edits", ctx.bot.edited.count(card1) >= 2, str(ctx.bot.edited))
    check("card 1 carries credentials", "anordvpn@b.co" in txt1)
    check("card 1 shows the pool", "NordVPN" in txt1)
    before1 = txt1

    q, ok = await tap(ctx, "ga:nordvpn", msg_id=9001)
    check("pull-again sends ANOTHER message", ok and len(ctx.bot.sent) == 2)
    txt1_again = page(ctx, UID, 9001)
    check("second pull does not edit the first card", txt1_again == before1)
    check("card 2 exists separately", "anordvpn@b.co" in page(ctx, UID, 9002) and 9002 != 9001)

    # error states must never wipe a visible card's credentials
    before2 = page(ctx, UID, 9002)
    SERVE_STATE["status"] = "cooldown"
    q, ok = await tap(ctx, "ga:nordvpn", msg_id=9002)
    SERVE_STATE["status"] = "ok"
    check("cooldown keeps card 2 intact", page(ctx, UID, 9002) == before2)
    check("cooldown notice is its own new message", len(ctx.bot.sent) == 3)
    check("cooldown notice speaks pace", "breathes" in ctx.bot.sent[-1][0])

    # feedback on the FIRST card — edits THAT card, creds stay visible
    q, ok = await tap(ctx, "fw:nordvpn:12", msg_id=9001)
    txt1_fb = page(ctx, UID, 9001)
    check("feedback on first card still works", ok and "✓" in txt1_fb and "working" in txt1_fb.lower())
    check("feedback keeps the credentials on the card", "anordvpn@b.co" in txt1_fb and txt1_fb.startswith(before1[:200]))
    check("feedback appends verdict under the card", len(txt1_fb) > len(before1))
    check("feedback answered with toast", q.answers[-1] == "logged ✓")

    # dead on card 2 → row kept + owner notified (pool + id + value + user)
    NOTIFIES.clear()
    FB_CALLS.clear()
    q, ok = await tap(ctx, "fd:nordvpn:13", msg_id=9002)
    txt2_fb = page(ctx, UID, 9002)
    check("dead: card keeps its drop text", "anordvpn@b.co" in txt2_fb)
    check("dead: friendly confirm on card", "kept" in txt2_fb.lower() or "review" in txt2_fb.lower())
    check("dead: owner pinged once", len(NOTIFIES) == 1)
    check("dead ping has pool + id + value + user",
          NOTIFIES and "NordVPN" in NOTIFIES[0] and "#13" in NOTIFIES[0]
          and "dead@x.com" in NOTIFIES[0] and "tester" in NOTIFIES[0])
    check("dead ping offers manager actions", "remove by id" in NOTIFIES[0])
    check("dead: feedback recorded for the pool", FB_CALLS[-1] == ("dead", "nordvpn"))

    # AUTO_REMOVE_DEAD=1 → verdict says the slot was pulled (flag flip)
    NOTIFIES.clear()
    config.AUTO_REMOVE_DEAD = True
    try:
        n_cards = len(ctx.bot.sent)
        q, ok = await tap(ctx, "g:steam")
        steam_card = 9000 + n_cards + 1
        q, ok = await tap(ctx, "fd:steam:13", msg_id=steam_card)
        txts = page(ctx, UID, steam_card)
        check("flag ON → verdict says pulled", ok and "pulled" in txts, txts[-160:])
        check("flag ON ping says AUTO-REMOVED", NOTIFIES and "AUTO-REMOVED" in NOTIFIES[-1])
    finally:
        config.AUTO_REMOVE_DEAD = False

    # navigation from a card keeps the card, edits the live menu instead
    q, ok = await tap(ctx, "h", msg_id=9001)
    check("nav from card keeps the card", page(ctx, UID, 9001) == txt1_fb)
    check("nav from card edits the live menu", (UID, 1000) in ctx.bot.edited)

    # stale card (memory gone) — confirm separately, old card untouched
    q, ok = await tap(ctx, "fw:nordvpn:99", msg_id=424242)
    check("stale-card feedback is a new message", ok and _sc("Feedback logged") in ctx.bot.sent[-1][0])
    check("stale-card feedback leaves its card alone", page(ctx, UID, 424242) == "")

    # unknown pool tap → polite notice, no crash, handled
    q, ok = await tap(ctx, "g:nosuchpool")
    check("unknown pool handled politely", ok and _sc("Pool drained") in ctx.bot.sent[-1][0])

    # normal user taps owner codes: swallowed, nothing rendered
    ctx2 = FakeCtx()
    q2, ok2 = await tap(ctx2, "op")
    joined = "\n".join(t for t, _ in ctx2.bot.sent) + page(ctx2, UID)
    check("owner panel hidden from user", "plan mix" not in joined and not ctx2.bot.edited)
    check("user owner-code tap answered + handled", ok2 and len(q2.answers) == 1)

    # ── owner: EVERY Owner Core top-level button works (section 5) ──
    octx = FakeCtx()
    q, ok = await tap(octx, "op", who=OWN, username="owner")
    check("owner panel rendered on live msg", ok and "plan mix" in page(octx, OWN))
    panel_text, panel_kb = await _views.owner_panel()
    panel_btns = [b.text for r in panel_kb.inline_keyboard for b in r]
    check("panel advertises vault manager", any("Vault manager" in t for t in panel_btns), str(panel_btns))
    check("panel keeps export + reset all", "Export all" in panel_text or any("Export all" in t for t in panel_btns))
    for cb in ("ost", "ovm:1", "oup:1", "obd", "oib:contact:0", "oib:hit:0",
               "obc", "olg", "oex", "orst", "orsn", "oam:1", "op"):
        SimpleMessage.DOCUMENTS.clear()
        e0 = len(octx.bot.edited)
        q, ok = await tap(octx, cb, who=OWN, username="owner")
        fresh = len(octx.bot.edited) > e0 or bool(SimpleMessage.DOCUMENTS)
        check(f"owner btn {cb} handled+answered", ok and fresh and len(q.answers) >= 1,
              f"ok={ok} fresh={fresh} answers={q.answers}")

    # users rows are tappable → manage card
    q, ok = await tap(octx, "oup:1", who=OWN, username="owner")
    check("users page renders tappable rows", ok and "manage" in page(octx, OWN))
    q, ok = await tap(octx, "oum:1", who=OWN, username="owner")
    check("user row opens manage card", ok and "rep      7" in page(octx, OWN), page(octx, OWN)[-200:])

    # banned rows tappable → manage
    q, ok = await tap(octx, "obd", who=OWN, username="owner")
    bn_text, bn_kb = await _views.owner_banned()
    check("banned page renders tappable rows", ok and any(
        b.callback_data and b.callback_data.startswith("oum:") for r in bn_kb.inline_keyboard for b in r))
    q, ok = await tap(octx, "oum:999", who=OWN, username="owner")
    check("banned row opens manage card", ok and "status   banned" in page(octx, OWN))

    # manage actions
    q, ok = await tap(octx, "opn:4444:elite", who=OWN, username="owner")
    check("plan set toast + card", ok and q.answers[-1] == "plan → elite" and "rep      7" in page(octx, OWN))
    q, ok = await tap(octx, "orp:4444:3", who=OWN, username="owner")
    check("rep change answered", ok and "+3 rep" in q.answers[-1])
    q, ok = await tap(octx, "obn:4444:1", who=OWN, username="owner")
    check("ban answered", ok and q.answers[-1] == "locked")
    q, ok = await tap(octx, f"obn:{OWN}:1", who=OWN, username="owner")
    check("owner cannot be banned", ok and "untouchable" in q.answers[-1])

    # ── vault manager + per-pool actions ──
    q, ok = await tap(octx, "ovm:1", who=OWN, username="owner")
    check("vault manager renders", ok and "NO code" in page(octx, OWN))

    # add stock → into the chosen pool only
    q, ok = await tap(octx, "ova:nordvpn", who=OWN, username="owner")
    check("add prompt armed for pool", ok and octx.user_data.get("mode") == "add_stock"
          and octx.user_data.get("mode_pool") == "nordvpn" and "NordVPN" in page(octx, OWN))
    from core import handlers_text

    ADD_CALLS.clear()
    await handlers_text.process_text(TextUpdate(OWN, "one@x.com:p1\ntwo@x.com:p2"), octx)
    check("add lands in ONE pool", ADD_CALLS and all(cat == "nordvpn" for cat, _n in ADD_CALLS), str(ADD_CALLS))
    check("add page reports the pool", "NordVPN" in page(octx, OWN))
    check("mode cleared after add", octx.user_data.get("mode") is None and octx.user_data.get("mode_pool") is None)

    # export per pool → one-pool document
    SimpleMessage.DOCUMENTS.clear()
    q, ok = await tap(octx, "ovx:nordvpn", who=OWN, username="owner")
    check("pool export sends vault_nordvpn.txt", ok and SimpleMessage.DOCUMENTS
          and SimpleMessage.DOCUMENTS[-1][1] == "vault_nordvpn.txt")
    SimpleMessage.DOCUMENTS.clear()
    q, ok = await tap(octx, "ovx:office", who=OWN, username="owner")
    check("empty pool export: no file, toast", ok and not SimpleMessage.DOCUMENTS and "empty" in q.answers[-1])

    # remove by id → inline prompt → delete + toast w/ value
    q, ok = await tap(octx, "orem:nordvpn", who=OWN, username="owner")
    check("remove prompt asks item id", ok and octx.user_data.get("mode") == "pool_rm"
          and "numeric item id" in page(octx, OWN))
    await handlers_text.process_text(TextUpdate(OWN, "12"), octx)
    check("remove-by-id deletes + shows removed value", "doomed@x.com" in page(octx, OWN), page(octx, OWN)[:160])
    q, ok = await tap(octx, "orem:nordvpn", who=OWN, username="owner")
    await handlers_text.process_text(TextUpdate(OWN, "999999"), octx)
    check("remove bad id refused", "no id" in page(octx, OWN), page(octx, OWN)[:160])

    # per-pool reset is WIPE-gated and pool-scoped
    q, ok = await tap(octx, "orpr:nordvpn", who=OWN, username="owner")
    check("pool reset asks WIPE", ok and "WIPE" in page(octx, OWN))
    before = POOL_COUNTS.get("nordvpn", 0)
    await handlers_text.process_text(TextUpdate(OWN, "maybe"), octx)
    check("reset refused without WIPE", POOL_COUNTS.get("nordvpn") == before and _sc("Reset aborted") in page(octx, OWN))
    await tap(octx, "orpr:nordvpn", who=OWN, username="owner")
    await handlers_text.process_text(TextUpdate(OWN, "WIPE"), octx)
    check("WIPE resets ONLY that pool", POOL_COUNTS.get("nordvpn") == 0 and POOL_COUNTS.get("vpn") == 12)
    POOL_COUNTS["nordvpn"] = 7

    # ── new pool without coding (section 2) ──
    q, ok = await tap(octx, "onp", who=OWN, username="owner")
    check("new pool step 1 asks name", ok and octx.user_data.get("mode") == "new_pool")
    await handlers_text.process_text(TextUpdate(OWN, "Disney+ Streaming"), octx)
    check("name parked for kind step", octx.user_data.get("new_pool") == "Disney+ Streaming")
    pk_text, pk_kb = _views.pool_pick_kind("Disney+ Streaming", "disneystreaming")
    pk_btns = [b.text for r in pk_kb.inline_keyboard for b in r]
    check("kind prompt offers both kinds",
          any("Accounts" in t for t in pk_btns) and any("Keys" in t for t in pk_btns), str(pk_btns))
    check("kind prompt names the pool", "Disney+ Streaming" in page(octx, OWN))
    q, ok = await tap(octx, "onpk:key", who=OWN, username="owner")
    check("pool created via kind button", ok and ("disneystreaming" in {p.category for p in POOL_LIST}), str(CREATED_POOLS))
    check("creation says no code needed", "no code" in (q.answers[-1] if q.answers else ""))
    check("new pool visible in manager immediately", "Disney+ Streaming" in page(octx, OWN))
    grid2 = (await _views.vault(UID))[0]
    check("new pool appears in user grid instantly", "Disney+ Streaming" in grid2)
    stock2 = (await _views.stock_page())[0]
    check("new pool appears on stock page", "Disney+ Streaming" in stock2)

    # duplicate name → error toast, nothing created
    q, ok = await tap(octx, "onp", who=OWN, username="owner")
    await handlers_text.process_text(TextUpdate(OWN, "Netflix"), octx)
    q, ok = await tap(octx, "onpk:key", who=OWN, username="owner")
    check("duplicate name → error toast", any("already exists" in a for a in q.answers), str(q.answers))
    check("duplicate not created", all(p.category != "netflix2" for p in POOL_LIST))
    # nonsense name refused
    q, ok = await tap(octx, "onp", who=OWN, username="owner")
    await handlers_text.process_text(TextUpdate(OWN, "……"), octx)
    check("empty slug refused with guidance", "letters or digits" in page(octx, OWN))

    # kind tap without a parked name → re-arms the name step
    q, ok = await tap(octx, "onpk:ep", who=OWN, username="owner")
    check("kind without name re-asks", ok and octx.user_data.get("mode") == "new_pool")

    # ── /admin silent manual (section 6) ──
    from core import handlers_owner

    actx = FakeCtx()
    await handlers_owner.cmd_admin(_CmdUpdate(OWN, []), actx)
    admin1 = actx.bot.sent[-1][0]
    check("admin renders p1/4 indicator", _sc("Owner manual · p1/4") in admin1, admin1[:120])
    q, ok = await tap(octx, "oam:2", who=OWN, username="owner")
    check("admin paging edits + p2 indicator", ok and _sc("p2/4") in page(octx, OWN))
    q, ok = await tap(octx, "oam:99", who=OWN, username="owner")
    check("admin clamps page", ok and _sc("p4/4") in page(octx, OWN))
    ntx = FakeCtx()
    await handlers_owner.cmd_admin(_CmdUpdate(UID, []), ntx)
    check("admin invisible to members", not ntx.bot.sent and not ntx.bot.edited)
    check("admin never in visible command list", "admin" not in {c.command for c in bot_mod.VISIBLE_COMMANDS})

    # global export + global reset stay wired
    SimpleMessage.DOCUMENTS.clear()
    q, ok = await tap(octx, "oex", who=OWN, username="owner")
    check("export all sends doc then panel", ok and SimpleMessage.DOCUMENTS and "plan mix" in page(octx, OWN))
    q, ok = await tap(octx, "orst", who=OWN, username="owner")
    check("reset all asks WIPE word", ok and "WIPE" in page(octx, OWN))
    q, ok = await tap(octx, "orsn", who=OWN, username="owner")
    check("reset cancel returns to panel", ok and "plan mix" in page(octx, OWN))
    # with no mode armed, a stray "WIPE" does nothing at all
    n_msgs = len(octx.bot.edited)
    await handlers_text.process_text(TextUpdate(OWN, "WIPE"), octx)
    check("stray WIPE without reset mode ignored", len(octx.bot.edited) == n_msgs)
    await tap(octx, "orst", who=OWN, username="owner")
    await handlers_text.process_text(TextUpdate(OWN, "WIPE"), octx)
    check("global WIPE clears everything", "wiped everything" in page(octx, OWN))

    # inbox + logs + refresh + search + broadcast
    q, ok = await tap(octx, "oir:contact:7", who=OWN, username="owner")
    check("inbox mark-read works + toast", ok and q.answers[-1] == "marked read")
    q, ok = await tap(octx, "oid:contact:7", who=OWN, username="owner")
    check("inbox delete works", ok and q.answers[-1] == "deleted")
    q, ok = await tap(octx, "oira:contact", who=OWN, username="owner")
    check("mark all read works", ok)
    q, ok = await tap(octx, "olg", who=OWN, username="owner")
    check("logs render + refresh", ok and "Working" in page(octx, OWN))
    q, ok = await tap(octx, "osr", who=OWN, username="owner")
    check("search arms text mode", ok and octx.user_data.get("mode") == "search_user")
    await handlers_text.process_text(TextUpdate(OWN, "4242"), octx)
    check("search opens card", "rep      7" in page(octx, OWN))
    q, ok = await tap(octx, "ost", who=OWN, username="owner")
    check("refresh returns panel", ok and _sc("Owner core") in page(octx, OWN))

    # broadcast flow (owner): background job + receipt, no blocking
    bctx = FakeCtx()
    q, ok = await tap(bctx, "obc", who=OWN, username="owner")
    check("broadcast prompt armed", bctx.user_data.get("mode") == "broadcast")
    await handlers_text.process_text(TextUpdate(OWN, "new stock in every pool"), bctx)
    check("broadcast launched in background", bctx.bot_data.get("bc_running") is True)
    await asyncio.sleep(0.3)
    check("broadcast receipt delivered", bctx.bot_data.get("bc_running") is False)

    # member text flows unchanged
    mctx = FakeCtx()
    await tap(mctx, "mw")
    check("write-mode prompt armed", mctx.user_data.get("mode") == "write_msg")
    await handlers_text.process_text(TextUpdate(UID, "i want elite please"), mctx)
    check("contact text flow completes", mctx.user_data.get("mode") is None)
    member_sends = [t for t, c in mctx.bot.sent if c == UID]
    check("contact flow: no new message to member", len(member_sends) == 0)
    check("contact flow: prompt edited", len(mctx.bot.edited) >= 1)

    # per-chat lock: a second tap while one is in flight waits (no double pull)
    lock_ok = await double_tap_check()
    check("per-chat lock serialises taps", lock_ok)


async def double_tap_check() -> bool:
    """Two concurrent 'g:vpn' taps from ONE chat must serialise: the second
    only runs after the first finished (no overlapping edits on one msg)."""
    import bot as bot_mod

    ctx = FakeCtx()
    order: list[str] = []
    real_serve = store.serve_claim

    async def slow_serve(*a, **k):
        order.append("start")
        await asyncio.sleep(0.05)
        r = await real_serve(*a, **k)
        order.append("end")
        return r

    store.serve_claim = slow_serve
    try:
        await asyncio.gather(
            bot_mod.route_callback(FakeUpdate(FakeQuery("g:vpn")), ctx),
            bot_mod.route_callback(FakeUpdate(FakeQuery("g:vpn")), ctx),
        )
    finally:
        store.serve_claim = real_serve
    return order == ["start", "end", "start", "end"]


async def router_audit(all_cbs: dict[str, set[str]]) -> None:
    """Every callback any page renders must be handled — no silent branch."""
    import bot as bot_mod

    for name, cbs in all_cbs.items():
        owner_page = name.startswith(("owner_", "vault_manager"))
        for cb in cbs:
            who = OWN if owner_page else UID
            ctx = FakeCtx()
            q = FakeQuery(cb, who=who)
            handled = await bot_mod.route_callback(FakeUpdate(q), ctx)
            check(f"route handled {name}:{cb}", bool(handled), f"{name} → {cb}")
            if who == OWN:
                check(f"{name}:{cb} answered", len(q.answers) >= 1)


async def main() -> int:
    slug_checks()
    constant_sync_checks()
    all_cbs = await render_views()
    await store_sql_checks()
    await tap_flows()
    await router_audit(all_cbs)
    print(f"\n=== {len(PROBLEMS)} problem(s) ===")
    for p in PROBLEMS:
        print(" -", p)
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
