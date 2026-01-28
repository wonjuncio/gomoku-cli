# game.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from board import Board, Player, Position
from move import Move, MoveResult
from gamestate import GameState
from movevalidator import MoveValidator


class Game:
    """
    Main game controller.

    Owns:
      - Board
      - MoveValidator
      - Current state fields (current_player, winner, history, last_move)

    Note:
      - Capture is NOT used (per your decision).
      - Renju optional rules are handled by MoveValidator(renju=True|False).
    """

    def __init__(
        self,
        board_size: int = 15,
        starting_player: Player = Player.BLACK,
        *,
        renju: bool = True,
    ) -> None:
        """
        Initialize game.

        Args:
            board_size: Size of the board (default: 15)
            starting_player: Player who moves first (default: BLACK)
            renju: Apply Renju forbidden-move rules for BLACK (default: True)
        """
        self.board = Board(board_size)
        self.validator = MoveValidator(renju=renju)

        # Game state
        self.starting_player: Player = starting_player
        self.current_player: Player = starting_player
        self.winner: Optional[Player] = None

        # History (store moves only; no capture)
        self.move_history: List[Move] = []
        self.last_move: Optional[Position] = None

    # -------------------------
    # State helpers
    # -------------------------

    def get_state(self) -> GameState:
        """Get current game state."""
        return GameState(
            current_player=self.current_player,
            winner=self.winner,
            move_history=list(self.move_history),
            last_move=self.last_move,
        )

    def is_game_over(self) -> bool:
        """Check if game is over (if there is winner, return true)."""
        return self.winner is not None

    # -------------------------
    # Move / validation
    # -------------------------

    def can_move(self, position: Position) -> bool:
        """Check if current player can make move at position."""
        move = Move(position=position, player=self.current_player)
        state = self.get_state()
        result = self.validator.validate(self.board, state, move)
        return result.success

    def make_move(self, position: Position) -> MoveResult:
        """
        Execute a move for the current player.

        Returns:
            MoveResult (success, error_message, is_winning_move)
        """
        move = Move(position=position, player=self.current_player)
        state = self.get_state()

        # validate (includes Renju forbidden checks if enabled)
        result = self.validator.validate(self.board, state, move)
        if not result.success:
            return result

        # apply
        self.board.place(position, self.current_player)
        self.move_history.append(move)
        self.last_move = position

        # end?
        if result.is_winning_move:
            self.winner = self.current_player
            return result

        # next turn
        self.switch_player()
        return result

    def switch_player(self) -> None:
        """Switch to next player."""
        self.current_player = self.current_player.opponent()

    def swap_player(self) -> bool:
        """
        Swap players first player <-> second player if the game has not started.

        Returns:
            True if swapped, False otherwise.
        """
        if not self.board.is_empty_board() or self.move_history:
            return False
        self.starting_player = self.starting_player.opponent()
        self.current_player = self.starting_player
        return True

    # -------------------------
    # Undo / valid moves
    # -------------------------

    def undo_last_move(self) -> bool:
        """
        Undo the last move.

        Returns:
            True if undone, False if no move to undo.
        """
        if not self.move_history:
            return False

        last = self.move_history.pop()
        pos = last.position

        # NOTE: Ideally Board exposes an `unplace()` method.
        # For now we do a minimal internal revert.
        r, c = (pos.y - 1, pos.x - 1)
        self.board._grid[r][c] = Player.EMPTY  # type: ignore[attr-defined]
        self.board._moves -= 1  # type: ignore[attr-defined]

        # restore turn to the player who made the undone move
        self.current_player = last.player

        # clear winner (undo may invalidate previous win)
        self.winner = None

        # update last_move
        self.last_move = self.move_history[-1].position if self.move_history else None
        return True

    def get_valid_moves(self, *, distance: int = 1) -> List[Position]:
        """
        Get all valid moves for current player.

        Strategy:
          - Use Board.get_adjacent_positions(distance) to keep it practical.
          - If board is empty, that method returns center by default.
        """
        candidates = self.board.get_adjacent_positions(distance=distance)
        valid: List[Position] = []
        for pos in candidates:
            if self.can_move(pos):
                valid.append(pos)
        return valid

    # -------------------------
    # Reset
    # -------------------------

    def reset(self) -> None:
        """Reset game to initial state."""
        self.board = Board(self.board.size)
        self.validator = MoveValidator(renju=self.validator.renju)
        self.current_player = self.starting_player
        self.winner = None
        self.move_history.clear()
        self.last_move = None
