"""
Cᴏɴꜱᴛᴀɴᴛꜱ ──────
Shared labels, callback codes and state-machine tokens used across
the whole bot. Keeping them here means no typo can silently break a
button route, and every callback payload stays short & fast.
"""
from __future__ import annotations

# ── Inline-callback codes ───────────────────────────────────────
# Kept tiny on purpose: shorter payloads = faster round-trips.
CB = {
    # navigation / main
    "HOME": "h",
    "BACK": "bk",
    "GEN": "gn",
    "GEN_EP": "ge",
    "GEN_KEY": "gk",
    "STOCK": "st",
    "PROFILE": "pf",
    "PLANS": "pl",
    "CONTACT": "ct",
    "HELP": "hp",
    # actions from a result card
    "FB_WORK": "fw",
    "FB_DEAD": "fd",
    "FB_SKIP": "fs",
    "GEN_AGAIN": "ga",
    # contact / reports
    "MSG_WRITE": "mw",     # -> text mode
    "MSG_HIT": "mh",       # -> text mode
    "DM_OWNER": "dm",
    # owner space
    "OWN_PANEL": "op",
    "OWN_USERS": "ou",
    "OWN_USER_PAGE": "oup:",     # oup:<page>
    "OWN_MANAGE": "oum:",        # oum:<uid>
    "OWN_SEARCH": "osr",
    "OWN_PLAN": "opn:",          # opn:<uid>:<plan>
    "OWN_REP": "orp:",           # orp:<uid>:<delta>
    "OWN_BAN": "obn:",           # obn:<uid>:0|1
    "OWN_ADD_EP": "oae",
    "OWN_ADD_KEY": "oak",
    "OWN_ADD_DONE": "oad",
    "OWN_REMOVE": "orem:",       # orem:<kind>:<id>
    "OWN_REMOVE_DONE": "ord",
    "OWN_RESET": "orst",
    "OWN_RESET_YES": "orsy",
    "OWN_RESET_NO": "orsn",
    "OWN_EXPORT": "oex",
    "OWN_STATS": "ost",
    "OWN_BROADCAST": "obc",
    "OWN_BC_DONE": "obcd",
    "OWN_INBOX": "oib:",         # oib:<kind>:<index>   kind c|h
    "OWN_INBOX_READ": "oir:",    # oir:<kind>:<id>
    "OWN_INBOX_READALL": "oira:",  # oira:<kind>
    "OWN_INBOX_DEL": "oid:",     # oid:<kind>:<id>
    "OWN_INBOX_REFRESH": "oirf:",  # oirf:<kind>
    "OWN_LOGS": "olg",
    "OWN_BANNED": "obd",
    "OWN_HITS": "ohits:",
    # plan detail / utility
    "PLAN_DETAIL": "pd:",
    "STOCK_FORCE": "stf",
    "CANCEL_MODE": "fc",
}

# Inline text-mode tokens (context.user_data["mode"])
MODE = {
    "ADD_EP": "add_ep",
    "ADD_KEY": "add_key",
    "WRITE_MSG": "write_msg",
    "HIT_REPORT": "hit_report",
    "SEARCH_USER": "search_user",
    "BROADCAST": "broadcast",
    "RESET_CONFIRM": "reset_confirm",
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
