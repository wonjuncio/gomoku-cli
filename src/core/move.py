from __future__ import annotations
from dataclasses import dataclass
from src.core.board import Position, Player

@dataclass(frozen=True)
class Move:
    """Represents a move on the board."""
    position: Position
    player: Player

    def __str__(self) -> str:
        """String representation."""
        return f"Player {self.player.value} at {self.position}"

@dataclass
class MoveResult:
    """Result of executing a move."""
    success: bool
    is_winning_move: bool = False
    error_message: str = ""

    @staticmethod
    def ok(*, is_winning_move: bool = False) -> "MoveResult":
        return MoveResult(
            success=True,
            is_winning_move=is_winning_move,
            error_message="",
        )

    @staticmethod
    def fail(msg: str) -> "MoveResult":
        return MoveResult(
            success=False,
            is_winning_move=False,
            error_message=msg,
        )
        