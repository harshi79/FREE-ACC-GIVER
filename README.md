# Fʀᴇᴇ Aᴄᴄ Gɪᴠᴇʀ — premium drop bot

A fast, button-driven Telegram bot that serves **email:pass accounts & PC keys**
from a live **vault of pools** — one pool per brand / service, **never mixed** —
with premium tiers, reputation, live stock, owner-only control panel and a
clean no-emoji UI (glyphs only: `[↯] [+] [✓] [✗] ◆ ✦ ▸`
and a small-caps main font).

Menus **render on the same message** — navigation edits it in place, no
message spam. Every generated drop is its **own card message** that nothing
else overwrites. Every screen has inline buttons, animations on `/start` and
on every drop, instant in-memory counters and a single-query hot path.

---

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
BOT_TOKEN=... BOT_DATABASE_URL=postgres://... .venv/bin/python bot.py
```

> The previous single-file `bot.py` has been fully replaced. The **Vault 2.0
> startup migration** adds the pool `category` column, seeds the pool
> registry and imports legacy stock (old email:pass → *VPN Accounts*, old
> keys → *PC & Software Keys*) — **existing users, stock, per-pool counts and
> served history are all kept**, and the migration is idempotent + safe to
> re-run.

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
`BOT_NAME`, `BOT_AUTO_REMOVE_DEAD` (default `0` = dead reports never delete
stock), … (all in `config.py`).

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

## Vault 2.0 — pools, one per brand, never mixed

Every brand / service owns **its own pool** — two physical stock tables
(`stock_emailpass` for `email:pass` accounts, `stock_keys` for serial / PC
keys) plus a `category` column on each and a `vault_categories(category,
label, kind, pos)` registry.

* **Seeded pools** — Accounts: VPN Accounts, ExpressVPN, NordVPN, Surfshark,
  Windscribe, Streaming, Netflix, Spotify, AI Accounts, ChatGPT, Claude,
  Midjourney, Character.ai · Keys: PC & Software Keys, VPN & Service Keys,
  Game Keys, Steam, Windows/Office, Antivirus.
* **Migration on startup** adds `category` if absent (legacy email:pass rows
  land in `vpn`, legacy keys in `pc`), seeds the registry and leaves the
  per-user "already served" history untouched.
* **Claims are scoped to one pool.** An exhausted pool never borrows from
  another; the "Pool drained" card only points at other pools.
* **UI everywhere** — the home shows live totals + the hottest pools as
  one-tap chips, `vault grid` lists every pool grouped by kind with live
  counts, `/status` shows per-pool counts, and drop cards + feedback buttons
  all carry the pool (label on the card, `fw|fd|fs:<slug>:<id>` payloads).
* **New pools need no code** — Owner Core → Vault manager → `＋ New pool`:
  send a name (inline prompt), pick the kind (Accounts / PC & Software
  Keys), done. Names are slugified (`Character.ai → characterai`), duplicate
  names are refused with an error toast and slug collisions resolve to
  `name2`, `name3`… The pool shows up instantly in home chips, the grid, the
  stock page and the manager.

## Dead feedback is never auto-removed

When a user taps `[✗] Dead` on a drop card, **the stock row stays**: the
owner receives a ping (pool label + item id + value + who reported) and the
user gets a friendly confirmation appended under their still-visible card.
The owner decides via Vault manager → `✕ Remove by id`. Set
`BOT_AUTO_REMOVE_DEAD=1` to restore the old auto-pull behavior.

## Member experience

| Screen        | What it does                                                        |
|---------------|---------------------------------------------------------------------|
| `/start`      | Boot animation → hub: live totals + hottest-pool chips              |
| `/gen`        | Vault grid — every pool, grouped by kind, live counts               |
| Pull          | Animated dispatch → **a new card message per drop** (old cards stay)|
| Feedback      | `[✓] Working` (+1 ✦) · `[✗] Dead` (kept + owner ping) · `[↷] Skip` (−1 ✦) |
| `/profile`    | Plan, reputation, today's pulls, lifetime pulls                      |
| `/plans`      | Tier cards (Free/Pro/Elite/∞) + private-account ordering            |
| `/contact`    | DM owner button (`@WhoEvenYori`) + compose-a-message flow            |
| `/status`     | Live stock **per pool**, members, system state (one-tap refresh)     |
| `/hits`       | Hit reports that land straight in the owner's inbox                  |

Plans gate daily pulls & cooldown:
`free 5/day · 1/5m` → `pro 20/day · 1/2m` → `elite 50/day · instant` →
`unlimited ∞ · instant`. Limits apply across pools (no pool hopping around
the wall). Private accounts & custom keys are arranged 1:1 — users drop a
message at the owner (button opens the DM with their id shown).

## Generation behavior (cards never get wiped)

* A **successful pull always SENDS a new message** — the flourish animates on
  that new card, never on an old one. “Pull again” stacks a second card; every
  earlier drop stays on screen untouched.
* **Menu navigation** (home / vault / stock / profile / plans / contact) keeps
  editing the one live *menu* message — a tap on “◂ Main” from a card edits
  the menu, never the card, so credentials can’t be replaced by navigation.
* **Error states** (cooldown · daily wall · drained pool) also land as their
  own fresh notice message — a failed tap can never wipe a visible card.
* **Feedback edits its own card**: the verdict line is *appended under* the
  still-visible credentials (`✓ working · +1 rep`), the feedback buttons are
  then replaced with “Pull again” (new message). Old cards keep working even
  after newer ones exist; if card memory is gone (restart), the confirmation
  renders as a separate message instead of touching the card.
* A per-chat lock serialises taps, so a double-tap can’t double-pull or
  interleave two generations.

---

## Owner Core (panel on the owner's hub)

- **◆ Vault manager** — every pool as a row with its four per-pool actions:
  `＋ Add` (bulk paste **into that pool only**, duplicates auto-skipped),
  `⇩ Export` (that pool as `.txt`), `✕ Remove by id` (inline prompt → deletes
  the row **and** its served-history reference, toast shows the removed
  value), `⚠ Reset` (that pool only — must type `WIPE` to confirm)
- **＋ New pool** — name + kind inline, no code change (see Vault 2.0 above)
- **Users** — paged member list; **every row is a tappable button** opening
  that user's manage card (stats stay on the row text), plus **Search by
  id/@username**; manage: `Free/Pro/Elite/∞` one-tap plan, `±3 rep`, `Ban/Unban`
- **Banned** — same: every banned row taps through to the manage card
- **Messages / Hits** — unread inboxes with `[✓] Read`, `[✕] Delete`,
  `Open chat`, `Mark all read`, prev/next paging
- **Broadcast** — background job with flood-guard + a receipt
- **Activity log** — latest verdicts (item type + id + user + time)
- **Export all** (per-pool sections) · **Reset all** (must type `WIPE`)
- **Refresh** — re-render every cached number; answers stay instant
- **Dead reports** — owner pings only; rows are kept unless
  `BOT_AUTO_REMOVE_DEAD=1`. Removal is always a deliberate owner action.
- Every owner callback is registered, answered with an instant toast and
  audited by the selftest — no silent (broken) buttons.

### `/admin` — silent owner manual

Owner-only, never in `/help`, menus or the command list (non-owners get
literally nothing). `/admin` renders a paged manual covering every owner
command (`/panel`, `/users <page>`, `/manage id|@user`, `/export`, `/admin`)
and every Owner Core button group — one short how-to + example each — with
`◂ ▸` paging and an `Owner manual · p2/4` indicator. The entry list lives in
`views.ADMIN_ENTRIES`; the selftest asserts it stays in sync with the real
command list and panel buttons.

---

## Code map (multi-file, by design)

```
config.py                every setting from env (secrets REQUIRED)
bot.py                   entry point + per-chat-locked callback router + health boot
Dockerfile · render.yaml Render-ready container + blueprint
core/
  style.py               small-caps font ᴀʙᴄ + glyph palette (no emoji)
  constants.py           callback codes + text-mode tokens
  messaging.py           live-MENU engine + result-CARD memory (never edit a card away)
  views.py               every screen → (text, inline keyboard) · /admin manual entries
  animation.py           boot & dispatch motion frames (run on the new card)
  cache.py               pool snapshot (registry + per-pool counts, TTL) + banned cache
  net.py                 retry-hardened sends / broadcasts
  security.py            owner-only semantics
  health.py              /healthz HTTP 200 server (Render ping)
  handlers_users.py      member commands + pool pulls + card feedback flows
  handlers_owner.py      owner panel, Vault manager, pool CRUD, inboxes, broadcast
  handlers_text.py       typed-reply state machine (pools included)
