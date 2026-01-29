from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.core.board import Board, Player, Position
from src.core.game import Game


# =========================
# Message types
# =========================

class MessageType(Enum):
    ERR = "ERR"
    INFO = "INFO"   # generic (moves, sync, connected) — [SWAP] only for actual swap
    YOU_MOVE = "YOU MOVE"
    OPP_MOVE = "OPP MOVE"
    SWAP = "SWAP"
    UNDO = "UNDO"
    RESTART = "RESTART"
    QUIT = "QUIT"


@dataclass(frozen=True)
class Message:
    """
    A UI message shown between board and state.
    Examples:
      [ERR] Invalid input
      [UNDO] Requested
    """
    type: MessageType
    text: str = ""

    def render(self) -> str:
        if self.text:
            return f"[{self.type.value}] {self.text}"
        return f"[{self.type.value}]"


# =========================
# Screen utils
# =========================

def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


# =========================
# View (board + message + state)
# =========================

class CliView:
    """
    Responsible ONLY for rendering:
      1) board
      2) message
      3) state line

    It does NOT:
      - parse input
      - send network messages
      - execute game logic
    """

    def __init__(
        self,
        *,
        you_name: str,
        you_color: Player,
        opp_name: str,
        opp_color: Player,
        prompt: str = "> ",
    ) -> None:
        self.you_name = you_name
        self.you_color = you_color
        self.opp_name = opp_name
        self.opp_color = opp_color
        self.prompt = prompt

        self._message: Optional[Message] = None

    # ---------- Message API ----------

    def set_message(self, msg: Optional[Message]) -> None:
        self._message = msg

    def set_error(self, text: str) -> None:
        self._message = Message(MessageType.ERR, text)

    def set_info(self, text: str = "") -> None:
        self._message = Message(MessageType.INFO, text) if text else None

    def set_move(self, text: str = "", is_you: bool = False) -> None:
        if text:
            t = MessageType.YOU_MOVE if is_you else MessageType.OPP_MOVE
            self._message = Message(t, text)
        else:
            self._message = None

    def set_swap(self, text: str = "") -> None:
        self._message = Message(MessageType.SWAP, text)

    def set_undo(self, text: str = "") -> None:
        self._message = Message(MessageType.UNDO, text)

    def set_restart(self, text: str = "") -> None:
        self._message = Message(MessageType.RESTART, text)

    def set_quit(self, text: str = "") -> None:
        self._message = Message(MessageType.QUIT, text)

    # ---------- Render ----------

    def render(self, game: Game) -> None:
        """
        Render:
          - board
          - message
          - state
          - prompt
        """
        clear_screen()

        # 1) board
        print(game.board.to_cli())
        print("")

        # 2) message
        if self._message is None:
            print("")
        else:
            print(self._message.render())

        # 3) state
        state_line = self._build_state_line(game)
        print(state_line)
        print(self.prompt, end="", flush=True)

    def _build_state_line(self, game: Game) -> str:
        turn_indicator = self._turn_indicator(game)
        return (
            f"{turn_indicator}   "
            f"You: {self.you_color.symbol()}   "
            f"Opponent: {self.opp_color.symbol()} ({self.opp_name})"
        )

    def _turn_indicator(self, game: Game) -> str:
        if game.winner is not None:
            if game.winner == self.you_color:
                return "☆ YOU WON ☆"
            return "♨ YOU LOST ♨"

        if game.is_game_over():
            return "GAME OVER"

        if game.current_player == self.you_color:
            return ">>> YOUR TURN <<<"
        return ">>> OPP TURN <<<"
