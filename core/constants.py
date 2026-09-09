"""
Cᴏɴꜱᴛᴀɴᴛꜱ ──────
Shared labels, callback codes and state-machine tokens used across
the whole bot. Keeping them here means no typo can silently break a
button route, and every callback payload stays short & fast.

Every "o*" code below MUST be registered in handlers_owner._OWNER_PREFIXES
and answered by owner_callback (the selftest verifies this automatically).
"""
from __future__ import annotations

# ── Inline-callback codes ───────────────────────────────────────
# Kept tiny on purpose: shorter payloads = faster round-trips.
# Pool slugs are [a-z0-9] only, so "g:<slug>", "fw:<slug>:<id>" stay short.
CB = {
    # navigation / main
    "HOME": "h",
    "VAULT": "vg",              # vault 2.0 pool grid
    "POOL": "g:",              # g:<slug> — pull from ONE pool, never another
    "STOCK": "st",
    "PROFILE": "pf",
    "PLANS": "pl",
    "CONTACT": "ct",
    "HELP": "hp",
    # actions from a result card
    "FB_WORK": "fw",           # fw:<slug>:<id>
    "FB_DEAD": "fd",           # fd:<slug>:<id>
    "FB_SKIP": "fs",           # fs:<slug>:<id>
    "GEN_AGAIN": "ga:",        # ga:<slug> — sends a NEW message
    # contact / reports
    "MSG_WRITE": "mw",         # -> text mode
    # owner space
    "OWN_PANEL": "op",
    "OWN_USER_PAGE": "oup:",     # oup:<page>
    "OWN_MANAGE": "oum:",        # oum:<uid>
    "OWN_SEARCH": "osr",
    "OWN_PLAN": "opn:",          # opn:<uid>:<plan>
    "OWN_REP": "orp:",           # orp:<uid>:<delta>
    "OWN_BAN": "obn:",           # obn:<uid>:0|1
    "OWN_RESET": "orst",         # global reset (WIPE-gated)
    "OWN_RESET_NO": "orsn",
    "OWN_EXPORT": "oex",         # export everything (sectioned per pool)
    "OWN_STATS": "ost",
    "OWN_BROADCAST": "obc",
    "OWN_INBOX": "oib:",         # oib:<kind>:<index>   kind c|h
    "OWN_INBOX_READ": "oir:",    # oir:<kind>:<id>
    "OWN_INBOX_READALL": "oira:",  # oira:<kind>
    "OWN_INBOX_DEL": "oid:",     # oid:<kind>:<id>
    "OWN_LOGS": "olg",
    "OWN_BANNED": "obd",
    # owner · vault manager (per-pool everything)
    "OWN_VAULT_MGR": "ovm:",      # ovm:<page>
    "OWN_NEW_POOL": "onp",        # step 1: ask the pool name (text)
    "OWN_NEW_POOL_KIND": "onpk:",  # onpk:ep|key — step 2: pick the kind
    "OWN_POOL_ADD": "ova:",       # ova:<slug> — add stock INTO the pool
    "OWN_POOL_EXPORT": "ovx:",    # ovx:<slug> — export ONE pool
    "OWN_POOL_REMOVE": "orem:",   # orem:<slug> — remove-by-id prompt (text)
    "OWN_POOL_RESET": "orpr:",    # orpr:<slug> — WIPE-gated per-pool reset
    "OWN_ADMIN": "oam:",          # oam:<page> — the silent owner manual
    # plan detail / utility
    "PLAN_DETAIL": "pd:",
    "STOCK_FORCE": "stf",
    "CANCEL_MODE": "fc",
}

# Inline text-mode tokens (context.user_data["mode"])
MODE = {
    "ADD_STOCK": "add_stock",   # bulk paste into the chosen pool (kind+pool parked in user_data)
    "NEW_POOL": "new_pool",     # owner: name of the new pool
    "POOL_REMOVE": "pool_rm",   # owner: item id to delete from the pool
    "WRITE_MSG": "write_msg",
    "HIT_REPORT": "hit_report",
    "SEARCH_USER": "search_user",
    "BROADCAST": "broadcast",
    "RESET_CONFIRM": "reset_confirm",     # global WIPE
    "RESET_POOL": "reset_pool",           # per-pool WIPE
}

# Stock kinds
EP = "ep"        # email:pass
KEY = "key"

STOCK_LABEL = {EP: "Email:Pass", KEY: "PC Key"}

VERDICTS = {"working", "dead", "skip"}
VERDICT_BADGE = {
    "working": "[✓] Working",
    "dead": "[✗] Dead",
    "skip": "[↷] Skipped",
}
