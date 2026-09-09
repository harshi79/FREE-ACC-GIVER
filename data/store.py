"""
Sᴛᴏʀᴇ ────────
Every read/write the bot performs against the database, grouped by
domain. Handlers never touch SQL directly and never stack multiple
round-trips where one will do ─ that single-connection batching is
what makes the bot feel instant.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import asyncpg

import config
from config import (
    INITIAL_REPUTATION,
    OWNER_ID,
    PLAN_COOLDOWN_MINUTES,
    PLAN_LIMITS,
)
from data import catalog
from data.db import db

log = logging.getLogger("store")

# ----------------------------------------------------------------------
# Mapping: short kind  ->  physical table names / columns
# Vault 2.0: rows inside each table are scoped to a pool (category).
# Claims NEVER fall back to another pool — the category filter is part
# of the claim itself.
# ----------------------------------------------------------------------
_STOCK = {
    "ep": {
        "table": "stock_emailpass",
        "history": "user_history_email",
        "cols": ("email", "password"),
        "word": "email",
    },
    "key": {
        "table": "stock_keys",
        "history": "user_history_key",
        "cols": ("key",),
        "word": "key",
    },
}

_FEEDBACK_WORD = {"ep": "email", "key": "key"}  # matches legacy logs


# ----------------------------------------------------------------------
# Small result objects
# ----------------------------------------------------------------------
@dataclass
class ServeResult:
    status: str                 # ok | cooldown | limit | empty | banned
    plan: str = "free"
    daily: int = 0
    limit: int | None = None
    wait_sec: int = 0
    item: dict[str, Any] | None = None
    pool_label: str = ""        # vault 2.0: the pool this drop came from


@dataclass
class FeedbackResult:
    verdict: str
    rep_delta: int = 0
    new_rep: int | None = None
    banned: bool = False
    ban_reason: str = ""
    removed: dict[str, Any] | None = None
    removed_word: str = ""
    pool_label: str = ""        # pool the verdict refers to (shown on the card)
    item: dict[str, Any] | None = None   # dead reports keep the item data
    kept: bool = False           # dead but NOT deleted (auto-remove off)


@dataclass
class AddResult:
    added: int = 0
    failed: int = 0
    failed_lines: list[str] = field(default_factory=list)


def plan_limit(plan: str) -> int | None:
    return PLAN_LIMITS.get(plan, 5)


def plan_cooldown_minutes(plan: str) -> int:
    return PLAN_COOLDOWN_MINUTES.get(plan, 5)


# ======================================================================
#  USERS
# ======================================================================
async def ensure_user(uid: int, username: str | None, first_name: str | None) -> None:
    await db.execute(
        """
        INSERT INTO users (user_id, username, first_name, last_username, reputation)
        VALUES ($1, $2, $3, $2, $4)
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            last_username = EXCLUDED.username
        """,
        uid,
        username or "",
        first_name or "",
        INITIAL_REPUTATION,
    )


async def get_user(uid: int) -> asyncpg.Record | None:
    return await db.fetchrow("SELECT * FROM users WHERE user_id = $1", uid)


async def get_profile(uid: int) -> asyncpg.Record | None:
    """One round-trip profile: user row + today's usage + last generation."""
    return await db.fetchrow(
        """
        SELECT u.*, COALESCE(l.count, 0) AS today_count, l.last_gen AS last_gen
        FROM users u
        LEFT JOIN user_limits l
               ON l.user_id = u.user_id AND l.date = $2
        WHERE u.user_id = $1
        """,
        uid,
        date.today(),
    )


async def banned_flag(uid: int) -> bool:
    val = await db.fetchval("SELECT is_banned FROM users WHERE user_id = $1", uid)
    return bool(val)


async def get_user_by_username(uname: str) -> asyncpg.Record | None:
    """Find a user by @username (or raw name)."""
    name = uname.lstrip("@").strip()
    if not name:
        return None
    return await db.fetchrow(
        "SELECT * FROM users WHERE LOWER(username) = LOWER($1) OR LOWER(last_username) = LOWER($1) LIMIT 1",
        name,
    )