data/
  db.py                  pool + schema bootstrap + Vault 2.0 migration
  catalog.py             pool seeds, slugify + collision rules, display helpers
  store.py               every SQL operation, batched single-connection, per-pool
tests/selftest.py        offline render + tap-through + SQL-level pool audit (1.2k checks)
```

### Why it feels fast
- All gates + the claim happen on **one pooled connection** in one
  transaction (`store.serve_claim`) — and the claim is pool-scoped
  (`… WHERE h.item_id IS NULL AND s.category = $2 … FOR UPDATE SKIP LOCKED`).
- Menus render from **one cached pool snapshot** (registry + per-pool
  counts + totals, short TTL, invalidated inline after every stock change);
  profile pages collapse user + daily usage into one query.
- Callback payloads are tiny (`vg`, `g:nordvpn`, `fd:netflix:127`,
  `ovx:steam`, …) — all ≤64 bytes, verified by the test suite.
- Updates run **concurrently across chats** while one per-chat lock keeps a
  single user's taps ordered (double-taps can't double-pull).

---

## Notes

- **Symbols, not emojis.** The whole bot uses a curated text-glyph palette
  (`↯ [+] [✓] [✗] [–] ◆ ✦ ▸ ◉ ─ ━ ⇩ ⚠`) and a small-caps main font. No emoji
  anywhere — even `⚠` is only allowed in its plain-glyph form, enforced by
  the test suite.
- Menu pages **edit** the live message; **drop cards are their own
  messages** and are never edited by anything except their own feedback.
  New messages also appear for commands you type and the owner's file export.
- `.env`-style overrides are supported via environment variables only
  (no extra dependency).
- Run `.venv/bin/python -m tests.selftest` anytime to re-verify every screen,
  payload sizes, pool isolation at the SQL level, card semantics, the dead
  policy, and that owner routes stay invisible to normal users.
