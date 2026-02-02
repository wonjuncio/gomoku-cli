from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union

from src.core.board import Position


class CommandType(Enum):
    QUIT = "quit"
    SWAP = "swap"
    RESTART = "restart"
    UNDO = "undo"
    HELP = "help"

    # For y/n prompts (swap/restart/undo 요청 수락/거절)
    ACCEPT = "accept"
    DECLINE = "decline"


@dataclass(frozen=True)
class Command:
    """Parsed command from user input."""
    type: CommandType
    raw: str


@dataclass(frozen=True)
class ParseResult:
    """
    Result of parsing one line input.
    Exactly one of (command, position) should be set on success.
    """
    command: Optional[Command] = None
    position: Optional[Position] = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.error == "" and (self.command is not None or self.position is not None)


ParsedInput = Union[Command, Position]


class CommandProcessor:
    """
    Parses user input line into:
      - Command (e.g. /undo)
      - Position (e.g. '8 8' or 'H8')
      - Accept/Decline response for prompts (y/n)

    This class does NOT execute anything. Controllers decide what to do.
    """

    def __init__(self, board_size: int = 15) -> None:
        if board_size <= 0:
            raise ValueError("board_size must be positive")
        self.board_size = board_size

    @property
    def help_cmds(self) -> str:
        cmds = ["/help", "/quit", "/swap", "/restart", "/undo"]
        return ", ".join(cmds)

    def help_text(self) -> str:
        col_end = chr(ord("A") + self.board_size - 1)
        return (
            f"Input: 'x y' (e.g. 8 8) or 'H8' (A-{col_end} + 1-{self.board_size}).\n"
            f"Commands: {self.help_cmds}"
        )

    # ---------- Public parse API ----------

    def parse(self, text: str, *, expecting_yn: bool = False) -> ParseResult:
        """
        Parse a raw input line.
        Returns ParseResult with either command or position on success.
        When expecting_yn is True (y/n prompt), invalid input shows "Enter Y or N".
        """
        raw = (text or "").strip()
        if not raw:
            return ParseResult(error="")  # treat as no-op line

        # y/n response (for swap/restart/undo confirmation)
        yn = raw.lower()
        if yn in ("y", "yes"):
            return ParseResult(command=Command(CommandType.ACCEPT, raw))
        if yn in ("n", "no"):
            return ParseResult(command=Command(CommandType.DECLINE, raw))

        # slash commands
        if raw.startswith("/"):
            cmd = raw[1:].strip().lower()
            if cmd == "quit":
                return ParseResult(command=Command(CommandType.QUIT, raw))
            if cmd == "swap":
                return ParseResult(command=Command(CommandType.SWAP, raw))
            if cmd == "restart":
                return ParseResult(command=Command(CommandType.RESTART, raw))
            if cmd == "undo":
                return ParseResult(command=Command(CommandType.UNDO, raw))
            if cmd == "help":
                return ParseResult(command=Command(CommandType.HELP, raw))

            return ParseResult(error=f"Unknown command: {raw}")

        # When in y/n prompt, only y/n are valid; anything else is invalid
        if expecting_yn:
            return ParseResult(error="Invalid input. Enter Y or N")

        # move: "x y" (1..board_size, 1..board_size)
        parts = raw.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            x, y = int(parts[0]), int(parts[1])
            if not self._is_in_bounds(x, y):
                return ParseResult(error=self._oob_msg(x, y))
            return ParseResult(position=Position(x, y))

        # move: "H8" (A..col_for_size + 1..board_size)
        if len(raw) >= 2 and raw[0].isalpha():
            col = raw[0].upper()
            rest = raw[1:].strip()
            if rest.isdigit():
                x = ord(col) - ord("A") + 1
                y = int(rest)
                if not self._is_in_bounds(x, y):
                    return ParseResult(error=self._oob_msg(x, y))
                return ParseResult(position=Position(x, y))

        return ParseResult(error="Invalid input. Use 'x y' or 'H8' or /help")

    # ---------- Helpers ----------

    def _is_in_bounds(self, x: int, y: int) -> bool:
        return 1 <= x <= self.board_size and 1 <= y <= self.board_size
    
    def _oob_msg(self, x: int, y: int) -> str:
        return f"Out of bounds: {x}, {y} (must be 1..{self.board_size})"
