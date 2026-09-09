import os
import socket
import logging
import asyncio
import tempfile
from datetime import datetime, date
from typing import Dict, List, Optional
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes
)
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.error import (
    RetryAfter, TimedOut, NetworkError, BadRequest
)

# ─── Configuration ──────────────────────────────────────────────
BOT_TOKEN = "8819857671:AAFgoU1ij4m7h1MWI-9iMRVjrQja4H1vuQY"
OWNER_ID = 7728424218
ADMIN_IDS = [OWNER_ID]
DATABASE_URL = "postgresql://neondb_owner:npg_vlXzsQ7n2VZg@ep-sweet-smoke-b3rtnp1f-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
DAILY_LIMIT = 5
COOLDOWN_MINUTES = 5
INITIAL_REPUTATION = 5

# ─── Network reliability tuning ─────────────────────────────────
POLL_TIMEOUT = 10
REQUEST_READ_TIMEOUT = 30.0
REQUEST_WRITE_TIMEOUT = 30.0
REQUEST_CONNECT_TIMEOUT = 10.0
REQUEST_POOL_TIMEOUT = 10.0
GET_UPDATES_READ_TIMEOUT = 35.0
MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.5
DB_CONNECT_MAX_ATTEMPTS = 6
DB_CONNECT_RETRY_BASE_DELAY = 2.0