async def set_plan(uid: int, plan: str) -> None:
    await db.execute("UPDATE users SET plan = $1 WHERE user_id = $2", plan, uid)


async def add_rep(uid: int, delta: int) -> int | None:
    return await db.fetchval(
        "UPDATE users SET reputation = reputation + $1 WHERE user_id = $2 RETURNING reputation",
        delta,
        uid,
    )


async def set_rep(uid: int, value: int) -> None:
    await db.execute("UPDATE users SET reputation = $1 WHERE user_id = $2", value, uid)


async def ban(uid: int, reason: str = "No reason provided") -> None:
    await db.execute(
        "UPDATE users SET is_banned = TRUE, ban_reason = $1 WHERE user_id = $2", reason, uid
    )


async def unban(uid: int) -> None:
    await db.execute("UPDATE users SET is_banned = FALSE, ban_reason = NULL WHERE user_id = $1", uid)


async def user_count() -> int:
    return int(await db.fetchval("SELECT COUNT(*) FROM users") or 0)


async def users_page(page: int, size: int = 10) -> list[asyncpg.Record]:
    """One page of users with their today-count baked in (2 fast queries)."""
    offset = max(0, (page - 1) * size)
    users = await db.fetch(
        """
        SELECT user_id, username, first_name, plan, reputation, is_banned,
               total_gens, joined_at
        FROM users
        ORDER BY joined_at DESC, user_id DESC
        LIMIT $1 OFFSET $2
        """,
        size,
        offset,
    )
    if not users:
        return []
    ids = [u["user_id"] for u in users]
    today = date.today()
    counts = {
        r["user_id"]: r["count"]
        for r in await db.fetch(
            "SELECT user_id, count FROM user_limits WHERE date = $1 AND user_id = ANY($2::bigint[])",
            today,
            ids,
        )
    }
    for u in users:
        u["today_count"] = counts.get(u["user_id"], 0)
    return users


async def banned_users() -> list[asyncpg.Record]:
    return await db.fetch(
        "SELECT user_id, username, first_name, ban_reason FROM users WHERE is_banned = TRUE"
    )


async def all_user_ids() -> list[int]:
    rows = await db.fetch("SELECT user_id FROM users")
    return [r["user_id"] for r in rows]


