"""
Sᴛʏʟᴇ ────────
Pure text helpers. No emoji anywhere in the bot ─ the whole visual
language uses Unicode glyphs like  [↯] [+] [✓] [✗] ◆ ✦ ▸ ── and a
"small caps" main font (ᴛʜɪs ɪs sᴍᴀʟʟ ᴄᴀᴘs).
"""
from __future__ import annotations

import random

# ── Small-caps font ─────────────────────────────────────────────
# Maps A-Z / a-z onto the Unicode small-capital letters. Digits and
# punctuation pass through untouched so emails / keys / numbers stay
# perfectly copyable where it matters (values are rendered raw anyway).
_SMALL_CAPS: dict[str, str] = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ғ", "g": "ɢ",
    "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ",
    "o": "ᴏ", "p": "ᴘ", "q": "ǫ", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ",
    "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ", "z": "ᴢ",
    "A": "ᴀ", "B": "ʙ", "C": "ᴄ", "D": "ᴅ", "E": "ᴇ", "F": "ғ", "G": "ɢ",
    "H": "ʜ", "I": "ɪ", "J": "ᴊ", "K": "ᴋ", "L": "ʟ", "M": "ᴍ", "N": "ɴ",
    "O": "ᴏ", "P": "ᴘ", "Q": "ǫ", "R": "ʀ", "S": "ꜱ", "T": "ᴛ", "U": "ᴜ",
    "V": "ᴠ", "W": "ᴡ", "X": "x", "Y": "ʏ", "Z": "ᴢ",
}


def sc(text: object) -> str:
    """Render text in the bot's small-caps main font."""
    return "".join(_SMALL_CAPS.get(ch, ch) for ch in str(text))


# ── Glyph palette (text presentation, no emoji) ─────────────────
class G:
    BOLT = "↯"      # fast / flash
    PLUS = "[+]"    # add
    MINUS = "[–]"   # remove
    OK = "[✓]"      # success
    NO = "[✗]"      # fail / block
    SKIP = "[↷]"    # skip
    REP = "✦"       # reputation
    STAR = "✧"      # premium shimmer
    DIAM = "◆"      # solid diamond
    DIAMO = "◇"     # hollow diamond
    DOT = "●"       # solid dot
    DOTF = "◉"      # filled target / live
    ARR = "▸"       # small triangle
    BACK = "◂"
    RIGHT = "⟶"
    LOOP = "⟳"
    SLIP = "[⇄]"    # copy slip
    WRITE = "[✎]"
    LOCK = "[⊘]"
    BOL = "▰"
    BOLO = "▱"
    GRID = "▸"
    BOX = "▪"
    MAIL = "[◈]"
    CHAT = "[◉]"
    WARN = "[!]"
    INF = "∞"

    # dividers (also exposed module-level as LINE / LINE_S)
    LINE = "━" * 22
    LINE_S = "─" * 22


# ── Decorators ──────────────────────────────────────────────────
LINE = "━" * 22
LINE_S = "─" * 22
FILL = "·" * 22

_SPARKS = ("✦", "✧", "◆", "↯", "◇", "▪")


def spark() -> str:
    """A tiny random shimmer used in headers, so pages feel alive."""
    return random.choice(_SPARKS)


def hr(char: str = "━") -> str:
    return char * 22


def badge(symbol: str, label: object) -> str:
    """[sym] LABEL chip, e.g. badge(G.BOLT, 'fast') -> '[↯] fast'"""
    return f"{symbol} {sc(label)}" if not symbol.startswith("[") else f"{symbol} {sc(label)}"


def fmt_rep(value: int) -> str:
    return f"{value} {G.REP}"


def fmt_stock(kind: str, count: int | None) -> str:
    if count is None:
        return "∞"
    return str(count)


def value_block(label: str, raw_value: str) -> str:
    """A neat raw value slot for emails / keys (kept plain for copying)."""
    return f"{G.ARR} {sc(label)}  \n    {raw_value}"
