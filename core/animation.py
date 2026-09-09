"""
Aɴɪᴍᴀᴛɪᴏɴ ──────
The bot never leaves you staring at nothing. Long actions edit the
same message through short motion frames (boot splash, generation
progress), then resolve into the real page. Everything happens on ONE
message ─ buttons navigate by replacing content, never by stacking
new messages.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardMarkup

from core.style import G, sc

log = logging.getLogger("anim")

_SPIN = ("▘", "▝", "▗", "▖")
# order: 1..4 little quadrants -> loop


def progress_bar(filled: int, total: int, width: int = 10) -> str:
    """▰▰▰▱▱▱▱▱▱▱ style bar."""
    filled = max(0, min(filled, total))
    done = round(width * filled / total) if total else width
    bar = G.BOL * done + G.BOLO * (width - done)
    pct = round(100 * filled / total) if total else 100
    return f"{bar} {pct:>3}%"


async def _edit(query, text: str, markup: InlineKeyboardMarkup | None) -> None:
    """Swallow the harmless 'message is not modified' error."""
    try:
        await query.edit_message_text(text=text, reply_markup=markup)
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        if "not modified" in str(exc).lower():
            return
        log.debug("anim edit skipped: %s: %s", name, exc)


async def boot_splash(query, *, steps: int = 4, wait: float = 0.34) -> None:
    """Startup flourish used when the user presses /start."""
    labels = [
        f"{G.BOLT} ᴡᴀʀᴍɪɴɢ ᴜᴘ ᴛʜᴇ sʏꜱᴛᴇᴍ",
        f"{G.DIAM} ᴘᴀʀsɪɴɢ ʏᴏᴜʀ sʟᴏᴛ",
        f"{G.STAR} sʏɴᴄɪɴɢ ᴘʀᴇᴍɪᴜᴍ ʀᴇʟᴀʏ",
        f"{G.DOTF} ʀᴇᴀᴅʏ",
    ]
    for i, label in enumerate(labels[:steps], start=1):
        line = label
        if i < steps:
            line += " " + _SPIN[(i * 2) % 4]
        text = f"{sc(config_name())}\n{G.LINE_S}\n{line}\n{progress_bar(i, steps)}"
        await _edit(query, text, None)
        if i < steps:
            await asyncio.sleep(wait)


def config_name() -> str:
    from config import BOT_NAME  # local import to dodge import cycles

    return BOT_NAME


async def gen_flourish(query, kind_label: str, *, fast: bool = False, wait: float = 0.34) -> None:
    """
    Live 'fetching' motion before a generated account lands.
    fast=True (owner) collapses it to a single beat so the owner never waits.
    """
    if fast:
        steps = 1
    else:
        steps = 3
    lines = [
        f"{G.ARR} ʀᴇsᴇʀᴠɪɴɢ ʏᴏᴜʀ {kind_label}",
        f"{G.ARR} sᴇᴀʟɪɴɢ sʟᴏᴛ",
        f"{G.ARR} ᴅᴇʟɪᴠᴇʀɪɴɢ",
    ]
    for i in range(1, steps + 1):
        line = lines[i - 1] if i <= len(lines) else lines[-1]
        text = f"{sc('Vault Dispatch')}\n{G.LINE_S}\n{line} {_SPIN[i % 4]}\n{progress_bar(i, steps)}"
        await _edit(query, text, None)
        if i < steps:
            await asyncio.sleep(wait)