# ======================================================================
#  PLANS / QUOTA + SERVING  (the hot path — one connection, few queries)
# ======================================================================
async def serve_claim(
    uid: int,
    username: str | None,
    first_name: str | None,
    kind: str,
    category: str,
    *,
    owner: bool = False,
    pool_label: str = "",
) -> ServeResult:
    """Serve exactly ONE item from exactly ONE pool (never a fallback)."""
    meta = _STOCK[kind]
    table, history = meta["table"], meta["history"]
    today = date.today()
    now = datetime.now()

    async with db.conn() as conn:
        # 1) keep the user fresh
        await conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_username, reputation)
            VALUES ($1, $2, $3, $2, $4)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_username = EXCLUDED.username
            """,
            uid,
            username or "",
            first_name or "",
            INITIAL_REPUTATION,
        )

        # 2) plan + gates (owner bypasses everything)
        u = await conn.fetchrow("SELECT plan, is_banned FROM users WHERE user_id = $1", uid)
        if u is None:
            return ServeResult(status="banned", plan="free")
        plan = u["plan"] or "free"
        if u["is_banned"]:
            return ServeResult(status="banned", plan=plan)

        daily = 0
        if not owner:
            cooldown_min = plan_cooldown_minutes(plan)
            if cooldown_min > 0:
                last_gen = await conn.fetchval(
                    "SELECT last_gen FROM user_limits WHERE user_id = $1 AND date = $2",
                    uid,
                    today,
                )
                if last_gen is not None:
                    elapsed = (now - last_gen).total_seconds()
                    if elapsed < cooldown_min * 60:
                        wait = int(cooldown_min * 60 - elapsed) + 1
                        return ServeResult(
                            status="cooldown", plan=plan, wait_sec=wait, pool_label=pool_label
                        )

            lim = plan_limit(plan)
            if lim is not None:
                daily = int(
                    await conn.fetchval(
                        "SELECT count FROM user_limits WHERE user_id = $1 AND date = $2",
                        uid,
                        today,
                    )
                    or 0
                )
                if daily >= lim:
                    return ServeResult(
                        status="limit", plan=plan, daily=daily, limit=lim, pool_label=pool_label
                    )

        # 3) claim one untouched item from THIS POOL ONLY + record it,
        #    atomically — an exhausted pool never borrows from another
        async with conn.transaction():
            cols = meta["cols"]
            select_cols = ", ".join(f"s.{c}" for c in ("id", "category") + cols)
            row = await conn.fetchrow(
                f"""
                SELECT {select_cols}
                FROM {table} s
                LEFT JOIN {history} h ON h.item_id = s.id AND h.user_id = $1
                WHERE h.item_id IS NULL AND s.category = $2
                ORDER BY s.id
                LIMIT 1
                FOR UPDATE OF s SKIP LOCKED
                """,
                uid,
                category,
            )
            if row is None:
                return ServeResult(
                    status="empty", plan=plan, daily=daily, limit=plan_limit(plan),
                    pool_label=pool_label,
                )

            item = dict(row)
            item["kind"] = kind
            item["pool_label"] = pool_label
            item_id = item["id"]

            await conn.execute(
                f"INSERT INTO {history} (user_id, item_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                uid,
                item_id,
            )
            await conn.execute(
                """
                INSERT INTO user_limits (user_id, date, count, last_gen)
                VALUES ($1, $2, 1, $3)
                ON CONFLICT (user_id, date) DO UPDATE SET
                    count = user_limits.count + 1,
                    last_gen = EXCLUDED.last_gen
                """,
                uid,
                today,
                now,
            )
            await conn.execute(
                "UPDATE users SET total_gens = total_gens + 1 WHERE user_id = $1", uid
            )

        # 4) the user's fresh daily number for the result card
        daily = int(
            await conn.fetchval(
                "SELECT count FROM user_limits WHERE user_id = $1 AND date = $2", uid, today
            )
            or 0
        )
        return ServeResult(
            status="ok", plan=plan, daily=daily, limit=plan_limit(plan),
            item=item, pool_label=pool_label,
        )


# ======================================================================
#  STOCK MAINTENANCE
# ======================================================================
async def stock_counts() -> dict[str, int]:
    row = await db.fetchrow(
        """
        SELECT
          (SELECT COUNT(*) FROM stock_emailpass) AS ep,
          (SELECT COUNT(*) FROM stock_keys)     AS keys
        """
    )
    return {"ep": int(row["ep"]), "key": int(row["keys"])}


# ── pool registry (vault 2.0) ──────────────────────────────────
_POOL_ORDER_SQL = (
    "ORDER BY CASE kind WHEN 'ep' THEN 0 ELSE 1 END, pos, label"
)


async def vault_categories() -> list[asyncpg.Record]:
    """The whole registry, accounts pools first then key pools, in pos order."""
    return await db.fetch(
        f"SELECT category, label, kind, pos FROM vault_categories {_POOL_ORDER_SQL}"
    )


async def pool_counts() -> list[asyncpg.Record]:
    """Live per-pool counts across both kinds in ONE query (GROUP BY)."""
    return await db.fetch(
        """
        SELECT 'ep' AS kind, category, COUNT(*) AS n FROM stock_emailpass GROUP BY category
        UNION ALL
        SELECT 'key' AS kind, category, COUNT(*) AS n FROM stock_keys GROUP BY category
        """
    )


async def create_pool(label: str, kind: str) -> tuple[str, str]:
    """
    Register a brand-new pool. Returns (category, error) — error is one of
    "" | "bad_name" | "name_exists" | "busy". Slug collisions (different
    name, same slug) are resolved with a numeric suffix.
    """
    clean = " ".join((label or "").split())[:60]
    base = catalog.slugify(clean)
    if not clean or not base:
        return "", "bad_name"
    existing = await vault_categories()
    if catalog.label_key(clean) in {catalog.label_key(r["label"]) for r in existing}:
        return "", "name_exists"
    taken = {r["category"] for r in existing}
    slug, _ = catalog.free_slug(base, taken)
    if not slug:
        return "", "busy"
    pos = max((r["pos"] for r in existing if r["kind"] == kind), default=-1) + 1
    await db.execute(
        "INSERT INTO vault_categories (category, label, kind, pos) VALUES ($1, $2, $3, $4)",
        slug,
        clean,
        kind,
        pos,
    )
    return slug, ""


# ── per-pool stock operations ────────────────────────────────────
async def add_items(uid: int, kind: str, category: str, lines: list[str]) -> AddResult:
    meta = _STOCK[kind]
    table = meta["table"]
    cols = meta["cols"]
    out = AddResult()
    async with db.conn() as conn:
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            values = [part.strip() for part in line.split(":", 1)] if len(cols) > 1 else [line]
            if len(values) != len(cols) or any(not v for v in values):
                out.failed += 1
                out.failed_lines.append(line)
                continue
            try:
                placeholders = ", ".join(
                    "$" + str(i) for i in range(1, len(cols) + 2)
                )
                await conn.execute(
                    f"INSERT INTO {table} ({', '.join(cols)}, category, added_by) "
                    f"VALUES ({placeholders}, ${len(cols) + 2})",
                    *values,
                    category,
                    uid,
                )
                out.added += 1
            except asyncpg.UniqueViolationError:
                out.failed += 1
                out.failed_lines.append(line)
            except asyncpg.PostgresError:
                out.failed += 1
                out.failed_lines.append(line)
    return out


async def remove_item(kind: str, category: str, item_id: int) -> dict[str, Any] | None:
    """
    Remove one row BY ID, scoped to its pool (an id living in another pool
    is not touched). Also clears the served-history references so the id is
    fully gone. Returns the removed row (for the toast) or None.
    """
    meta = _STOCK[kind]
    table, history = meta["table"], meta["history"]
    cols = ", ".join(("id", "category") + meta["cols"])
    async with db.conn() as conn:
        row = await conn.fetchrow(
            f"SELECT {cols} FROM {table} WHERE id = $1 AND category = $2",
            item_id,
            category,
        )
        if row is None:
            return None
        await conn.execute(f"DELETE FROM {table} WHERE id = $1", item_id)
        await conn.execute(f"DELETE FROM {history} WHERE item_id = $1", item_id)
        return dict(row)


async def reset_pool(kind: str, category: str) -> int:
    """Wipe one pool only — stock + its served-history references. Returns count."""
    meta = _STOCK[kind]
    table, history = meta["table"], meta["history"]
    async with db.conn() as conn:
        n = int(
            await conn.fetchval(
                f"SELECT COUNT(*) FROM {table} WHERE category = $1", category
            )
            or 0
        )
        await conn.execute(
            f"DELETE FROM {history} WHERE item_id IN (SELECT id FROM {table} WHERE category = $1)",
            category,
        )
        await conn.execute(f"DELETE FROM {table} WHERE category = $1", category)
        return n


async def reset_all_stock() -> None:
    async with db.conn() as conn:
        await conn.execute("DELETE FROM stock_emailpass")
        await conn.execute("DELETE FROM stock_keys")
        await conn.execute("DELETE FROM user_history_email")
        await conn.execute("DELETE FROM user_history_key")


async def export_stock() -> tuple[str, int, int]:
    """Full export, sectioned PER POOL so nothing is ever mixed up."""
    pools = {r["category"]: r["label"] for r in await vault_categories()}
    ep_rows = await db.fetch(
        "SELECT category, email, password FROM stock_emailpass ORDER BY category, id"
    )
    key_rows = await db.fetch("SELECT category, key FROM stock_keys ORDER BY category, id")
    parts: list[str] = []

    def emit(header: str, rows: list[str]) -> None:
        parts.append(header)
        parts.extend(rows)

    for cat in dict.fromkeys([r["category"] for r in ep_rows] + [r["category"] for r in key_rows]):
        cat_ep = [f"{r['email']}:{r['password']}" for r in ep_rows if r["category"] == cat]
        cat_key = [r["key"] for r in key_rows if r["category"] == cat]
        if not cat_ep and not cat_key:
            continue
        emit(f"── {pools.get(cat, cat)}  ({len(cat_ep) + len(cat_key)})", [])
        if cat_ep:
            emit("email:pass:", cat_ep)
        if cat_key:
            emit("keys:", cat_key)
    return "\n".join(parts), len(ep_rows), len(key_rows)


async def export_pool(kind: str, category: str) -> tuple[str, int]:
    """Export one pool only. Returns (content, count)."""
    meta = _STOCK[kind]
    table = meta["table"]
    cols = meta["cols"]
    select_cols = ", ".join(cols)
    rows = await db.fetch(
        f"SELECT {select_cols} FROM {table} WHERE category = $1 ORDER BY id", category
    )
    if kind == "ep":
        lines = [f"{r['email']}:{r['password']}" for r in rows]
    else:
        lines = [r["key"] for r in rows]
    return "\n".join(lines), len(lines)


# ======================================================================
#  FEEDBACK  (working / dead / skip)
# ======================================================================
async def record_feedback(
    uid: int,
    kind: str,
    item_id: int,
    verdict: str,
    *,
    owner: bool = False,
    category: str = "",
    pool_label: str = "",
) -> FeedbackResult:
    """
    Log a verdict for one item. DEAD reports are quiet bookkeeping: the
    row STAYS in its pool (kept=True) so the owner decides — unless
    config.AUTO_REMOVE_DEAD is on, which restores auto-pull.
    """
    meta = _STOCK[kind]
    table, history = meta["table"], meta["history"]
    word = meta["word"]
    res = FeedbackResult(verdict=verdict, pool_label=pool_label)

    async with db.conn() as conn:
        await conn.execute(
            """
            INSERT INTO feedback_log (user_id, item_type, item_id, feedback_type, served_at)
            VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
            """,
            uid,
            word,
            item_id,
            verdict,
        )

        if verdict == "dead":
            cols = ", ".join(("id", "category") + meta["cols"])
            row = await conn.fetchrow(
                f"SELECT {cols} FROM {table} WHERE id = $1", item_id
            )
            if row is not None:
                res.item = dict(row)
                if not res.pool_label:
                    res.pool_label = str(
                        await conn.fetchval(
                            "SELECT label FROM vault_categories WHERE category = $1",
                            row["category"],
                        )
                        or row["category"]
                    )
                if config.AUTO_REMOVE_DEAD:
                    await conn.execute(f"DELETE FROM {table} WHERE id = $1", item_id)
                    await conn.execute(f"DELETE FROM {history} WHERE item_id = $1", item_id)
                    res.removed = dict(row)
                    res.removed_word = word
                else:
                    res.kept = True     # never auto-removed — owner reviews
        elif verdict == "working":
            new_rep = await conn.fetchval(
                "UPDATE users SET reputation = reputation + 1 "
                "WHERE user_id = $1 RETURNING reputation",
                uid,
            )
            res.rep_delta = 1
            res.new_rep = new_rep
        elif verdict == "skip" and not owner:
            new_rep = await conn.fetchval(
                "UPDATE users SET reputation = reputation - 1 "
                "WHERE user_id = $1 RETURNING reputation",
                uid,
            )
            res.rep_delta = -1
            res.new_rep = new_rep
            if new_rep is not None and new_rep <= 0:
                await conn.execute(
                    "UPDATE users SET is_banned = TRUE, ban_reason = $1 WHERE user_id = $2",
                    "Reputation dropped to 0 (skipped feedback)",
                    uid,
                )
                res.banned = True
                res.ban_reason = "Reputation dropped to 0 (skipped feedback)"
    return res


async def feedback_log(limit: int = 12) -> list[asyncpg.Record]:
    return await db.fetch(
        """
        SELECT f.user_id, f.item_type, f.item_id, f.feedback_type, f.feedback_at,
               u.username, u.first_name
        FROM feedback_log f
        LEFT JOIN users u ON u.user_id = f.user_id
        ORDER BY f.feedback_at DESC
        LIMIT $1
        """,
        limit,
    )


# ======================================================================
#  MAILBOX  (hit reports + contact messages for the owner)
# ======================================================================
_MAILBOX_SQL = {
    "hit": {
        "table": "hit_reports",
        "label": "Hit report",
    },
    "contact": {
        "table": "contact_messages",
        "label": "Contact message",
    },
}


async def mailbox_add(kind: str, uid: int, content: str) -> int:
    table = _MAILBOX_SQL[kind]["table"]
    return int(
        await db.fetchval(
            f"INSERT INTO {table} (user_id, content) VALUES ($1, $2) RETURNING id",
            uid,
            content,
        )
    )


async def mailbox_unread(kind: str, limit: int = 12) -> list[asyncpg.Record]:
    table = _MAILBOX_SQL[kind]["table"]
    return await db.fetch(
        f"""
        SELECT m.id, m.user_id, m.content, m.sent_at,
               u.username, u.first_name
        FROM {table} m
        LEFT JOIN users u ON u.user_id = m.user_id
        WHERE m.is_read = FALSE
        ORDER BY m.id DESC
        LIMIT $1
        """,
        limit,
    )


async def mailbox_unread_counts() -> dict[str, int]:
    row = await db.fetchrow(
        """
        SELECT
          (SELECT COUNT(*) FROM hit_reports WHERE is_read = FALSE)     AS hit,
          (SELECT COUNT(*) FROM contact_messages WHERE is_read = FALSE) AS contact
        """
    )
    return {"hit": int(row["hit"]), "contact": int(row["contact"])}


async def mailbox_mark_read(kind: str, item_id: int) -> None:
    table = _MAILBOX_SQL[kind]["table"]
    await db.execute(f"UPDATE {table} SET is_read = TRUE WHERE id = $1", item_id)


async def mailbox_mark_all_read(kind: str) -> int:
    table = _MAILBOX_SQL[kind]["table"]
    row = await db.fetchval(
        f"""
        WITH moved AS (
            UPDATE {table} SET is_read = TRUE WHERE is_read = FALSE RETURNING 1
        )
        SELECT COUNT(*) FROM moved
        """
    )
    return int(row or 0)


async def mailbox_delete(kind: str, item_id: int) -> None:
    table = _MAILBOX_SQL[kind]["table"]
    await db.execute(f"DELETE FROM {table} WHERE id = $1", item_id)


# ======================================================================
#  OWNER DASHBOARD NUMBERS
# ======================================================================
async def dashboard_stats() -> dict[str, Any]:
    today = date.today()
    row = await db.fetchrow(
        """
        SELECT
          (SELECT COUNT(*) FROM users)                                             AS users,
          (SELECT COUNT(*) FROM users WHERE is_banned = TRUE)                      AS banned,
          (SELECT COUNT(*) FROM stock_emailpass)                                   AS ep,
          (SELECT COUNT(*) FROM stock_keys)                                        AS keys,
          (SELECT COUNT(*) FROM user_limits WHERE date = $1)                       AS active_today,
          (SELECT COALESCE(SUM(count), 0) FROM user_limits WHERE date = $1)        AS serves_today,
          (SELECT COALESCE(SUM(total_gens), 0) FROM users)                         AS serves_total,
          (SELECT COUNT(*) FROM feedback_log WHERE feedback_type = 'dead')         AS dead_reports,
          (SELECT COUNT(*) FROM feedback_log WHERE feedback_type = 'working')      AS working_reports
        """,
        today,
    )
    plans = await db.fetch("SELECT plan, COUNT(*) AS n FROM users GROUP BY plan")
    return {
        **{k: int(row[k]) for k in row.keys()},
        "plans": {r["plan"]: int(r["n"]) for r in plans},
    }


def is_owner(uid: int) -> bool:
    return uid == OWNER_ID
