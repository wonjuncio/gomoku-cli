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
        return (
            "Input: 'x y' (e.g. 8 8) or 'H8' (A-O + 1-15).\n"
            f"Commands: {self.help_cmds}"
        )

    # ---------- Public parse API ----------

    def parse(self, text: str) -> ParseResult:
        """
        Parse a raw input line.
        Returns ParseResult with either command or position on success.
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

        # move: "x y"
        parts = raw.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            x, y = int(parts[0]), int(parts[1])
            pos = Position(x, y)
            if not self._in_bounds(pos):
                return ParseResult(error=self._oob_msg(pos))
            return ParseResult(position=pos)

        # move: "H8" (A-O + 1-15)
        if len(raw) >= 2 and raw[0].isalpha():
            col = raw[0].upper()
            rest = raw[1:].strip()
            if rest.isdigit():
                x = ord(col) - ord("A") + 1
                y = int(rest)
                pos = Position(x, y)
                if not self._in_bounds(pos):
                    return ParseResult(error=self._oob_msg(pos))
                return ParseResult(position=pos)

        return ParseResult(error="Invalid input. Use 'x y' or 'H8' or /help")

    # ---------- Helpers ----------

    def _in_bounds(self, pos: Position) -> bool:
        return 1 <= pos.x <= self.board_size and 1 <= pos.y <= self.board_size

    def _oob_msg(self, pos: Position) -> str:
        # A-O는 15 기준이지만, board_size가 바뀌어도 숫자로 안내
        return f"Out of bounds: {pos.x}, {pos.y} (must be 1..{self.board_size})"
