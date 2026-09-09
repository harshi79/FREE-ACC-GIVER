# Fʀᴇᴇ Aᴄᴄ Gɪᴠᴇʀ — premium drop bot

A fast, button-driven Telegram bot that serves **email:pass accounts & PC keys**
from a live vault, with premium tiers, reputation, live stock, owner-only
control panel and a clean no-emoji UI (glyphs only: `[↯] [+] [✓] [✗] ◆ ✦ ▸`
and a small-caps main font).

Everything **renders on the same message** — buttons replace content in place,
no message spam. Every screen has inline buttons, animations on `/start` and
on every drop, instant in-memory counters and a single-query hot path.

---

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
BOT_TOKEN=... BOT_DATABASE_URL=postgres://... .venv/bin/python bot.py
```

> The previous single-file `bot.py` has been fully replaced. The database
> schema is unchanged (plus the old auto-migration), so **existing users,
> stock and history are kept**.

---

## Deploy on Render (Docker)

The repo ships everything Render needs: a `Dockerfile`, a `render.yaml`
Blueprint and a tiny built-in **health server** that answers `200` on
`/healthz` — so Render (or any uptime pinger) can keep the bot warm and
alive.

**Option A — Blueprint (recommended):**
1. Push this repo to GitHub.
2. Render → **New → Blueprint** → pick the repo (`render.yaml` is auto-detected).
3. When prompted, paste the secrets:
   - `BOT_TOKEN` — your Telegram token from @BotFather
   - `BOT_DATABASE_URL` — your Postgres connection string
4. Deploy. The bot starts polling the moment the container boots.

**Option B — manual Web Service:**
1. Render → **New → Web Service** → pick the repo (Docker runtime is
   detected from `Dockerfile`).
2. Add the same two env vars in **Environment**.
3. Set **Health Check Path** to `/healthz`.
4. Deploy.

**Secrets are never hardcoded:** the bot refuses to start (with a clear
list of what's missing) until `BOT_TOKEN` and `BOT_DATABASE_URL` exist in
the environment. Optional overrides: `BOT_OWNER_ID`, `BOT_OWNER_USERNAME`,
`BOT_NAME`, … (all in `config.py`).

### Run the same image locally

```bash
docker build -t free-acc-giver .
docker run --rm -p 8000:8000 \
  -e BOT_TOKEN=... \
  -e BOT_DATABASE_URL=postgres://... \
  free-acc-giver

# health check
curl -i http://localhost:8000/healthz     # -> 200 ok
```

### Health server

`core/health.py` starts before any database work and binds
`0.0.0.0:$PORT` (Render injects `PORT`; falls back to `8000`). Every
route answers `200 "ok"` on GET/HEAD, on a silent daemon thread — it
never touches the bot's async loop. Web services on Render must bind
the port quickly or they're restarted; this guarantees that.

---

## One owner. Nobody else. Ever.

- There are **no admins, no roles** — exactly one privileged id: `OWNER_ID`.
- Every "admin" feature is **owner-only** and lives behind the hidden
  **Owner Core** button that only appears on the owner's own screens.
- Owner bypasses **every** gate: daily limits, cooldowns, reputation
  penalties, feedback requirements — nothing applies to the owner.
- Owner commands (`/panel /users /manage /export …`) are silent hotkeys.
  They never appear in `/help`, in menus or in the bot's command list —
  normal members have no way to see them, and non-owner calls are ignored.
- Bans are per-user; the owner can never be banned by the bot.

---

## Member experience

| Screen        | What it does                                                        |
|---------------|---------------------------------------------------------------------|
| `/start`      | Boot animation → hub with live stock counters on the buttons        |
| `/gen`        | Vault picker → animated dispatch → account lands on the same message|
| Feedback      | `[✓] Working` (+1 ✦) · `[✗] Dead` (auto-remove + owner ping) · `[↷] Skip` (−1 ✦) |
| `/profile`    | Plan, reputation, today's pulls, lifetime pulls                      |
| `/plans`      | Tier cards (Free/Pro/Elite/∞) + private-account ordering            |
| `/contact`    | DM owner button (`@WhoEvenYori`) + compose-a-message flow            |
| `/status`     | Live stock, members, system state (one-tap refresh)                  |
| `/hits`       | Hit reports that land straight in the owner's inbox                  |

Plans gate daily pulls & cooldown:
`free 5/day · 1/5m` → `pro 20/day · 1/2m` → `elite 50/day · instant` →
`unlimited ∞ · instant`. Private accounts & custom keys are arranged 1:1 —
users drop a message at the owner (button opens the DM with their id shown).

---

## Owner Core (panel on the owner's hub)

- **[+] Email:Pass / [+] PC Keys** — bulk paste, duplicates auto-skipped
- **Users** — paged member list, **Search by id/@username**, then manage:
  `Free/Pro/Elite/∞` one-tap plan, `±3 rep`, `Ban/Unban`
- **Messages / Hits** — unread inboxes with `[✓] Read`, `[✕] Delete`,
  `Open chat`, `Mark all read`, prev/next paging
- **Broadcast** — background job with flood-guard + a receipt
- **Activity log** — latest verdicts
- **Export .txt** · **Reset pool** (must type `WIPE` to confirm)
- All numbers cached in memory (TTL) so every panel opens instantly.

---

## Code map (multi-file, by design)

```
config.py                every setting from env (secrets REQUIRED)
bot.py                   entry point + callback router + health boot
Dockerfile · render.yaml Render-ready container + blueprint
core/
  style.py               small-caps font ᴀʙᴄ + glyph palette (no emoji)
  constants.py           callback codes + text-mode tokens
  messaging.py           ONE-message page engine (edit, fallback send)
  views.py               every screen → (text, inline keyboard)
  animation.py           boot & dispatch motion frames
  cache.py               TTL counters (stock/users) + banned-state cache
  net.py                 retry-hardened sends / broadcasts
  security.py            owner-only semantics
  health.py              /healthz HTTP 200 server (Render ping)
  handlers_users.py      member commands + button flows
  handlers_owner.py      owner panel, inboxes, broadcast (hidden)
  handlers_text.py       typed-reply state machine
data/
  db.py                  pool + schema bootstrap + migration
  store.py               every SQL operation, batched single-connection
tests/selftest.py        offline render + tap-through test (291 checks)
```

### Why it feels fast
- All gates + the claim happen on **one pooled connection** in one
  transaction (`store.serve_claim`) — the old code needed ~6 queries.
- Buttons show **cached** stock counts; profile pages collapse user + daily
  usage into one query; cache updates inline so numbers stay honest.
- Callback payloads are tiny single-character routes (`ge`, `fw:ep:127`, …).
- Updates run **concurrently across chats** while one per-chat lock keeps a
  single user's taps ordered (double-taps can't double-pull).

---

## Notes

- **Symbols, not emojis.** The whole bot uses a curated text-glyph palette
  (`↯ [+] [✓] [✗] [–] ◆ ✦ ▸ ◉ ─ ━`) and a small-caps main font. No emoji
  anywhere — verified by the test suite.
- No new messages when you tap buttons — every page **edits** the live
  message. New messages only appear for commands you type and the
  owner's file export.
- `.env`-style overrides are supported via environment variables only
  (no extra dependency).
- Run `.venv/bin/python -m tests.selftest` anytime to re-verify all screens,
  payload sizes and that owner routes stay invisible to normal users.
