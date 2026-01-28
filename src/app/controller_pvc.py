from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List

from src.app.controller_base import BaseController, ControllerEvent, EventType
from src.core.board import Player, Position
from src.cli.commands import Command, CommandProcessor, CommandType
from src.cli.view import CliView, Message, MessageType
from src.core.game import Game

# AI is in a separate file per your plan.
# Expected interface (reference only):
# class GomokuAI:
#     def __init__(self, color: str, lvl: int = 2): ...
#     def get_move(self, board: List[List[str]]) -> Optional[Tuple[int, int]]: ...
# from src.ai.gomoku_ai import GomokuAI  # adjust import path to your project layout


@dataclass
class PvCConfig:
    renju: bool = True
    lvl: int = 3
    board_size: int = 15
    tick_sec: float = 1.0


class PvCController(BaseController):
    """
    Player vs Computer controller.

    Key rules (per your spec):
      - /undo requires NO consent.
      - If playing vs AI, /undo undoes TWO plies (human + AI) when possible.
      - /restart requires NO consent.
      - /swap allowed only BEFORE the game starts:
          In PvC, /swap swaps YOUR color with AI color (so who is Black/White swaps).
          Because in Gomoku/Renju, Black always starts.
      - /quit exits (no remote notification).
    """

    def __init__(self, *, config: PvCConfig) -> None:
        self.cfg = config

        # Default: human is BLACK (O), AI is WHITE (X)
        self.you_color: Player = Player.BLACK
        self.ai_color: Player = Player.WHITE
        self.you_name: str = "You"
        self.ai_name: str = f"CPU(lvl{self.cfg.lvl})"

        game = Game(
            board_size=self.cfg.board_size,
            starting_player=Player.BLACK,   # black starts
            renju=self.cfg.renju,
        )

        view = CliView(
            you_name=self.you_name,
            you_color=self.you_color,
            opp_name=self.ai_name,
            opp_color=self.ai_color,
            prompt=">>> ",
        )

        cmd = CommandProcessor(board_size=self.cfg.board_size)

        super().__init__(game=game, view=view, command_processor=cmd, tick_sec=self.cfg.tick_sec)

        # AI instance (uses symbols 'O'/'X')
        self.ai = self._new_ai()

        # Avoid generating multiple AI events per tick
        self._ai_thinking: bool = False

    # ============================================================
    # Base hooks
    # ============================================================

    def on_start(self) -> None:
        self.view.set_message(Message(MessageType.RESTART, "PVC START"))
        self._dirty = True

    def on_quit_requested(self) -> None:
        self.view.set_message(Message(MessageType.QUIT, "Exiting..."))
        self._dirty = True

    # ============================================================
    # External events (AI)
    # ============================================================

    def poll_external_events(self) -> None:
        """
        If it's AI's turn, create an AI event (Position) and push it.
        We do NOT block long here; keep it simple and responsive.
        """
        if self.game.winner is not None:
            self._ai_thinking = False
            return

        if self.game.current_player != self.ai_color:
            self._ai_thinking = False
            return

        if self._ai_thinking:
            return

        self._ai_thinking = True

        pos = self._ai_choose_position()
        if pos is None:
            # No move: treat as game over (draw not modeled in core yet)
            self.view.set_message(Message(MessageType.ERR, "AI has no valid moves."))
            self._ai_thinking = False
            return

        self.push_event(ControllerEvent(EventType.AI, pos))

    def handle_event(self, event: ControllerEvent) -> None:
        if event.type != EventType.AI:
            return

        pos: Position = event.payload  # type: ignore[assignment]

        # Apply AI move via normal game path (validator etc.)
        if self.game.winner is not None:
            self._ai_thinking = False
            return

        if self.game.current_player != self.ai_color:
            self._ai_thinking = False
            return

        result = self.game.make_move(pos)
        if not result.success:
            # If AI picked invalid (shouldn’t), request another next tick
            self.view.set_message(Message(MessageType.ERR, f"AI invalid: {result.error_message}"))
            self._ai_thinking = False
            return

        self.view.set_message(Message(MessageType.SWAP, f"[OPP MOVE] {pos.x}, {pos.y} ({pos})"))
        self._ai_thinking = False

    # ============================================================
    # User commands
    # ============================================================

    def handle_command(self, command: Command) -> None:
        # y/n has no meaning in PVC
        if command.type in (CommandType.ACCEPT, CommandType.DECLINE):
            self.view.set_error("No confirmation needed vs AI.")
            return

        if command.type == CommandType.HELP:
            self.view.set_message(Message(MessageType.ERR, self.cmd.help_text()))
            return

        if command.type == CommandType.UNDO:
            self._undo_two_plies()
            return

        if command.type == CommandType.RESTART:
            self._restart()
            return

        if command.type == CommandType.SWAP:
            self._swap_colors_before_start()
            return

        self.view.set_error("Unknown/unsupported command. Use /help")

    # ============================================================
    # User move
    # ============================================================

    def handle_move(self, pos: Position) -> None:
        if self.game.winner is not None:
            self.view.set_error("Game is over.")
            return

        if self.game.current_player != self.you_color:
            self.view.set_error("Not your turn.")
            return

        result = self.game.make_move(pos)
        if not result.success:
            self.view.set_error(result.error_message)
            return

        self.view.set_message(Message(MessageType.SWAP, f"[YOU MOVE] {pos.x}, {pos.y} ({pos})"))

    # ============================================================
    # Helpers
    # ============================================================

    def _new_ai(self) -> GomokuAI:
        """
        AI expects color as 'O' or 'X'.
        Our Player mapping in this project:
          BLACK.symbol() -> 'O'
          WHITE.symbol() -> 'X'
        """
        return GomokuAI(color=self.ai_color.symbol(), lvl=self.cfg.lvl)

    def _board_as_symbols(self) -> List[List[str]]:
        """
        Convert Board -> List[List[str]] for AI:
          '.' empty, 'O' black, 'X' white
        """
        size = self.game.board.size
        grid: List[List[str]] = []
        for y in range(1, size + 1):
            row: List[str] = []
            for x in range(1, size + 1):
                row.append(self.game.board.get(Position(x, y)).symbol())
            grid.append(row)
        return grid

    def _ai_choose_position(self) -> Optional[Position]:
        """
        Ask AI for a move and convert to Position.

        IMPORTANT:
        AI's get_move(board) returns Optional[Tuple[int,int]].
        We will interpret it as 0-based (row, col) by default, because that's common.
        If your AI returns 0-based (x,y) or 1-based, adjust conversion here ONLY.
        """
        board = self._board_as_symbols()
        mv = self.ai.get_move(board)
        if mv is None:
            return None

        r, c = mv  # assume (row, col), 0-based
        x = c + 1
        y = r + 1

        pos = Position(x, y)

        # If AI returned illegal pos, try a fallback: pick any valid move adjacent
        if not self.game.can_move(pos):
            candidates = self.game.get_valid_moves(distance=2)
            for p in candidates:
                if self.game.can_move(p):
                    return p
            return None

        return pos

    def _undo_two_plies(self) -> None:
        """
        Undo rule vs AI:
          - Undo human last and AI last (up to two moves).
          - If only one move exists, undo one.
        """
        if not self.game.move_history:
            self.view.set_undo("No moves to undo.")
            return

        undone = 0

        # Undo last move
        if self.game.undo_last_move():
            undone += 1

        # If after undo it's still AI-vs-human, also undo one more
        if self.game.move_history:
            if self.game.undo_last_move():
                undone += 1

        self._ai_thinking = False
        self.view.set_undo(f"Undid {undone} move(s).")

    def _restart(self) -> None:
        self.game.reset()
        # Black always starts (renju/gomoku standard). If you are WHITE, AI(BLACK) starts.
        self.game.current_player = Player.BLACK
        self.game.winner = None
        self._ai_thinking = False
        self.view.set_restart("Game restarted.")

    def _swap_colors_before_start(self) -> None:
        """
        Swap your color with AI (only before game starts).
        After swap:
          - If you become WHITE, AI becomes BLACK and moves first.
          - If you become BLACK, you move first.
        """
        if not self.game.board.is_empty_board() or self.game.move_history:
            self.view.set_error("Swap is only allowed before the game starts.")
            return

        # Swap colors
        self.you_color, self.ai_color = self.ai_color, self.you_color
        self.ai = self._new_ai()

        # Reset game and set turn to BLACK (standard)
        self.game.reset()
        self.game.current_player = Player.BLACK

        # Update view so state line shows correct stones/names
        self.view = CliView(
            you_name=self.you_name,
            you_color=self.you_color,
            opp_name=self.ai_name,
            opp_color=self.ai_color,
            prompt=">>> ",
        )

        self._ai_thinking = False
        self.view.set_swap("Swapped colors. Black moves first.")
