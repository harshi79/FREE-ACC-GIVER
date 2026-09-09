"""
Sᴇʟꜰᴛᴇꜱᴛ ────────
Offline harness: renders EVERY screen with a fake data layer and
verifies the invariants that keep the bot premium & fast:
  • every page text ≤ 4096 chars (Telegram limit)
  • every callback payload ≤ 64 bytes
  • no color-emoji leaks into rendered text
  • owner routes never resolve for non-owners
  • buttons edit the SAME message (no message spam)
Run:  .venv/bin/python -m tests.selftest
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, ".")

import config  # noqa: E402
import data.store as store  # noqa: E402
import core.cache as cache  # noqa: E402

EPOCH = datetime.now() - timedelta(days=3)
OWN = config.OWNER_ID
UID = 555


# ── fake data layer ─────────────────────────────────────────────
def _fake_profile(uid: int) -> dict:
    return {
        "user_id": uid, "username": "tester", "first_name": "Test User",
        "plan": "pro", "reputation": 7, "is_banned": False, "ban_reason": None,
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


async def _f_stock():
    return {"ep": 12, "key": 4}


async def _f_export():
    return "a@b.c:pw\nKEY-1", 1, 1


async def _noop(*_a, **_k):
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
store.add_items = _noop
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


async def _f_all_user_ids() -> list[int]:
    return [2, 3]


store.all_user_ids = _f_all_user_ids

cache.stock = _f_stock
cache.users = _f_user_count
cache.banned = _noop
cache.banned_mark = lambda *a, **k: None
cache.stock_mutate = lambda *a, **k: None
cache.stock_invalidate = lambda: None
cache.users_invalidate = lambda: None

# replace placeholder asyncs with meaningful ones for flows
async def _f_serve(uid, username, first_name, kind, *, owner=False):
    item = (
        {"id": 11, "kind": "ep", "email": "a@b.co", "password": "pw1"}
        if kind == "ep"
        else {"id": 5, "kind": "key", "key": "KEY-77"}
    )
    return store.ServeResult(status="ok", plan="pro", daily=3, limit=20, item=item)


async def _f_feedback(uid, kind, item_id, verdict, *, owner=False):
    return store.FeedbackResult(verdict=verdict, rep_delta=1, new_rep=8)


async def _f_add_items(uid, kind, lines):
    return store.AddResult(added=len(lines), failed=0)


async def _f_mailbox_add(kind, uid, content) -> int:
    return 1


store.serve_claim = _f_serve
store.record_feedback = _f_feedback
store.add_items = _f_add_items
store.mailbox_add = _f_mailbox_add

# ── verification helpers ────────────────────────────────────────
PROBLEMS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'ok' if ok else '!!'}] {label}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        PROBLEMS.append(f"{label}: {detail}")


EMOJI_FOOTPRINT = set(
    "😀😂🥺😎😈🤖👻🙏👍👎🙌💪🫶💀☠️❤️💙🔥✨⭐🌟💫⚡❄️☀️🌙🎉🎊🎁🚀"
    "📧📨📩💌🔑🗝️🔐📊📈📉👤👥✅❌⛔🚫⚠️❗❓❕➡️⬅️⬆️⬇️↗️↘️💬🗨️📢📣"
    "🕐⏳⏰🎯🧠🛡️💎🏆🥇🥈🥉♻️🔄↩️↪️☑️✔️✖️➕➖➗🆓🅿️🈁✈️🌐🔗🌊☁️🔥"
)


def emoji_leak(text: str) -> str | None:
    for ch in text:
        if ch in EMOJI_FOOTPRINT or ord(ch) >= 0x1F000:
            return ch
    return None


# ── render all views ────────────────────────────────────────────
async def render_views() -> None:
    from core import views

    # every entry is a callable: views mix async & sync builders, so we
    # call each and await only the coroutines.
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
        "write_prompt": lambda: views.text_mode_prompt("write_msg"),
        "hit_prompt": lambda: views.text_mode_prompt("hit_report"),
        "search_prompt": lambda: views.text_mode_prompt("search_user"),
        "bc_prompt": lambda: views.text_mode_prompt("broadcast"),
        "add_ep_prompt": lambda: views.text_mode_prompt("add_ep"),
        "add_key_prompt": lambda: views.text_mode_prompt("add_key"),
        "reset_confirm": lambda: views.reset_confirm(),
        "msg_sent": lambda: views.message_sent("contact"),
        "hit_sent": lambda: views.message_sent("hit"),
        "add_done": lambda: views.add_done("ep", 5, 2),
        "banned": lambda: views.banned_page("because"),
    }
    for plan in config.PLAN_ORDER:
        renderers[f"plan_detail:{plan}"] = lambda p=plan: views.plan_detail_page(p, UID)

    sr_ep = store.ServeResult(
        status="ok", plan="pro", daily=2, limit=20,
        item={"id": 9, "kind": "ep", "email": "x@y.com", "password": "pw"},
    )
    sr_key = store.ServeResult(
        status="ok", plan="pro", daily=2, limit=20, item={"id": 3, "kind": "key", "key": "ABCD-1234"},
    )
    sr_unlim = store.ServeResult(status="ok", plan="unlimited", daily=7, limit=None, item={"id": 4, "kind": "ep", "email": "u@y.com", "password": "p"})
    fb_ok = store.FeedbackResult(verdict="working", rep_delta=1, new_rep=8)
    fb_dead = store.FeedbackResult(verdict="dead", removed={"id": 9, "email": "x@y.com", "password": "pw"}, removed_word="email")
    fb_skip = store.FeedbackResult(verdict="skip", rep_delta=-1, new_rep=4)
    fb_ban = store.FeedbackResult(verdict="skip", rep_delta=-1, new_rep=0, banned=True, ban_reason="rep 0")
    cooldown = store.ServeResult(status="cooldown", plan="free", wait_sec=95)
    wall = store.ServeResult(status="limit", plan="free", daily=5, limit=5)
    renderers.update({
        "result_ep": lambda: views.result(sr_ep, owner=False),
        "result_ep_owner": lambda: views.result(sr_ep, owner=True),
        "result_key": lambda: views.result(sr_key, owner=False),
        "result_unlim": lambda: views.result(sr_unlim, owner=False),
        "feedback_working": lambda: views.feedback_done(fb_ok, "ep"),
        "feedback_dead": lambda: views.feedback_done(fb_dead, "ep"),
        "feedback_skip": lambda: views.feedback_done(fb_skip, "ep"),
        "feedback_banned": lambda: views.feedback_done(fb_ban, "ep"),
        "cooldown": lambda: views.cooldown(cooldown),
        "limit_wall": lambda: views.limit_wall(wall),
        "empty_ep": lambda: views.empty("ep"),
        "empty_key": lambda: views.empty("key"),
    })

    import inspect

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
        for row in rows:
            for b in row:
                if b.callback_data:
                    check(
                        f"render {name} payload ≤64",
                        len(b.callback_data.encode()) <= 64,
                        f"{b.callback_data!r} len={len(b.callback_data.encode())}",
                    )
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


# ── simulated taps on ONE message ──────────────────────────────
class FakeBot:
    def __init__(self):
        self.sent: list[tuple[str, int]] = []
        self.edited: list[tuple[int, int]] = []

    async def send_message(self, chat_id, text, **_kw):
        self.sent.append((text, chat_id))
        return SimpleMessage(chat_id=chat_id, message_id=9000 + len(self.sent))

    async def edit_message_text(self, chat_id, message_id, text, **_kw):
        self.edited.append((chat_id, message_id))
        return SimpleMessage(chat_id=chat_id, message_id=message_id)


class SimpleMessage:
    def __init__(self, chat_id: int, message_id: int):
        self.chat_id = chat_id
        self.message_id = message_id

    async def reply_document(self, document, **_kw):
        return self


class FakeQuery:
    def __init__(self, data: str, who: int = UID, username: str = "tester"):
        self.data = data
        self.message = SimpleMessage(chat_id=who, message_id=1000)
        self.edits: list[str] = []
        self.answers: list[str] = []
        self.from_user = SimpleNamespace(id=who, username=username, first_name="Test User")

    async def answer(self, text=None, **_kw):
        self.answers.append(text or "")

    async def edit_message_text(self, text, reply_markup=None, **_kw):
        self.edits.append(text)
        return self.message


class FakeCtx:
    def __init__(self):
        self.user_data: dict = {}
        self.bot_data: dict = {}
        self.chat_data: dict = {}
        self.bot = FakeBot()


class FakeUpdate:
    def __init__(self, query: FakeQuery):
        self.callback_query = query
        self.effective_user = query.from_user
        self.effective_chat = SimpleNamespace(id=query.from_user.id)


async def tap_flows() -> None:
    import bot as bot_mod  # central router (answers + routes)

    async def tap(ctx: FakeCtx, data: str, who: int = UID, username: str = "tester") -> FakeQuery:
        q = FakeQuery(data, who=who, username=username)
        await bot_mod.route_callback(FakeUpdate(q), ctx)
        return q

    # member chain: home -> pull -> feedback — all edits, zero sends
    ctx = FakeCtx()
    q = await tap(ctx, "h")
    check("tap home renders once", len(q.edits) == 1, f"{len(q.edits)} edits")
    check("tap home: no extra message", len(ctx.bot.sent) == 0, f"{len(ctx.bot.sent)} sends")
    check("home answered (spinner off)", len(q.answers) == 1)

    q = await tap(ctx, "ge")
    check("tap pull: anim+result edits", len(q.edits) >= 2, f"{len(q.edits)} edits")
    check("pull shows credentials", "a@b.co" in q.edits[-1])
    check("pull: no extra message", len(ctx.bot.sent) == 0)

    q = await tap(ctx, "fw:ep:11")
    check("feedback edits to card", len(q.edits) >= 1 and "marked working" in q.edits[-1].lower())
    check("feedback toast", q.answers and q.answers[0] == "+1 rep")

    # normal user taps an owner code: must never render the panel
    ctx2 = FakeCtx()
    q2 = await tap(ctx2, "op")
    joined = "\n".join(q2.edits) + "\n" + "\n".join(t for t, _ in ctx2.bot.sent)
    check("owner panel hidden from user", "plan mix" not in joined and len(q2.edits) == 0)

    # owner taps the panel + drills around
    octx = FakeCtx()
    oq = await tap(octx, "op", who=OWN, username="owner")
    check("owner panel rendered", len(oq.edits) == 1 and "plan mix" in oq.edits[-1])

    oq = await tap(octx, "oup:2", who=OWN, username="owner")
    check("owner users page rendered", "today" in oq.edits[-1] or "vault is empty" in oq.edits[-1])

    oq = await tap(octx, "oum:4444", who=OWN, username="owner")
    check("owner manage page rendered", "pulls" in oq.edits[-1])

    oq = await tap(octx, "opn:4444:elite", who=OWN, username="owner")
    check("owner plan change rendered", "pulls" in oq.edits[-1])

    oq = await tap(octx, "oib:contact:0", who=OWN, username="owner")
    check("owner inbox rendered", "sender" in oq.edits[-1])

    oq = await tap(octx, "oir:contact:7", who=OWN, username="owner")
    check("owner inbox mark-read rendered", "sender" in oq.edits[-1])

    # text-mode entry for a member
    mctx = FakeCtx()
    await tap(mctx, "mw")
    check("write-mode prompt armed", mctx.user_data.get("mode") == "write_msg")

    from core import handlers_text

    msg = SimpleNamespace(text="i want elite please", chat_id=UID)

    class _TU:
        def __init__(self, chat_id):
            self.effective_user = SimpleNamespace(id=chat_id, username="tester", first_name="T")
            self.effective_chat = SimpleNamespace(id=chat_id)
            self.message = msg

    await handlers_text.process_text(_TU(UID), mctx)
    check("contact text flow completes", mctx.user_data.get("mode") is None)
    # the only new message may be the ping to the OWNER, never to the member chat
    member_sends = [t for t, c in mctx.bot.sent if c == UID]
    check("contact flow: no new message to member", len(member_sends) == 0)
    check("contact flow: prompt edited", len(mctx.bot.edited) >= 1)

    # broadcast flow (owner): message launches a background job w/o blocking
    bctx = FakeCtx()
    await tap(bctx, "obc", who=OWN, username="owner")
    check("broadcast prompt armed", bctx.user_data.get("mode") == "broadcast")
    await handlers_text.process_text(_TU(OWN), bctx)
    check("broadcast launched in background", bctx.bot_data.get("bc_running") is True)
    await asyncio.sleep(0.3)
    check("broadcast receipt delivered", bctx.bot_data.get("bc_running") is False)


async def main() -> int:
    await render_views()
    await tap_flows()
    print(f"\n=== {len(PROBLEMS)} problem(s) ===")
    for p in PROBLEMS:
        print(" -", p)
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
