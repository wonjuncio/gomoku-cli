from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple
import shlex


class MsgType(Enum):
    # handshake / session
    HELLO = "HELLO"         # HELLO v=1 name=Guest
    WELCOME = "WELCOME"     # WELCOME v=1 role=HOST|GUEST
    MATCH = "MATCH"         # MATCH size=15 renju=1 you=2 (you color int)
    TURN = "TURN"           # TURN color=1

    # gameplay
    MOVE = "MOVE"           # MOVE x=1 y=1  (guest->host request or pvc internal)
    APPLY = "APPLY"         # APPLY x=1 y=1 color=1  (authoritative broadcast)
    WIN = "WIN"             # WIN color=1 x=... y=...
    ERR = "ERR"             # ERR msg="..."
    QUIT = "QUIT"           # QUIT msg="..."

    # sync
    STATE = "STATE"         # STATE (request snapshot)
    BOARD = "BOARD"         # BOARD size=15 (snapshot start)
    STONE = "STONE"         # STONE x=.. y=.. color=.. (snapshot contents)
    ENDSTATE = "ENDSTATE"   # ENDSTATE turn=.. winner=0|1|2

    # shared commands needing consent
    REQ = "REQ"             # REQ kind=UNDO|SWAP|RESTART from=Guest
    RESP = "RESP"           # RESP kind=UNDO ok=1|0 from=Host msg="optional"


@dataclass(frozen=True)
class NetMessage:
    """
    Typed message used by controllers.

    fields: dict of string->string (wire format is text)
    """
    type: MsgType
    fields: Dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default)

    def get_int(self, key: str, default: int = 0) -> int:
        v = self.fields.get(key, "")
        try:
            return int(v)
        except Exception:
            return default

    def get_bool01(self, key: str, default: bool = False) -> bool:
        v = self.fields.get(key, "")
        if v == "1":
            return True
        if v == "0":
            return False
        return default


def _quote(v: str) -> str:
    # Quote only if needed
    if v == "":
        return '""'
    if any(ch.isspace() for ch in v) or any(ch in v for ch in ['"', "=", "\\"]):
        # shlex compatible escaping via repr-like minimal quoting
        v = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{v}"'
    return v


def to_line(msg: NetMessage) -> str:
    """
    Serialize a NetMessage into one line (ending with \\n).
    Format: TYPE key=value key=value
    Values may be quoted with "..." if they contain spaces.
    """
    parts = [msg.type.value]
    for k, v in msg.fields.items():
        parts.append(f"{k}={_quote(str(v))}")
    return " ".join(parts) + "\n"


def parse_line(line: str) -> Optional[NetMessage]:
    """
    Parse one protocol line into NetMessage.
    Uses shlex.split so quoted values work.
    Returns None if line is empty/whitespace.
    """
    raw = (line or "").strip()
    if not raw:
        return None

    tokens = shlex.split(raw, posix=True)
    if not tokens:
        return None

    typ_token = tokens[0].upper()
    try:
        mtype = MsgType(typ_token)
    except Exception:
        # Unknown type is treated as ERR-like; controller may ignore or handle.
        return NetMessage(MsgType.ERR, {"msg": f"Unknown message type: {typ_token}"})

    fields: Dict[str, str] = {}
    for t in tokens[1:]:
        if "=" not in t:
            continue
        k, v = t.split("=", 1)
        fields[k] = v
    return NetMessage(mtype, fields)
