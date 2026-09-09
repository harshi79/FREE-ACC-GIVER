"""
Sᴇᴄᴜʀɪᴛʏ ────────
There is exactly one privileged identity: the OWNER. No admins, no
roles table, no hidden second class. Owner bypasses every gate
(limits, cooldowns, reputation, welcome-flows) and is the only
account that may ever see the control panel.
"""
from __future__ import annotations

import config


def is_owner(uid: int) -> bool:
    return uid == config.OWNER_ID


def owner_text_reply_expected(mode: str) -> bool:
    return mode in ("add_ep", "add_key", "search_user", "broadcast")


def user_text_reply_expected(mode: str) -> bool:
    return mode in ("write_msg", "hit_report")