# ─── Logging ─────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Database ────────────────────────────────────────────────────
class Database:
    def __init__(self):
        self.pool = None

    async def initialize(self):
        if self.pool is not None:
            return
        last_exc = None
        for attempt in range(1, DB_CONNECT_MAX_ATTEMPTS + 1):
            try:
                self.pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
                await self._create_tables()
                logger.info("Database connected and tables ready.")
                return
            except socket.gaierror as e:
                last_exc = e
                logger.error("Database host could not be resolved (DNS failure): %s", e)
            except OSError as e:
                last_exc = e
                logger.error("Database connection failed (network/OS error): %s", e)
            except asyncpg.PostgresError as e:
                last_exc = e
                logger.error("Database rejected the connection: %s", e)
            except Exception as e:
                last_exc = e
                logger.error("Database connection failed unexpectedly: %s", type(e).__name__)
            if attempt < DB_CONNECT_MAX_ATTEMPTS:
                delay = DB_CONNECT_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "Retrying database connection in %.1fs (attempt %d/%d)...",
                    delay, attempt, DB_CONNECT_MAX_ATTEMPTS
                )
                await asyncio.sleep(delay)
        if isinstance(last_exc, socket.gaierror):
            raise RuntimeError(
                "Could not resolve the database host. Check: (1) internet connection, "
                "(2) run `ipconfig /flushdns`, (3) disable VPN/firewall temporarily, "
                "(4) verify Neon console. "
                f"(Original error: {last_exc})"
            ) from last_exc
        if isinstance(last_exc, OSError):
            raise RuntimeError(
                "Could not reach the database. Check Neon is running and port 5432 is reachable. "
                f"(Original error: {last_exc})"
            ) from last_exc
        raise RuntimeError(
            f"Failed to connect to database after {DB_CONNECT_MAX_ATTEMPTS} attempts. "
            f"(Last error: {last_exc!r})"
        ) from last_exc

    async def _create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
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
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stock_emailpass (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE,
                    password TEXT,
                    added_by BIGINT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stock_keys (
                    id SERIAL PRIMARY KEY,
                    key TEXT UNIQUE,
                    added_by BIGINT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_history_email (
                    user_id BIGINT,
                    item_id INT,
                    served_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, item_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_history_key (
                    user_id BIGINT,
                    item_id INT,
                    served_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, item_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_limits (
                    user_id BIGINT NOT NULL,
                    date DATE NOT NULL,
                    count INT DEFAULT 0,
                    last_gen TIMESTAMP,
                    PRIMARY KEY (user_id, date)
                )
            """)
            await self._migrate_user_limits(conn)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback_log (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    item_type TEXT,
                    item_id INT,
                    feedback_type TEXT,
                    served_at TIMESTAMP,
                    feedback_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS hit_reports (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    content TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_read BOOLEAN DEFAULT FALSE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS contact_messages (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    content TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_read BOOLEAN DEFAULT FALSE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id BIGINT PRIMARY KEY
                )
            """)
            await conn.execute("""
                INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING
            """, OWNER_ID)

    async def _migrate_user_limits(self, conn):
        try:
            rows = await conn.fetch("""
                SELECT a.attname
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a
                  ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
                WHERE c.relname = 'user_limits'
                  AND n.nspname = 'public'
                  AND i.indisprimary
                ORDER BY a.attnum
            """)
            columns = [r["attname"] for r in rows]
            if columns == ["user_id", "date"]:
                return
            async with conn.transaction():
                await conn.execute(
                    "ALTER TABLE user_limits DROP CONSTRAINT IF EXISTS user_limits_pkey"
                )
                await conn.execute("ALTER TABLE user_limits ALTER COLUMN date SET NOT NULL")
                await conn.execute(
                    "ALTER TABLE user_limits ADD CONSTRAINT user_limits_pkey "
                    "PRIMARY KEY (user_id, date)"
                )
            logger.info("Migrated user_limits primary key to (user_id, date).")
        except Exception:
            logger.exception("Failed to migrate user_limits primary key.")

    async def get_user(self, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

    async def create_user(self, user_id: int, username: str, first_name: str):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, username, first_name, last_username)
                VALUES ($1, $2, $3, $2)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_username = EXCLUDED.username
            """, user_id, username or "", first_name or "")

    async def update_username(self, user_id: int, username: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET username = $2, last_username = $2 WHERE user_id = $1",
                user_id, username or ""
            )

    async def get_reputation(self, user_id: int) -> int:
        user = await self.get_user(user_id)
        return user["reputation"] if user else INITIAL_REPUTATION

    async def add_reputation(self, user_id: int, amount: int):
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(
                "UPDATE users SET reputation = reputation + $1 WHERE user_id = $2 RETURNING reputation",
                amount, user_id
            )
            return result

    async def set_reputation(self, user_id: int, value: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET reputation = $1 WHERE user_id = $2",
                value, user_id
            )

    async def get_plan(self, user_id: int) -> str:
        user = await self.get_user(user_id)
        return user["plan"] if user else "free"

    async def set_plan(self, user_id: int, plan: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET plan = $1 WHERE user_id = $2",
                plan, user_id
            )

    async def is_admin(self, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM admins WHERE user_id = $1)", user_id
            )

    async def get_admins(self) -> List[int]:
        async with self.pool.acquire() as conn:
            return [r["user_id"] for r in await conn.fetch("SELECT user_id FROM admins")]

    async def add_admin(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)

    async def remove_admin(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)

    async def is_banned(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return user["is_banned"] if user else False

    async def ban_user(self, user_id: int, reason: str = "No reason provided"):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_banned = TRUE, ban_reason = $1 WHERE user_id = $2",
                reason, user_id
            )

    async def unban_user(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_banned = FALSE, ban_reason = NULL WHERE user_id = $1",
                user_id
            )

    async def get_banned_users(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT user_id, username, ban_reason FROM users WHERE is_banned = TRUE")

    async def get_daily_count(self, user_id: int) -> int:
        today = date.today()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT count FROM user_limits WHERE user_id = $1 AND date = $2",
                user_id, today
            )
            return row["count"] if row else 0

    async def increment_daily_count(self, user_id: int):
        today = date.today()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_limits (user_id, date, count, last_gen)
                VALUES ($1, $2, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (user_id, date) DO UPDATE SET
                    count = user_limits.count + 1,
                    last_gen = CURRENT_TIMESTAMP
            """, user_id, today)

    async def get_last_gen(self, user_id: int) -> Optional[datetime]:
        today = date.today()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT last_gen FROM user_limits WHERE user_id = $1 AND date = $2",
                user_id, today
            )
            return row["last_gen"] if row else None

    async def add_emailpass(self, email: str, password: str, admin_id: int) -> bool:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO stock_emailpass (email, password, added_by) VALUES ($1, $2, $3)",
                    email, password, admin_id
                )
                return True
        except Exception:
            logger.exception("Failed to add emailpass")
            return False

    async def add_key(self, key: str, admin_id: int) -> bool:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO stock_keys (key, added_by) VALUES ($1, $2)",
                    key, admin_id
                )
                return True
        except Exception:
            logger.exception("Failed to add key")
            return False

    async def get_emailpass(self, user_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("""
                    SELECT s.id, s.email, s.password
                    FROM stock_emailpass s
                    LEFT JOIN user_history_email h
                           ON h.item_id = s.id AND h.user_id = $1
                    WHERE h.item_id IS NULL
                    ORDER BY s.id
                    LIMIT 1
                    FOR UPDATE OF s SKIP LOCKED
                """, user_id)
                if not row:
                    return None
                await conn.execute(
                    "INSERT INTO user_history_email (user_id, item_id) "
                    "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    user_id, row["id"]
                )
                return dict(row)

    async def get_key(self, user_id: int) -> Optional[Dict]:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow("""
                    SELECT s.id, s.key
                    FROM stock_keys s
                    LEFT JOIN user_history_key h
                           ON h.item_id = s.id AND h.user_id = $1
                    WHERE h.item_id IS NULL
                    ORDER BY s.id
                    LIMIT 1
                    FOR UPDATE OF s SKIP LOCKED
                """, user_id)
                if not row:
                    return None
                await conn.execute(
                    "INSERT INTO user_history_key (user_id, item_id) "
                    "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    user_id, row["id"]
                )
                return dict(row)

    async def get_stock_count(self) -> Dict:
        async with self.pool.acquire() as conn:
            emails = await conn.fetchval("SELECT COUNT(*) FROM stock_emailpass")
            keys = await conn.fetchval("SELECT COUNT(*) FROM stock_keys")
            return {"emails": emails, "keys": keys}

    async def remove_emailpass(self, item_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM stock_emailpass WHERE id = $1", item_id)
            return result != "DELETE 0"

    async def remove_key(self, item_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute("DELETE FROM stock_keys WHERE id = $1", item_id)
            return result != "DELETE 0"

    async def reset_stock(self):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM stock_emailpass")
            await conn.execute("DELETE FROM stock_keys")
            await conn.execute("DELETE FROM user_history_email")
            await conn.execute("DELETE FROM user_history_key")

    async def export_stock(self) -> str:
        async with self.pool.acquire() as conn:
            emails = await conn.fetch("SELECT email, password FROM stock_emailpass")
            keys = await conn.fetch("SELECT key FROM stock_keys")
            lines = ["─── Email:Pass ───"]
            lines.extend([f"{r['email']}:{r['password']}" for r in emails])
            lines.append("\n─── Keys ───")
            lines.extend([r["key"] for r in keys])
            return "\n".join(lines)

    async def log_feedback(self, user_id: int, item_type: str, item_id: int, feedback_type: str):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO feedback_log (user_id, item_type, item_id, feedback_type, served_at)
                VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
            """, user_id, item_type, item_id, feedback_type)

    async def save_hit_report(self, user_id: int, content: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO hit_reports (user_id, content) VALUES ($1, $2)",
                user_id, content
            )

    async def save_contact_message(self, user_id: int, content: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO contact_messages (user_id, content) VALUES ($1, $2)",
                user_id, content
            )

    async def get_all_users(self, limit: int = 20, offset: int = 0) -> List[Dict]:
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT user_id, username, first_name, plan, reputation, is_banned, total_gens
                FROM users
                ORDER BY user_id
                LIMIT $1 OFFSET $2
            """, limit, offset)

    async def get_user_count(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM users")

    async def update_total_gens(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET total_gens = total_gens + 1 WHERE user_id = $1",
                user_id
            )

db = Database()

# ─── Helper Functions ──────────────────────────────────────────
def escape_markdown_v2(text: str) -> str:
    return "" if text is None else str(text)

def format_plan(plan: str) -> str:
    plans = {
        "free": "🆓 𝙵𝚁𝙴𝙴 ",
        "pro": "⭐ 𝙿𝚁𝙾 ",
        "elite": "👑 𝙴𝙻𝙸𝚃𝙴 ",
        "unlimited": "∞ 𝚄𝙽𝙻𝙸𝙼𝙸𝚃𝙴𝙳 "
    }
    return plans.get(plan, plan.upper())

PLAN_LIMITS = {"free": 5, "pro": 20, "elite": 50, "unlimited": None}
PLAN_COOLDOWN_MINUTES = {"free": 5, "pro": 2, "elite": 0, "unlimited": 0}

def plan_limit(plan: str) -> Optional[int]:
    return PLAN_LIMITS.get(plan, DAILY_LIMIT)

def plan_cooldown_minutes(plan: str) -> int:
    return PLAN_COOLDOWN_MINUTES.get(plan, COOLDOWN_MINUTES)

def plan_features(plan: str) -> str:
    if plan == "free":
        return "• 5 𝚐𝚎𝚗𝚜/𝚍𝚊𝚢\n• 1 𝚙𝚎𝚛 5 𝚖𝚒𝚗\n• 𝙴𝚖𝚊𝚒𝚕:𝙿𝚊𝚜𝚜 + 𝙺𝚎𝚢𝚜 "
    elif plan == "pro":
        return "• 20 𝚐𝚎𝚗𝚜/𝚍𝚊𝚢\n• 1 𝚙𝚎𝚛 2 𝚖𝚒𝚗\n• 𝙿𝚛𝚒𝚘𝚛𝚒𝚝𝚢 𝚜𝚞𝚙𝚙𝚘𝚛𝚝\n• 𝙰𝚕𝚕 𝚝𝚢𝚙𝚎𝚜 "
    elif plan == "elite":
        return "• 50 𝚐𝚎𝚗𝚜/𝚍𝚊𝚢\n• 𝙽𝚘 𝚌𝚘𝚘𝚕𝚍𝚘𝚠𝚗\n• 𝙿𝚛𝚒𝚘𝚛𝚒𝚝𝚢 𝚜𝚞𝚙𝚙𝚘𝚛𝚝\n• 𝙰𝚕𝚕 𝚝𝚢𝚙𝚎𝚜 "
    elif plan == "unlimited":
        return "• 𝚄𝙽𝙻𝙸𝙼𝙸𝚃𝙴𝙳 𝚐𝚎𝚗𝚜\n• 𝙽𝚘 𝚌𝚘𝚘𝚕𝚍𝚘𝚠𝚗\n• 𝟸𝟺/𝟽 𝚜𝚞𝚙𝚙𝚘𝚛𝚝\n• 𝙰𝚕𝚕 𝚝𝚢𝚙𝚎𝚜 "
    return " "

# ─── Resilient Telegram I/O helpers ─────────────────────────────
async def _retry_call(coro_factory, *, max_retries: int = MAX_RETRIES, base_delay: float = RETRY_BASE_DELAY):
    attempt = 0
    while True:
        try:
            return await coro_factory()
        except RetryAfter as e:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = max(float(e.retry_after), 0.5)
            logger.warning("Rate limited (RetryAfter=%.1fs); retry %d/%d", float(e.retry_after), attempt, max_retries)
            await asyncio.sleep(delay)
        except TimedOut:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("Timed out; retry %d/%d in %.1fs", attempt, max_retries, delay)
            await asyncio.sleep(delay)
        except NetworkError as e:
            if isinstance(e, BadRequest):
                raise
            attempt += 1
            if attempt > max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("Transient network error; retry %d/%d in %.1fs", attempt, max_retries, delay)
            await asyncio.sleep(delay)

async def safe_reply(message, text: str, reply_markup=None, **kwargs):
    try:
        return await _retry_call(
            lambda: message.reply_text(text=text, reply_markup=reply_markup, **kwargs)
        )
    except RetryAfter as e:
        logger.error("reply_text rate-limited after retries (RetryAfter=%.1fs)", float(e.retry_after))
    except BadRequest as e:
        logger.error("reply_text rejected by Telegram: %s", e)
    except (TimedOut, NetworkError) as e:
        logger.error("reply_text failed after retries: %s", type(e).__name__)
    except Exception as e:
        logger.exception("reply_text failed: %s", type(e).__name__)
    return None

async def safe_edit(query, text: str, reply_markup=None, **kwargs):
    try:
        return await _retry_call(
            lambda: query.edit_message_text(text=text, reply_markup=reply_markup, **kwargs)
        )
    except BadRequest as e:
        msg = str(e)
        if "not modified" in msg.lower():
            logger.debug("edit_message_text: message not modified (ignored).")
        else:
            logger.error("edit_message_text bad request: %s", msg)
    except RetryAfter as e:
        logger.error("edit_message_text rate-limited after retries (RetryAfter=%.1fs)", float(e.retry_after))
    except (TimedOut, NetworkError) as e:
        logger.error("edit_message_text failed after retries: %s", type(e).__name__)
    except Exception as e:
        logger.exception("edit_message_text failed: %s", type(e).__name__)
    return None

async def safe_notify(bot, chat_id, text: str, **kwargs) -> bool:
    try:
        await _retry_call(lambda: bot.send_message(chat_id=chat_id, text=text, **kwargs))
        return True
    except RetryAfter as e:
        logger.error("notify %s rate-limited (RetryAfter=%.1fs)", chat_id, float(e.retry_after))
    except BadRequest as e:
        logger.error("notify %s rejected by Telegram: %s", chat_id, e)
    except (TimedOut, NetworkError) as e:
        logger.error("notify %s failed after retries: %s", chat_id, type(e).__name__)
    except Exception as e:
        logger.exception("notify %s failed: %s", chat_id, type(e).__name__)
    return False

# ─── Handlers ──────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.create_user(user.id, user.username or "", user.first_name or "")
    msg = (
        f"ʜᴇʟʟᴏ {escape_markdown_v2(user.first_name or 'ᴜꜱᴇʀ')}!\n"
        "ᴛʜɪꜱ ɪꜱ ᴇxᴘʀᴇꜱꜱᴠᴘɴ ᴘʀᴏᴠɪᴅᴇʀ ʙᴏᴛ — ʏᴏᴜʀ ꜱᴏᴜʀᴄᴇ ꜰᴏʀ ᴘʀᴇᴍɪᴜᴍ ᴠᴘɴ ᴀᴄᴄᴏᴜɴᴛꜱ ᴀɴᴅ ᴋᴇʏꜱ.\n"
        "ᴜꜱᴇ ᴛʜᴇ ᴄᴏᴍᴍᴀɴᴅꜱ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ꜱᴛᴀʀᴛᴇᴅ:\n"
        "➜ /gen — ɢᴇᴛ ᴀ ᴠᴘɴ ᴀᴄᴄᴏᴜɴᴛ ᴏʀ ᴋᴇʏ\n"
        "➜ /profile — ᴠɪᴇᴡ ʏᴏᴜʀ ᴘʀᴏꜰɪʟᴇ\n"
        "➜ /status — ᴄʜᴇᴄᴋ ꜱᴛᴏᴄᴋ ᴀᴠᴀɪʟᴀʙɪʟɪᴛʏ\n"
        "➜ /plan — ᴠɪᴇᴡ ʏᴏᴜʀ ᴘʟᴀɴ\n"
        "➜ /hits — ꜱᴇɴᴅ ʜɪᴛ ʀᴇᴘᴏʀᴛ\n"
        "➜ /contact — ᴄᴏɴᴛᴀᴄᴛ ᴀ ᴅᴍɪɴ\n"
        "➜ /help — ꜱʜᴏᴡ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅꜱ"
    )
    keyboard = [
        [InlineKeyboardButton("📧 Get Email:Pass ", callback_data="gen_email")],
        [InlineKeyboardButton("🔑 Get PC Key ", callback_data="gen_key")],
        [InlineKeyboardButton("📊 Check Stock ", callback_data="status")],
        [InlineKeyboardButton("👤 My Profile ", callback_data="profile")],
    ]
    await safe_reply(update.message, msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin_user = user_id in ADMIN_IDS or user_id == OWNER_ID
    if is_admin_user:
        msg = ("⚙ 𝙰𝙳𝙼𝙸𝙽 𝙲𝙾𝙼𝙼𝙰𝙽𝙳𝚂 \n"
               "📦 𝚂𝚃𝙾𝙲𝙺 𝙼𝙰𝙽𝙰𝙶𝙴𝙼𝙴𝙽𝚃 \n"
               "➜ /addemail — 𝙰𝚍𝚍 𝚎𝚖𝚊𝚒𝚕:𝚙𝚊𝚜𝚜 𝚊𝚌𝚌𝚘𝚞𝚗𝚝𝚜 \n"
               "➜ /addkey — 𝙰𝚍𝚍 𝙿𝙲 𝚔𝚎𝚢𝚜 \n"
               "➜ /removeemail <𝚒𝚍> — 𝚁𝚎𝚖𝚘𝚟𝚎 𝚎𝚖𝚊𝚒𝚕:𝚙𝚊𝚜𝚜 𝚋𝚢 𝙸𝙳 \n"
               "➜ /removekey <𝚒𝚍> — 𝚁𝚎𝚖𝚘𝚟𝚎 𝚔𝚎𝚢 𝚋𝚢 𝙸𝙳 \n"
               "➜ /reset — 𝙳𝚎𝚕𝚎𝚝𝚎 𝚊𝚕𝚕 𝚜𝚝𝚘𝚌𝚔 \n"
               "➜ /export — 𝙳𝚘𝚠𝚗𝚕𝚘𝚊𝚍 𝚜𝚝𝚘𝚌𝚔 𝚊𝚜 .𝚝𝚡𝚝 \n"
               "👥 𝚄𝚂𝙴𝚁 𝙼𝙰𝙽𝙰𝙶𝙴𝙼𝙴𝙽𝚃 \n"
               "➜ /users — 𝙻𝚒𝚜𝚝 𝚊𝚕𝚕 𝚞𝚜𝚎𝚛𝚜 (𝚙𝚊𝚐𝚎𝚍) \n"
               "➜ /profile <𝚞𝚜𝚎𝚛_𝚒𝚍> — 𝚅𝚒𝚎𝚠 𝚞𝚜𝚎𝚛 𝚙𝚛𝚘𝚏𝚒𝚕𝚎 \n"
               "➜ /ban <𝚞𝚜𝚎𝚛_𝚒𝚍> [𝚛𝚎𝚊𝚜𝚘𝚗] — 𝙱𝚊𝚗 𝚊 𝚞𝚜𝚎𝚛 \n"
               "➜ /unban <𝚞𝚜𝚎𝚛_𝚒𝚍> — 𝚄𝚗𝚋𝚊𝚗 𝚊 𝚞𝚜𝚎𝚛 \n"
               "➜ /banned — 𝙻𝚒𝚜𝚝 𝚋𝚊𝚗𝚗𝚎𝚍 𝚞𝚜𝚎𝚛𝚜 \n"
               "➜ /setplan <𝚞𝚜𝚎𝚛_𝚒𝚍> <𝚙𝚕𝚊𝚗> — 𝙲𝚑𝚊𝚗𝚐𝚎 𝚞𝚜𝚎𝚛 𝚙𝚕𝚊𝚗 \n"
               "⭐ 𝚁𝙴𝙿𝚄𝚃𝙰𝚃𝙸𝙾𝙽 \n"
               "➜ /addrep <𝚞𝚜𝚎𝚛_𝚒𝚍> <𝚊𝚖𝚘𝚞𝚗𝚝> — 𝙰𝚍𝚍 𝚛𝚎𝚙𝚞𝚝𝚊𝚝𝚒𝚘𝚗 \n"
               "➜ /rmrep <𝚞𝚜𝚎𝚛_𝚒𝚍> <𝚊𝚖𝚘𝚞𝚗𝚝> — 𝚁𝚎𝚖𝚘𝚟𝚎 𝚛𝚎𝚙𝚞𝚝𝚊𝚝𝚒𝚘𝚗 \n"
               "➜ /setrep <𝚞𝚜𝚎𝚛_𝚒𝚍> <𝚟𝚊𝚕𝚞𝚎> — 𝚂𝚎𝚝 𝚎𝚡𝚊𝚌𝚝 𝚛𝚎𝚙𝚞𝚝𝚊𝚝𝚒𝚘𝚗 \n"
               "📊 𝚂𝚃𝙰𝚃𝚂 & 𝙻𝙾𝙶𝚂 \n"
               "➜ /stats — 𝚂𝚝𝚘𝚌𝚔 + 𝚞𝚜𝚎𝚛 𝚜𝚝𝚊𝚝𝚜 \n"
               "➜ /logs — 𝚁𝚎𝚌𝚎𝚗𝚝 𝚊𝚌𝚝𝚒𝚟𝚒𝚝𝚢 \n"
               "➜ /hits_admin — 𝚅𝚒𝚎𝚠 𝚑𝚒𝚝 𝚛𝚎𝚙𝚘𝚛𝚝𝚜 \n"
               "➜ /messages — 𝚅𝚒𝚎𝚠 𝚌𝚘𝚗𝚝𝚊𝚌𝚝 𝚖𝚎𝚜𝚜𝚊𝚐𝚎𝚜 \n"
               "📢 𝙱𝚁𝙾𝙰𝙳𝙲𝙰𝚂𝚃 \n"
               "➜ /broadcast <𝚖𝚎𝚜𝚜𝚊𝚐𝚎> — 𝚂𝚎𝚗𝚍 𝚝𝚘 𝚊𝚕𝚕 𝚞𝚜𝚎𝚛𝚜 \n"
               "👑 𝙰𝙳𝙼𝙸𝙽 𝙼𝙰𝙽𝙰𝙶𝙴𝙼𝙴𝙽𝚃 \n"
               "➜ /addadmin <𝚞𝚜𝚎𝚛_𝚒𝚍> — 𝙰𝚍𝚍 𝚊𝚍𝚖𝚒𝚗 \n"
               "➜ /removeadmin <𝚞𝚜𝚎𝚛_𝚒𝚍> — 𝚁𝚎𝚖𝚘𝚟𝚎 𝚊𝚍𝚖𝚒𝚗 \n"
               "🔄 𝙲𝙾𝙼𝙼𝙾𝙽 \n"
               "➜ /start — 𝚂𝚝𝚊𝚛𝚝 𝚋𝚘𝚝 \n"
               "➜ /help — 𝚃𝚑𝚒𝚜 𝚖𝚎𝚜𝚜𝚊𝚐𝚎")
        await safe_reply(update.message, msg)
    else:
        msg = ("📋 𝙲𝙾𝙼𝙼𝙰𝙽𝙳𝚂 \n"
               "➜ /gen — 𝙶𝚎𝚝 𝚊 𝚅𝙿𝙽 𝚊𝚌𝚌𝚘𝚞𝚗𝚝 𝚘𝚛 𝚔𝚎𝚢 \n"
               "➜ /profile — 𝚅𝚒𝚎𝚠 𝚢𝚘𝚞𝚛 𝚙𝚛𝚘𝚏𝚒𝚕𝚎 \n"
               "➜ /status — 𝙲𝚑𝚎𝚌𝚔 𝚜𝚝𝚘𝚌𝚔 𝚊𝚟𝚊𝚒𝚕𝚊𝚋𝚒𝚕𝚒𝚝𝚢 \n"
               "➜ /plan — 𝚅𝚒𝚎𝚠 𝚢𝚘𝚞𝚛 𝚙𝚕𝚊𝚗 \n"
               "➜ /hits — 𝚂𝚎𝚗𝚍 𝚑𝚒𝚝 𝚛𝚎𝚙𝚘𝚛𝚝 \n"
               "➜ /contact — 𝙲𝚘𝚗𝚝𝚊𝚌𝚝 𝚊𝚍𝚖𝚒𝚗 \n"
               "➜ /help — 𝚃𝚑𝚒𝚜 𝚖𝚎𝚜𝚜𝚊𝚐𝚎")
        await safe_reply(update.message, msg)

async def gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await db.is_banned(user_id):
        user = await db.get_user(user_id)
        await safe_reply(
            update.message,
            f"🚫 𝚈𝙾𝚄 𝙰𝚁𝙴 𝙱𝙰𝙽𝙽𝙴𝙳\n\n𝚁𝚎𝚊𝚜𝚘𝚗: {escape_markdown_v2(user['ban_reason'] or '𝙽𝚘 𝚛𝚎𝚊𝚜𝚘𝚗')}\n\n𝙲𝚘𝚗𝚝𝚊𝚌𝚝 𝚊𝚍𝚖𝚒𝚗: /contact "
        )
        return
    stock = await db.get_stock_count()
    keyboard = [
        [InlineKeyboardButton(f"📧 Get Email:Pass ({stock['emails']} left) ", callback_data="gen_email")],
        [InlineKeyboardButton(f"🔑 Get PC Key ({stock['keys']} left) ", callback_data="gen_key")],
        [InlineKeyboardButton("📊 Check Stock ", callback_data="status")],
        [InlineKeyboardButton("👤 My Profile ", callback_data="profile")],
        [InlineKeyboardButton("🔙 Back ", callback_data="back_main")],
    ]
    await safe_reply(
        update.message,
        "𝚂𝙴𝙻𝙴𝙲𝚃 𝚆𝙷𝙰𝚃 𝚈𝙾𝚄 𝚆𝙰𝙽𝚃 𝚃𝙾 𝙶𝙴𝙽𝙴𝚁𝙰𝚃𝙴: ",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    target_id = user_id
    if context.args and await db.is_admin(user_id):
        try:
            target_id = int(context.args[0])
        except ValueError:
            await safe_reply(update.message, "❌ Invalid user ID.")
            return
    user = await db.get_user(target_id)
    if not user:
        await safe_reply(update.message, "𝙿𝚕𝚎𝚊𝚜𝚎 𝚞𝚜𝚎 /start 𝚏𝚒𝚛𝚜𝚝. ")
        return
    daily = await db.get_daily_count(target_id)
    is_banned = user['is_banned']
    user_limit = plan_limit(user['plan'])
    usage_text = f"{daily}/{user_limit}" if user_limit is not None else f"{daily}/∞"
    msg = (f"👤 𝙿𝚁𝙾𝙵𝙸𝙻𝙴 \n"
           f"𝚄𝚜𝚎𝚛 𝙸𝙳: {user['user_id']} \n"
           f"𝚄𝚜𝚎𝚛𝚗𝚊𝚖𝚎: @{escape_markdown_v2(user['username'] or 'None')}\n"
           f"𝙽𝚊𝚖𝚎: {escape_markdown_v2(user['first_name'] or 'None')}\n"
           f"📊 𝚂𝚃𝙰𝚃𝚂 \n"
           f"• 𝙿𝚕𝚊𝚗: {format_plan(user['plan'])}\n"
           f"• 𝚁𝚎𝚙𝚞𝚝𝚊𝚝𝚒𝚘𝚗: {user['reputation']} ✦\n"
           f"• 𝚃𝚘𝚝𝚊𝚕 𝙶𝚎𝚗𝚜: {user['total_gens']}\n"
           f"• 𝚃𝚘𝚍𝚊𝚢'𝚜 𝚄𝚜𝚊𝚐𝚎: {usage_text}\n"
           f"• 𝙹𝚘𝚒𝚗𝚎𝚍: {user['joined_at'].strftime('%Y-%m-%d')}\n"
           f"• 𝚂𝚝𝚊𝚝𝚞𝚜: {'🟢 𝙰𝚌𝚝𝚒𝚟𝚎' if not is_banned else '🔴 𝙱𝙰𝙽𝙽𝙴𝙳'}")
    if is_banned:
        msg += f"\n\n🚫 𝙱𝚊𝚗 𝚁𝚎𝚊𝚜𝚘𝚗: {escape_markdown_v2(user['ban_reason'] or 'None')} "
    await safe_reply(update.message, msg)

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    plan = await db.get_plan(user_id)
    msg = f"""📊 𝚈𝙾𝚄𝚁 𝙿𝙻𝙰𝙽
{format_plan(plan)} 𝙿𝙻𝙰𝙽
{plan_features(plan)}
┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
⭐ 𝙰𝚅𝙰𝙸𝙻𝙰𝙱𝙻𝙴 𝙿𝙻𝙰𝙽𝚂
↯ 𝙵𝚁𝙴𝙴 — 5/𝚍𝚊𝚢, 1/5𝚖𝚒𝚗
↯ 𝙿𝚁𝙾 — 20/𝚍𝚊𝚢, 1/2𝚖𝚒𝚗
↯ 𝙴𝙻𝙸𝚃𝙴 — 50/𝚍𝚊𝚢, 𝚗𝚘 𝚌𝚘𝚘𝚕𝚍𝚘𝚠𝚗
↯ 𝚄𝙽𝙻𝙸𝙼𝙸𝚃𝙴𝙳 — 𝚞𝚗𝚕𝚒𝚖𝚒𝚝𝚎𝚍 𝚐𝚎𝚗𝚜
𝙲𝚘𝚗𝚝𝚊𝚌𝚝 𝚊𝚍𝚖𝚒𝚗 𝚝𝚘 𝚞𝚙𝚐𝚛𝚊𝚍𝚎: /contact"""
    await safe_reply(update.message, msg)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stock = await db.get_stock_count()
    total_users = await db.get_user_count()
    msg = f"""📊 𝚂𝚃𝙾𝙲𝙺 𝚂𝚃𝙰𝚃𝚄𝚂
📧 𝙴𝚖𝚊𝚒𝚕:𝙿𝚊𝚜𝚜: {stock['emails']}
🔑 𝙿𝙲 𝙺𝚎𝚢𝚜: {stock['keys']}
👥 𝚃𝚘𝚝𝚊𝚕 𝚄𝚜𝚎𝚛𝚜: {total_users}"""
    await safe_reply(update.message, msg)

async def hits_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_hit"] = True
    await safe_reply(
        update.message,
        "📥 𝚂𝙴𝙽𝙳 𝚈𝙾𝚄𝚁 𝙷𝙸𝚃 𝚁𝙴𝙿𝙾𝚁𝚃\n\n"
        "𝙵𝚘𝚛𝚖𝚊𝚝:\n"
        "𝚂𝚎𝚛𝚟𝚒𝚌𝚎: 𝙴𝚖𝚊𝚒𝚕:𝙿𝚊𝚜𝚜\n"
        "𝙳𝚎𝚝𝚊𝚒𝚕𝚜: 𝚆𝚘𝚛𝚔𝚒𝚗𝚐 𝚏𝚒𝚗𝚎\n\n"
        "𝙴𝚡𝚊𝚖𝚙𝚕𝚎:\n"
        "𝙴𝚡𝚙𝚛𝚎𝚜𝚜𝚅𝙿𝙽: 𝚞𝚜𝚎𝚛@𝚎𝚖𝚊𝚒𝚕.𝚌𝚘𝚖:𝚙𝚊𝚜𝚜123\n"
        "𝚆𝚘𝚛𝚔𝚒𝚗𝚐 𝚙𝚎𝚛𝚏𝚎𝚌𝚝𝚕𝚢 ✅\n\n"
        "𝚂𝚎𝚗𝚍 𝚢𝚘𝚞𝚛 𝚛𝚎𝚙𝚘𝚛𝚝 𝚗𝚘𝚠. "
    )

async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = f"""👤 𝙲𝙾𝙽𝚃𝙰𝙲𝚃 𝙵𝙾𝚁 𝙿𝚁𝙴𝙼𝙸𝚄𝙼
𝙵𝚘𝚛 𝚙𝚕𝚊𝚗 𝚞𝚙𝚐𝚛𝚊𝚍𝚎𝚜 & 𝚋𝚞𝚜𝚒𝚗𝚎𝚜𝚜 𝚚𝚞𝚎𝚛𝚒𝚎𝚜, 𝚖𝚎𝚜𝚜𝚊𝚐𝚎 𝚍𝚒𝚛𝚎𝚌𝚝𝚕𝚢:
👉 @{escape_markdown_v2("Yorichiiprime")}
📌 𝚁𝚄𝙻𝙴𝚂:
• 𝙽𝙾 "𝙷𝚒/𝙷𝚎𝚕𝚕𝚘" 𝚖𝚎𝚜𝚜𝚊𝚐𝚎𝚜.
• 𝙾𝚗𝚕𝚢 𝚜𝚎𝚗𝚍 𝚋𝚞𝚜𝚒𝚗𝚎𝚜𝚜/𝚙𝚕𝚊𝚗 𝚛𝚎𝚕𝚊𝚝𝚎𝚍 𝚚𝚞𝚎𝚛𝚒𝚎𝚜.
• 𝙸𝚗𝚌𝚕𝚞𝚍𝚎 𝚢𝚘𝚞𝚛 𝚃𝚎𝚕𝚎𝚐𝚛𝚊𝚖 𝙸𝙳 & 𝚛𝚎𝚚𝚞𝚎𝚜𝚝 𝚍𝚎𝚝𝚊𝚒𝚕𝚜."""
    keyboard = [[InlineKeyboardButton("💬 𝙾𝚙𝚎𝚗 𝙲𝚑𝚊𝚝", url="https://t.me/Yorichiiprime")]]
    await safe_reply(update.message, msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_hit_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.user_data.get("awaiting_hit"):
        return
    context.user_data["awaiting_hit"] = False
    content = update.message.text
    await db.save_hit_report(user_id, content)
    admins = await db.get_admins()
    for admin_id in admins:
        await safe_notify(
            context.bot,
            admin_id,
            f"📥 𝙷𝙸𝚃 𝚁𝙴𝙿𝙾𝚁𝚃\n\n"
            f"𝙵𝚛𝚘𝚖: @{escape_markdown_v2(update.effective_user.username or '')}\n"
            f"𝚄𝚜𝚎𝚛 𝙸𝙳: {user_id}\n\n{escape_markdown_v2(content)}"
        )
    await safe_reply(update.message, "✅ 𝙷𝚒𝚝 𝚛𝚎𝚙𝚘𝚛𝚝 𝚜𝚎𝚗𝚝! 𝚃𝚑𝚊𝚗𝚔 𝚢𝚘𝚞.")

async def handle_contact_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.user_data.get("awaiting_contact"):
        return
    context.user_data["awaiting_contact"] = False
    content = update.message.text
    await db.save_contact_message(user_id, content)
    admins = await db.get_admins()
    for admin_id in admins:
        await safe_notify(
            context.bot,
            admin_id,
            f"👤 𝙲𝙾𝙽𝚃𝙰𝙲𝚃 𝙼𝙴𝚂𝚂𝙰𝙶𝙴\n\n"
            f"𝙵𝚛𝚘𝚖: @{escape_markdown_v2(update.effective_user.username or '')}\n"
            f"𝚄𝚜𝚎𝚛 𝙸𝙳: {user_id}\n\n{escape_markdown_v2(content)}"
        )
    await safe_reply(update.message, "✅ 𝙼𝚎𝚜𝚜𝚊𝚐𝚎 𝚜𝚎𝚗𝚝! 𝙰𝚍𝚖𝚒𝚗 𝚠𝚒𝚕𝚕 𝚛𝚎𝚜𝚙𝚘𝚗𝚍 𝚜𝚑𝚘𝚛𝚝𝚕𝚢.")

async def handle_add_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        return
    mode = context.user_data.get("add_mode")
    if not mode:
        return
    text = update.message.text
    lines = text.strip().split("\n")
    added = 0
    failed = 0
    if mode == "email":
        for line in lines:
            if ":" not in line:
                failed += 1
                continue
            email, password = line.split(":", 1)
            if await db.add_emailpass(email.strip(), password.strip(), user_id):
                added += 1
            else:
                failed += 1
    elif mode == "key":
        for line in lines:
            key = line.strip()
            if await db.add_key(key, user_id):
                added += 1
            else:
                failed += 1
    await safe_reply(
        update.message,
        f"✅ 𝙰𝙳𝙳𝙴𝙳\n\n{added} 𝚒𝚝𝚎𝚖𝚜 𝚊𝚍𝚍𝚎𝚍\n{failed} 𝚏𝚊𝚒𝚕𝚎𝚍 "
    )
    context.user_data.pop("add_mode", None)

# ─── Callback Queries ──────────────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if await db.is_banned(user_id):
        await safe_edit(query, "🚫 𝚈𝙾𝚄 𝙰𝚁𝙴 𝙱𝙰𝙽𝙽𝙴𝙳. 𝙲𝚘𝚗𝚝𝚊𝚌𝚝 𝚊𝚍𝚖𝚒𝚗: /contact")
        return
    data = query.data
    if data == "back_main":
        await safe_edit(query, "𝚃𝚢𝚙𝚎 /start 𝚝𝚘 𝚐𝚘 𝚋𝚊𝚌𝚔 𝚝𝚘 𝚝𝚑𝚎 𝚖𝚊𝚒𝚗 𝚖𝚎𝚗𝚞.")
        return
    if data == "profile":
        user = await db.get_user(user_id)
        if not user:
            await safe_edit(query, "𝙿𝚕𝚎𝚊𝚜𝚎 𝚞𝚜𝚎 /start 𝚏𝚒𝚛𝚜𝚝.")
            return
        daily = await db.get_daily_count(user_id)
        msg = f"""👤 𝙿𝚁𝙾𝙵𝙸𝙻𝙴
𝚄𝚜𝚎𝚛 𝙸𝙳: {user['user_id']}
𝚄𝚜𝚎𝚛𝚗𝚊𝚖𝚎: @{escape_markdown_v2(user['username'] or 'None')}
𝙽𝚊𝚖𝚎: {escape_markdown_v2(user['first_name'] or 'None')}
📊 𝚂𝚃𝙰𝚃𝚂
• 𝙿𝚕𝚊𝚗: {format_plan(user['plan'])}
• 𝚁𝚎𝚙𝚞𝚝𝚊𝚝𝚒𝚘𝚗: {user['reputation']} ✦
• 𝚃𝚘𝚝𝚊𝚕 𝙶𝚎𝚗𝚜: {user['total_gens']}
• 𝚃𝚘𝚍𝚊𝚢'𝚜 𝚄𝚜𝚊𝚐𝚎: {daily}/{DAILY_LIMIT}"""
        await safe_edit(query, msg)
        return
    if data == "status":
        stock = await db.get_stock_count()
        total_users = await db.get_user_count()
        await safe_edit(
            query,
            f"📊 𝚂𝚃𝙾𝙲𝙺 𝚂𝚃𝙰𝚃𝚄𝚂\n\n📧 𝙴𝚖𝚊𝚒𝚕:𝙿𝚊𝚜𝚜: {stock['emails']}\n🔑 𝙿𝙲 𝙺𝚎𝚢𝚜: {stock['keys']}\n👥 𝚃𝚘𝚝𝚊𝚕 𝚄𝚜𝚎𝚛𝚜: {total_users}"
        )
        return
    if data in ["gen_email", "gen_key"]:
        await process_gen(query, context, user_id, data)

async def process_gen(query, context, user_id, gen_type):
    await db.create_user(user_id, query.from_user.username or "", query.from_user.first_name or "")
    plan = await db.get_plan(user_id)
    cooldown_minutes = plan_cooldown_minutes(plan)
    last_gen = await db.get_last_gen(user_id)
    if last_gen and cooldown_minutes > 0:
        elapsed = (datetime.now() - last_gen).total_seconds()
        if elapsed < cooldown_minutes * 60:
            remaining = int(cooldown_minutes * 60 - elapsed)
            await safe_edit(query, f"⏳ 𝙲𝙾𝙾𝙻𝙳𝙾𝚆𝙽 𝙰𝙲𝚃𝙸𝚅𝙴\n\n𝙿𝚕𝚎𝚊𝚜𝚎 𝚠𝚊𝚒𝚝 {remaining} 𝚜𝚎𝚌𝚘𝚗𝚍𝚜.")
            return
    daily_count = await db.get_daily_count(user_id)
    limit = plan_limit(plan)
    if limit is not None and daily_count >= limit:
        await safe_edit(
            query,
            f"🚫 𝙳𝙰𝙸𝙻𝚈 𝙻𝙸𝙼𝙸𝚃 𝚁𝙴𝙰𝙲𝙷𝙴𝙳\n\nYou have used {daily_count}/{limit} gens today.\n\n𝙲𝚘𝚗𝚝𝚊𝚌𝚝 𝚊𝚍𝚖𝚒𝚗: /contact"
        )
        return
    if gen_type == "gen_email":
        item = await db.get_emailpass(user_id)
        if not item:
            await safe_edit(query, "📭 𝙽𝙾 𝙴𝙼𝙰𝙸𝙻:𝙿𝙰𝚂𝚂 𝙻𝙴𝙵𝚃.\n\n𝙰𝚍𝚖𝚒𝚗 𝚠𝚒𝚕𝚕 𝚛𝚎𝚏𝚒𝚕𝚕.")
            return
        await db.increment_daily_count(user_id)
        await db.update_total_gens(user_id)
        keyboard = [
            [InlineKeyboardButton("📋 Copy", callback_data=f"copy_{item['id']}")],
            [InlineKeyboardButton("✅ Working", callback_data=f"fb_working_email_{item['id']}"),
             InlineKeyboardButton("❌ Dead", callback_data=f"fb_dead_email_{item['id']}")],
            [InlineKeyboardButton("⏭️ Skip (-1 rep)", callback_data=f"fb_skip_email_{item['id']}")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")],
        ]
        await safe_edit(
            query,
            f"📧 𝙴𝙼𝙰𝙸𝙻:𝙿𝙰𝚂𝚂 𝙶𝙴𝙽𝙴𝚁𝙰𝚃𝙴𝙳\n\n𝙴𝚖𝚊𝚒𝚕: {escape_markdown_v2(item['email'])}\n𝙿𝚊𝚜𝚜: {escape_markdown_v2(item['password'])}\n\n𝙲𝚕𝚒𝚌𝚔 𝙲𝚘𝚙𝚢.\n\n𝙵𝚎𝚎𝚍𝚋𝚊𝚌𝚔 𝚛𝚎𝚚𝚞𝚒𝚛𝚎𝚍!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        item = await db.get_key(user_id)
        if not item:
            await safe_edit(query, "📭 𝙽𝙾 𝙿𝙲 𝙺𝙴𝚈𝚂 𝙻𝙴𝙵𝚃.\n\n𝙰𝚍𝚖𝚒𝚗 𝚠𝚒𝚕𝚕 𝚛𝚎𝚏𝚒𝚕𝚕.")
            return
        await db.increment_daily_count(user_id)
        await db.update_total_gens(user_id)
        keyboard = [
            [InlineKeyboardButton("📋 Copy", callback_data=f"copy_{item['id']}")],
            [InlineKeyboardButton("✅ Working", callback_data=f"fb_working_key_{item['id']}"),
             InlineKeyboardButton("❌ Dead", callback_data=f"fb_dead_key_{item['id']}")],
            [InlineKeyboardButton("⏭️ Skip (-1 rep)", callback_data=f"fb_skip_key_{item['id']}")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")],
        ]
        await safe_edit(
            query,
            f"🔑 𝙿𝙲 𝙺𝙴𝚈 𝙶𝙴𝙽𝙴𝚁𝙰𝚃𝙴𝙳\n\n𝙺𝚎𝚢: {escape_markdown_v2(item['key'])}\n\n𝙲𝚕𝚒𝚌𝚔 𝙲𝚘𝚙𝚢.\n\n𝙵𝚎𝚎𝚍𝚋𝚊𝚌𝚔 𝚛𝚎𝚚𝚞𝚒𝚛𝚎𝚍!",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    parts = data.split("_")
    if len(parts) < 4:
        logger.warning("Malformed feedback callback_data: %r", data)
        return
    fb_type = parts[1]
    item_type = parts[2]
    try:
        item_id = int(parts[3])
    except ValueError:
        logger.warning("Non-numeric item id in feedback callback_data: %r", data)
        return
    if fb_type not in ("working", "dead", "skip") or item_type not in ("email", "key"):
        logger.warning("Unknown feedback callback_data: %r", data)
        return
    await db.log_feedback(user_id, item_type, item_id, fb_type)
    if fb_type == "skip":
        rep = await db.add_reputation(user_id, -1)
        if rep is None:
            rep = 0
        await safe_edit(query, f"⏭️ 𝚂𝙺𝙸𝙿𝙿𝙴𝙳\n\n-1 𝚁𝙴𝙿\n\n𝙽𝚎𝚠 𝚁𝚎𝚙: {rep} ✦\n\n𝙿𝚕𝚎𝚊𝚜𝚎 𝚐𝚒𝚟𝚎 𝚏𝚎𝚎𝚍𝚋𝚊𝚌𝚔 𝚗𝚎𝚡𝚝 𝚝𝚒𝚖𝚎!")
        if rep <= 0:
            await db.ban_user(user_id, "Reputation dropped to 0 (skipped feedback)")
            await safe_edit(query, "🚫 𝙱𝙰𝙽𝙽𝙴𝙳 𝙵𝙾𝚁 𝙽𝙾𝚃 𝙿𝚁𝙾𝚅𝙸𝙳𝙸𝙽𝙶 𝙵𝙴𝙴𝙳𝙱𝙰𝙲𝙺\n\n𝙲𝚘𝚗𝚝𝚊𝚌𝚝 𝚊𝚍𝚖𝚒𝚗: /contact")
        return
    if fb_type == "working":
        rep = await db.add_reputation(user_id, 1)
        if rep is None:
            rep = 0
        await safe_edit(query, f"✅ 𝙵𝙴𝙴𝙳𝙱𝙰𝙲𝙺 𝚁𝙴𝙲𝙾𝚁𝙳𝙴𝙳\n\n+1 𝙰𝙳𝙳𝙴𝙳\n\n𝙽𝚎𝚠 𝚁𝚎𝚙: {rep} ✦")
        return
    if fb_type == "dead":
        admins = await db.get_admins()
        for admin_id in admins:
            await safe_notify(
                context.bot,
                admin_id,
                f"⚠️ 𝙳𝙴𝙰𝙳 𝙰𝙲𝙲𝙾𝚄𝙽𝚃\n\n"
                f"𝚄𝚜𝚎𝚛: @{escape_markdown_v2(update.effective_user.username or '')}\n"
                f"𝙸𝚍: {item_id}\n𝚃𝚢𝚙𝚎: {item_type}\n"
                "𝙾𝚙𝚎𝚛𝚊𝚝𝚘𝚛 𝚗𝚎𝚎𝚍𝚜 𝚝𝚘 𝚛𝚎𝚖𝚘𝚟𝚎. "
            )
        if item_type == "email":
            await db.remove_emailpass(item_id)
        else:
            await db.remove_key(item_id)
        await safe_edit(query, "❌ 𝙵𝙴𝙴𝙳𝙱𝙰𝙲𝙺 𝙻𝙾𝙶𝙶𝙴𝙳\n\n𝚃𝚑𝚎 𝚊𝚌𝚌𝚘𝚞𝚗𝚝 𝚠𝚒𝚕𝚕 𝚋𝚎 𝚛𝚎𝚖𝚘𝚟𝚎𝚍 𝚏𝚛𝚘𝚖 𝚜𝚝𝚘𝚌𝚔.")
        return

async def copy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "📋 𝙲𝙾𝙿𝚈 𝚃𝙷𝙴 𝚃𝙴𝚇𝚃\n\n𝚂𝚎𝚕𝚎𝚌𝚝 𝚝𝚑𝚎 𝚊𝚌𝚌𝚘𝚞𝚗𝚝 𝚘𝚛 𝚔𝚎𝚢 𝚊𝚋𝚘𝚟𝚎 𝚊𝚗𝚍 𝚞𝚜𝚎 𝙲𝚝𝚛𝚕+𝙲.")

# ─── Admin Commands ─────────────────────────────────────────────
async def add_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    context.user_data["add_mode"] = "email"
    await safe_reply(update.message, "📤 𝚂𝙴𝙽𝙳 𝙴𝙼𝙰𝙸𝙻:𝙿𝙰𝚂𝚂\n\n𝙾𝚗𝚎 𝚙𝚎𝚛 𝚕𝚒𝚗𝚎:\n𝚎𝚖𝚊𝚒𝚕:𝚙𝚊𝚜𝚜\n\n𝚃𝚢𝚙𝚎 /cancel 𝚝𝚘 𝚜𝚝𝚘𝚙.")

async def add_key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    context.user_data["add_mode"] = "key"
    await safe_reply(update.message, "📤 𝚂𝙴𝙽𝙳 𝙿𝙲 𝙺𝙴𝚈𝚂\n\n𝙾𝚗𝚎 𝚙𝚎𝚛 𝚕𝚒𝚗𝚎:\n𝙰𝙱𝙲𝟷𝟸𝟹𝚇𝚈𝚉\n\n𝚃𝚢𝚙𝚎 /cancel 𝚝𝚘 𝚜𝚝𝚘𝚙.")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("add_mode", None)
    context.user_data.pop("awaiting_hit", None)
    context.user_data.pop("awaiting_contact", None)
    await safe_reply(update.message, "✅ 𝙲𝚊𝚗𝚌𝚎𝚕𝚕𝚎𝚍.")

async def add_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_edit(query, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    context.user_data.pop("add_mode", None)
    await safe_edit(query, "✅ 𝙰𝚍𝚍 𝚖𝚘𝚍𝚎 𝚌𝚕𝚘𝚜𝚎𝚍.")

async def add_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_edit(query, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    context.user_data.pop("add_mode", None)
    await safe_edit(query, "❌ 𝙰𝚍𝚍 𝚖𝚘𝚍𝚎 𝚌𝚊𝚗𝚌𝚎𝚕𝚕𝚎𝚍.")

async def remove_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    if not context.args:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /removeemail <𝚒𝚍>")
        return
    try:
        item_id = int(context.args[0])
    except ValueError:
        await safe_reply(update.message, "❌ 𝙸𝚗𝚟𝚊𝚕𝚒𝚍 𝙸𝙳.")
        return
    if await db.remove_emailpass(item_id):
        await safe_reply(update.message, f"✅ 𝙴𝚖𝚊𝚒𝚕:𝙿𝚊𝚜𝚜 𝙸𝙳 {item_id} 𝚛𝚎𝚖𝚘𝚟𝚎𝚍.")
    else:
        await safe_reply(update.message, f"❌ 𝙸𝙳 {item_id} 𝚗𝚘𝚝 𝚏𝚘𝚞𝚗𝚍.")

async def remove_key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    if not context.args:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /removekey <𝚒𝚍>")
        return
    try:
        item_id = int(context.args[0])
    except ValueError:
        await safe_reply(update.message, "❌ 𝙸𝚗𝚟𝚊𝚕𝚒𝚍 𝙸𝙳.")
        return
    if await db.remove_key(item_id):
        await safe_reply(update.message, f"✅ 𝙺𝚎𝚢 𝙸𝙳 {item_id} 𝚛𝚎𝚖𝚘𝚟𝚎𝚍.")
    else:
        await safe_reply(update.message, f"❌ 𝙸𝙳 {item_id} 𝚗𝚘𝚝 𝚏𝚘𝚞𝚗𝚍.")

async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    keyboard = [
        [InlineKeyboardButton("✅ Confirm Reset", callback_data="reset_confirm")],
        [InlineKeyboardButton("❌ Cancel", callback_data="reset_cancel")],
    ]
    await safe_reply(update.message, "⚠️ 𝚆𝙰𝚁𝙽𝙸𝙽𝙶\n\n𝚃𝚑𝚒𝚜 𝚠𝚒𝚕𝚕 𝙳𝙴𝙻𝙴𝚃𝙴 𝙰𝙻𝙻 𝚜𝚝𝚘𝚌𝚔.\n\n𝙲𝚘𝚗𝚏𝚒𝚛𝚖:", reply_markup=InlineKeyboardMarkup(keyboard))

async def reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_edit(query, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    if query.data == "reset_confirm":
        await db.reset_stock()
        await safe_edit(query, "✅ 𝙰𝙻𝙻 𝚂𝚃𝙾𝙲𝙺 𝚁𝙴𝚂𝙴𝚃.")
    else:
        await safe_edit(query, "❌ 𝚁𝚎𝚜𝚎𝚝 𝚌𝚊𝚗𝚌𝚎𝚕𝚕𝚎𝚍.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    stock = await db.get_stock_count()
    total_users = await db.get_user_count()
    msg = f"""📊 𝚂𝚃𝙰𝚃𝙸𝚂𝚃𝙸𝙲𝚂
📧 𝙴𝚖𝚊𝚒𝚕:𝙿𝚊𝚜𝚜: {stock['emails']}
🔑 𝙿𝙲 𝙺𝚎𝚢𝚜: {stock['keys']}
👥 𝚃𝚘𝚝𝚊𝚕 𝚄𝚜𝚎𝚛𝚜: {total_users}"""
    await safe_reply(update.message, msg)

async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈 ")
        return
    page = 1
    if context.args:
        try:
            page = int(context.args[0])
        except ValueError:
            pass
    limit = 20
    page = max(1, page)
    offset = (page - 1) * limit
    users = await db.get_all_users(limit, offset)
    total = await db.get_user_count()
    total_pages = max(1, (total + limit - 1) // limit)
    if not users:
        await safe_reply(update.message, "𝙽𝚘 𝚞𝚜𝚎𝚛𝚜. ")
        return
    msg = f"👥 𝚄𝚂𝙴𝚁 𝙻𝙸𝚂𝚃 (𝙿𝚊𝚐𝚎 {page}/{total_pages})\n\n "
    for u in users:
        status = "🟢 " if not u["is_banned"] else "🔴 "
        msg += f"{status} {u['user_id']} @{escape_markdown_v2(u['username'] or 'None')} | {format_plan(u['plan'])} | {u['reputation']}✦\n "
    keyboard = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ ", callback_data=f"users_page_{page-1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️ ", callback_data=f"users_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 Back ", callback_data="back_main")])
    await safe_reply(update.message, msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def users_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_edit(query, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈 ")
        return
    try:
        page = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        logger.warning("Malformed users_page callback_data: %r", query.data)
        return
    limit = 20
    page = max(1, page)
    offset = (page - 1) * limit
    users = await db.get_all_users(limit, offset)
    total = await db.get_user_count()
    total_pages = max(1, (total + limit - 1) // limit)
    msg = f"👥 𝚄𝚂𝙴𝚁 𝙻𝙸𝚂𝚃 (𝙿𝚊𝚐𝚎 {page}/{total_pages})\n\n "
    for u in users:
        status = "🟢 " if not u["is_banned"] else "🔴 "
        msg += f"{status} {u['user_id']} @{escape_markdown_v2(u['username'] or 'None')} | {format_plan(u['plan'])} | {u['reputation']}✦\n "
    keyboard = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀️ ", callback_data=f"users_page_{page-1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶️ ", callback_data=f"users_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 Back ", callback_data="back_main")])
    await safe_edit(query, msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈 ")
        return
    if not context.args:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /ban <𝚞𝚜𝚎𝚛_𝚒𝚍> [𝚛𝚎𝚊𝚜𝚘𝚗] ")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await safe_reply(update.message, "❌ Invalid user ID. ")
        return
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "No reason "
    if target_id == OWNER_ID:
        await safe_reply(update.message, "❌ 𝙲𝙰𝙽𝙽𝙾𝚃 𝙱𝙰𝙽 𝙾𝚆𝙽𝙴𝚁. ")
        return
    await db.ban_user(target_id, reason)
    await safe_reply(update.message, f"✅ 𝚄𝚜𝚎𝚛 {target_id} 𝚋𝚊𝚗𝚗𝚎𝚍.\n𝚁𝚎𝚊𝚜𝚘𝚗: {escape_markdown_v2(reason)} ")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    if not context.args:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /unban <𝚞𝚜𝚎𝚛_𝚒𝚍>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await safe_reply(update.message, "❌ Invalid user ID.")
        return
    await db.unban_user(target_id)
    await safe_reply(update.message, f"✅ 𝚄𝚜𝚎𝚛 {target_id} 𝚞𝚗𝚋𝚊𝚗𝚗𝚎𝚍.")

async def banned_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    banned = await db.get_banned_users()
    if not banned:
        await safe_reply(update.message, "𝙽𝚘 𝚋𝚊𝚗𝚗𝚎𝚍 𝚞𝚜𝚎𝚛𝚜.")
        return
    msg = "🚫 𝙱𝙰𝙽𝙽𝙴𝙳 𝚄𝚂𝙴𝚁𝚂\n\n"
    for b in banned:
        msg += f"{b['user_id']} @{escape_markdown_v2(b['username'] or 'None')}\n  𝚁𝚎𝚊𝚜𝚘𝚗: {escape_markdown_v2(b['ban_reason'] or 'None')}\n\n"
    await safe_reply(update.message, msg)

async def set_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈 ")
        return
    if len(context.args) < 2:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /setplan <𝚞𝚜𝚎𝚛_𝚒𝚍> <𝚏𝚛𝚎𝚎|𝚙𝚛𝚘|𝚎𝚕𝚒𝚝𝚎|𝚞𝚗𝚕𝚒𝚖𝚒𝚝𝚎𝚍> ")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await safe_reply(update.message, "❌ Invalid user ID. ")
        return
    plan = context.args[1].lower()
    valid_plans = ["free", "pro", "elite", "unlimited"]
    if plan not in valid_plans:
        await safe_reply(update.message, f"❌ 𝙸𝚗𝚟𝚊𝚕𝚒𝚍. 𝙲𝚑𝚘𝚘𝚜𝚎: {', '.join(valid_plans)} ")
        return
    await db.set_plan(target_id, plan)
    await safe_reply(update.message, f"✅ 𝙿𝚕𝚊𝚗 𝚏𝚘𝚛 {target_id} → {plan.upper()}. ")

async def add_rep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈 ")
        return
    if len(context.args) < 2:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /addrep <𝚞𝚜𝚎𝚛_𝚒𝚍> <𝚊𝚖𝚘𝚞𝚗𝚝> ")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await safe_reply(update.message, "❌ User ID and amount must be numbers.")
        return
    rep = await db.add_reputation(target_id, amount)
    await safe_reply(update.message, f"✅ {target_id} +{amount} 𝚛𝚎𝚙\n𝙽𝚎𝚠 𝚛𝚎𝚙: {rep} ✦ ")

async def rm_rep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    if len(context.args) < 2:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /rmrep <𝚞𝚜𝚎𝚛_𝚒𝚍> <𝚊𝚖𝚘𝚞𝚗𝚝>")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await safe_reply(update.message, "❌ User ID and amount must be numbers.")
        return
    rep = await db.add_reputation(target_id, -amount)
    await safe_reply(update.message, f"✅ {target_id} -{amount} 𝚛𝚎𝚙\n𝙽𝚎𝚠 𝚛𝚎𝚙: {rep} ✦")

async def set_rep_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈 ")
        return
    if len(context.args) < 2:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /setrep <𝚞𝚜𝚎𝚛_𝚒𝚍> <𝚟𝚊𝚕𝚞𝚎> ")
        return
    try:
        target_id = int(context.args[0])
        value = int(context.args[1])
    except ValueError:
        await safe_reply(update.message, "❌ User ID and value must be numbers.")
        return
    await db.set_reputation(target_id, value)
    await safe_reply(update.message, f"✅ {target_id} 𝚛𝚎𝚙 → {value} ✦ ")

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    content = await db.export_stock()
    if not content.strip():
        await safe_reply(update.message, "📭 𝙽𝚘 𝚜𝚝𝚘𝚌𝚔.")
        return
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(content)
        temp_path = f.name
    try:
        await _retry_call(lambda: update.message.reply_document(document=InputFile(temp_path, "stock_export.txt"), caption="📦 𝙴𝚇𝙿𝙾𝚁𝚃"))
    except Exception:
        logger.exception("Failed to send stock export document.")
    finally:
        os.unlink(temp_path)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈")
        return
    if not context.args:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /broadcast <𝚖𝚎𝚜𝚜𝚊𝚐𝚎>")
        return
    message = " ".join(context.args)
    users = await db.get_all_users(9999)
    count = 0
    for user in users:
        if await safe_notify(context.bot, user["user_id"], message):
            count += 1
        await asyncio.sleep(0.05)
    await safe_reply(update.message, f"✅ 𝙱𝚛𝚘𝚊𝚍𝚌𝚊𝚜𝚝 𝚜𝚎𝚗𝚝 𝚝𝚘 {count} 𝚞𝚜𝚎𝚛𝚜.")

async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await safe_reply(update.message, "⛔ 𝙾𝚆𝙽𝙴𝚁 𝙾𝙽𝙻𝚈")
        return
    if not context.args:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /addadmin <𝚞𝚜𝚎𝚛_𝚒𝚍>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await safe_reply(update.message, "❌ Invalid user ID.")
        return
    await db.add_admin(target_id)
    await safe_reply(update.message, f"✅ {target_id} 𝚗𝚘𝚠 𝚊𝚍𝚖𝚒𝚗.")

async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await safe_reply(update.message, "⛔ 𝙾𝚆𝙽𝙴𝚁 𝙾𝙽𝙻𝚈")
        return
    if not context.args:
        await safe_reply(update.message, "𝚄𝚜𝚊𝚐𝚎: /removeadmin <𝚞𝚜𝚎𝚛_𝚒𝚍>")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await safe_reply(update.message, "❌ Invalid user ID.")
        return
    if target_id == OWNER_ID:
        await safe_reply(update.message, "❌ 𝙲𝙰𝙽𝙽𝙾𝚃 𝚁𝙴𝙼𝙾𝚅𝙴 𝙾𝚆𝙽𝙴𝚁.")
        return
    await db.remove_admin(target_id)
    await safe_reply(update.message, f"✅ {target_id} 𝚛𝚎𝚖𝚘𝚟𝚎𝚍.")

async def logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈 ")
        return
    async with db.pool.acquire() as conn:
        logs = await conn.fetch("""
            SELECT user_id, item_type, feedback_type, feedback_at
            FROM feedback_log
            ORDER BY feedback_at DESC
            LIMIT 10
        """)
    if not logs:
        await safe_reply(update.message, "𝙽𝚘 𝚕𝚘𝚐𝚜. ")
        return
    msg = "📋 𝚁𝙴𝙲𝙴𝙽𝚃 𝙻𝙾𝙶𝚂\n\n "
    for log in logs:
        msg += f"• {log['user_id']} → {log['item_type']} ({log['feedback_type']}) {log['feedback_at'].strftime('%H:%M')}\n "
    await safe_reply(update.message, msg)

async def hits_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈 ")
        return
    async with db.pool.acquire() as conn:
        hits = await conn.fetch("""
            SELECT id, user_id, content, sent_at
            FROM hit_reports
            WHERE is_read = FALSE
            ORDER BY sent_at DESC
            LIMIT 20
        """)
    if not hits:
        await safe_reply(update.message, "𝙽𝚘 𝚑𝚒𝚝𝚜. ")
        return
    msg = "📥 𝙷𝙸𝚃 𝚁𝙴𝙿𝙾𝚁𝚃𝚂\n\n "
    for h in hits:
        msg += f" {h['user_id']} : {escape_markdown_v2(h['content'][:100])}\n "
    await safe_reply(update.message, msg)

async def messages_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await db.is_admin(user_id):
        await safe_reply(update.message, "⛔ 𝙰𝙳𝙼𝙸𝙽 𝙾𝙽𝙻𝚈 ")
        return
    async with db.pool.acquire() as conn:
        msgs = await conn.fetch("""
            SELECT id, user_id, content, sent_at
            FROM contact_messages
            WHERE is_read = FALSE
            ORDER BY sent_at DESC
            LIMIT 20
        """)
    if not msgs:
        await safe_reply(update.message, "𝙽𝚘 𝚖𝚎𝚜𝚜𝚊𝚐𝚎𝚜. ")
        return
    msg = "👤 𝙲𝙾𝙽𝚃𝙰𝙲𝚃 𝙼𝙴𝚂𝚂𝙰𝙶𝙴𝚂\n\n "
    for m in msgs:
        msg += f" {m['user_id']} : {escape_markdown_v2(m['content'][:100])}\n "
    await safe_reply(update.message, msg)

# ─── Global Error Handler ──────────────────────────────────────
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if update and hasattr(update, 'effective_user') and update.effective_user:
        try:
            await safe_notify(context.bot, update.effective_user.id, "⚠️ 𝙰𝚗 𝚞𝚗𝚎𝚡𝚙𝚎𝚌𝚝𝚎𝚍 𝚎𝚛𝚛𝚘𝚛 𝚘𝚌𝚌𝚞𝚛𝚛𝚎𝚍. 𝙿𝚕𝚎𝚊𝚜𝚎 𝚝𝚛𝚢 𝚊𝚐𝚊𝚒𝚗 𝚘𝚛 𝚌𝚘𝚗𝚝𝚊𝚌𝚝 𝚊𝚍𝚖𝚒𝚗.")
        except Exception:
            logger.exception("Failed to notify user of an error.")

# ─── Main ────────────────────────────────────────────────────────
async def main():
    await db.initialize()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(HTTPXRequest(
            connection_pool_size=32,
            read_timeout=REQUEST_READ_TIMEOUT,
            write_timeout=REQUEST_WRITE_TIMEOUT,
            connect_timeout=REQUEST_CONNECT_TIMEOUT,
            pool_timeout=REQUEST_POOL_TIMEOUT,
        ))
        .get_updates_request(HTTPXRequest(
            connection_pool_size=1,
            read_timeout=GET_UPDATES_READ_TIMEOUT,
            write_timeout=REQUEST_WRITE_TIMEOUT,
            connect_timeout=REQUEST_CONNECT_TIMEOUT,
            pool_timeout=REQUEST_POOL_TIMEOUT,
        ))
        .build()
    )

    # ── User Commands ──
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("gen", gen_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("plan", plan_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("hits", hits_command))
    app.add_handler(CommandHandler("contact", contact_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # ── Admin Commands ──
    app.add_handler(CommandHandler("addemail", add_email_command))
    app.add_handler(CommandHandler("addkey", add_key_command))
    app.add_handler(CommandHandler("removeemail", remove_email_command))
    app.add_handler(CommandHandler("removekey", remove_key_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("users", users_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("banned", banned_command))
    app.add_handler(CommandHandler("setplan", set_plan_command))
    app.add_handler(CommandHandler("addrep", add_rep_command))
    app.add_handler(CommandHandler("rmrep", rm_rep_command))
    app.add_handler(CommandHandler("setrep", set_rep_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("addadmin", add_admin_command))
    app.add_handler(CommandHandler("removeadmin", remove_admin_command))
    app.add_handler(CommandHandler("logs", logs_command))
    app.add_handler(CommandHandler("hits_admin", hits_admin_command))
    app.add_handler(CommandHandler("messages", messages_admin_command))

    # ── Message Handlers ──
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_hit_message), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_contact_message), group=1)

    # ── Callback Queries ──
    app.add_handler(CallbackQueryHandler(button_callback, pattern="^(gen_email|gen_key|status|profile|back_main)$"))
    app.add_handler(CallbackQueryHandler(add_done_callback, pattern="^add_done_"))
    app.add_handler(CallbackQueryHandler(add_cancel_callback, pattern="^add_cancel$"))
    app.add_handler(CallbackQueryHandler(reset_callback, pattern="^reset_"))
    app.add_handler(CallbackQueryHandler(users_page_callback, pattern="^users_page_"))
    app.add_handler(CallbackQueryHandler(copy_callback, pattern="^copy_"))
    app.add_handler(CallbackQueryHandler(feedback_callback, pattern="^fb_"))

    # ── Error Handler ──
    app.add_error_handler(error_handler)

    # ── Startup / shutdown (PTB v20+ async lifecycle) ──
    await app.initialize()
    await app.updater.start_polling(drop_pending_updates=True, timeout=POLL_TIMEOUT)
    await app.start()
    logger.info("Bot is running. Press Ctrl+C to stop.")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutdown requested.")
    finally:
        logger.info("Shutting down gracefully...")
        try:
            await app.updater.stop()
        except Exception:
            logger.exception("Error while stopping the updater.")
        try:
            await app.stop()
        except Exception:
            logger.exception("Error while stopping the application.")
        try:
            await app.shutdown()
        except Exception:
            logger.exception("Error while shutting down the application.")
        if db.pool:
            await db.pool.close()
            db.pool = None

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped.")
    except RuntimeError as e:
        print(f"\n[FATAL] {e}\n")
        raise SystemExit(1)