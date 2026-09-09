"""
Dᴀᴛᴀʙᴀꜱᴇ ᴄᴏʀᴇ ──────
Connection pool + schema bootstrap + tiny wrappers.

The whole DB layer talks through the single `db` singleton below.
Schema is identical to the previous bot (plus the old auto-migration),
so no existing user / stock / history data is lost on upgrade.
"""
from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

import config
from data import catalog

log = logging.getLogger("db")

_SCHEMA = [
    # users ----------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        plan TEXT DEFAULT 'free',
        reputation INT DEFAULT 5,
        is_banned BOOLEAN DEFAULT FALSE,
        ban_reason TEXT,
        total_gens INT DEFAULT 0,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_username TEXT
    )
    """,
    # stock ----------------------------------------------------------
    # Vault 2.0: every brand/service owns ONE pool; `category` scopes rows
    # to a pool and pools are never mixed. `stock_*` stay two physical
    # tables (one per kind), the registry lives in vault_categories.
    """
    CREATE TABLE IF NOT EXISTS stock_emailpass (
        id SERIAL PRIMARY KEY,
        email TEXT UNIQUE,
        password TEXT,
        category TEXT NOT NULL DEFAULT 'vpn',
        added_by BIGINT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_keys (
        id SERIAL PRIMARY KEY,
        key TEXT UNIQUE,
        category TEXT NOT NULL DEFAULT 'pc',
        added_by BIGINT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # pool registry (seeded + owner-extensible, no code change needed) --
    """
    CREATE TABLE IF NOT EXISTS vault_categories (
        category TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        kind TEXT NOT NULL,
        pos INT NOT NULL DEFAULT 0
    )
    """,
    # Category indexes are intentionally created by _migrate_vault2(),
    # after legacy stock tables have received their category columns.
    # Creating them here would fail startup on a pre-Vault-2 database.
    # per-user "never served twice" history --------------------------
    """
    CREATE TABLE IF NOT EXISTS user_history_email (
        user_id BIGINT,
        item_id INT,
        served_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, item_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_history_key (
        user_id BIGINT,
        item_id INT,
        served_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, item_id)
    )
    """,
    # daily counters --------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS user_limits (
        user_id BIGINT NOT NULL,
        date DATE NOT NULL,
        count INT DEFAULT 0,
        last_gen TIMESTAMP,
        PRIMARY KEY (user_id, date)
    )
    """,
    # feedback ---------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS feedback_log (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        item_type TEXT,
        item_id INT,
        feedback_type TEXT,
        served_at TIMESTAMP,
        feedback_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # hit reports ------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS hit_reports (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        content TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_read BOOLEAN DEFAULT FALSE
    )
    """,
    # contact messages ---------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS contact_messages (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        content TEXT,
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_read BOOLEAN DEFAULT FALSE
    )
    """,
]


class Database:
    def __init__(self, dsn: str | None = None) -> None:
        # Read the DSN lazily so environment-injected values (Render)
        # are picked up even when this module was imported earlier.
        self._dsn = dsn
        self.pool: asyncpg.Pool | None = None

    # ── lifecycle ────────────────────────────────────────────────────
    async def connect(self) -> None:
        if self.pool is not None:
            return
        dsn = self._dsn or config.DATABASE_URL
        if not dsn:
            raise RuntimeError("DATABASE_URL is not set (check environment variables).")
        last_exc: Exception | None = None
        for attempt in range(1, config.DB_CONNECT_MAX_ATTEMPTS + 1):
            try:
                self.pool = await asyncpg.create_pool(
                    dsn=dsn,
                    min_size=2,
                    max_size=12,
                    command_timeout=20,
                    timeout=15,
                )
                await self._bootstrap()
                log.info("Database connected and schema ready.")
                return
            except (socket.gaierror, OSError, asyncpg.PostgresError) as exc:
                last_exc = exc
                log.error("DB attempt %d failed: %s: %s", attempt, type(exc).__name__, exc)
            except Exception as exc:  # noqa: BLE001 - surface everything
                last_exc = exc
                log.exception("DB attempt %d failed unexpectedly", attempt)
            if attempt < config.DB_CONNECT_MAX_ATTEMPTS:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
        raise RuntimeError(
            f"Could not connect to the database after {config.DB_CONNECT_MAX_ATTEMPTS} attempts. "
            f"Last error: {last_exc!r}"
        ) from last_exc

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def _bootstrap(self) -> None:
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            for statement in _SCHEMA:
                await conn.execute(statement)
            await _migrate_user_limits(conn)
            await _migrate_vault2(conn)

    # ── low-level helpers ───────────────────────────────────────────
    @asynccontextmanager
    async def conn(self) -> AsyncIterator[asyncpg.Connection]:
        """Borrow one pooled connection."""
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            yield conn

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        async with self.conn() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        async with self.conn() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self.conn() as conn:
            return await conn.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        async with self.conn() as conn:
            return await conn.execute(query, *args)


# Global instance used everywhere.
db = Database()


async def _migrate_user_limits(conn: asyncpg.Connection) -> None:
    """Old builds shipped user_limits with PK (user_id); ensure (user_id, date)."""
    try:
        rows = await conn.fetch(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
            WHERE c.relname = 'user_limits' AND n.nspname = 'public' AND i.indisprimary
            ORDER BY a.attnum
            """
        )
        columns = [r["attname"] for r in rows]
        if columns == ["user_id", "date"]:
            return
        async with conn.transaction():
            await conn.execute("ALTER TABLE user_limits DROP CONSTRAINT IF EXISTS user_limits_pkey")
            await conn.execute("ALTER TABLE user_limits ALTER COLUMN date SET NOT NULL")
            await conn.execute(
                "ALTER TABLE user_limits ADD CONSTRAINT user_limits_pkey PRIMARY KEY (user_id, date)"
            )
        log.info("Migrated user_limits primary key to (user_id, date).")
    except Exception:  # noqa: BLE001
        log.exception("user_limits migration failed (non-fatal).")


async def _migrate_vault2(conn: asyncpg.Connection) -> None:
    """
    Vault 2.0 migration (idempotent, runs on every startup):

    1. add the `category` column to each stock table if absent — the
       DEFAULT backfills every legacy row into its legacy pool
       (old email:pass -> 'vpn', old keys -> 'pc') without touching
       per-user served history, which stays exactly as it was;
    2. seed the vault_categories registry (existing pools are kept).
    """
    try:
        for table, default_cat in (("stock_emailpass", "vpn"), ("stock_keys", "pc")):
            has = await conn.fetchval(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1 AND column_name = 'category'
                """,
                table,
            )
            if has is None:
                await conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN category TEXT NOT NULL "
                    f"DEFAULT '{default_cat}'"
                )
                log.info("Vault 2.0: %s.category added (legacy rows -> '%s').", table, default_cat)
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_category ON {table} (category)"
            )
        for category, label, kind, pos in catalog.seed_sql():
            await conn.execute(
                """
                INSERT INTO vault_categories (category, label, kind, pos)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (category) DO NOTHING
                """,
                category,
                label,
                kind,
                pos,
            )
    except Exception:  # noqa: BLE001
        log.exception("Vault 2.0 migration failed (non-fatal).")
