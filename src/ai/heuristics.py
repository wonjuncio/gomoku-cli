"""Simple heuristic evaluation for game states (no capture)."""

from typing import Set, Tuple

from src.core.game import Game
from src.core.board import Player, Position
from src.ai.config import (
    WEIGHT_WIN,
    WEIGHT_FOUR,
    WEIGHT_THREE,
    WEIGHT_TWO,
)


class Heuristic:
    """Evaluates board state from maximizing player's perspective."""

    def __init__(self, game: Game) -> None:
        self.game = game

    def evaluate(self, maximizing_player: Player, depth: int) -> int:
        """
        Evaluate current state. Positive = good for maximizing player.

        Args:
            maximizing_player: Player we are maximizing for.
            depth: Current search depth (used for terminal bonus).

        Returns:
            Heuristic score.
        """
        if self.game.winner is not None:
            if self.game.winner == Player.EMPTY:
                return 0
            if self.game.winner == maximizing_player:
                return WEIGHT_WIN + depth
            return -(WEIGHT_WIN + depth)

        minimizing_player = maximizing_player.opponent()
        score = self._pattern_score(maximizing_player) - self._pattern_score(minimizing_player)
        return score

    def _pattern_score(self, player: Player) -> int:
        """Sum pattern scores for all stones of player (by max line length per cell)."""
        board = self.game.board
        score = 0
        seen_lines: Set[Tuple[Position, int, int]] = set()  # (start_pos, dx, dy) for dedup

        for pos, p in board.iter_stones():
            if p != player:
                continue
            for dx, dy in board.directions():
                length = board.line_length_through(pos, player, dx, dy)
                if length < 2:
                    continue
                # Dedupe: same line from different cells (use normalized direction)
                start = self._line_start(pos, player, dx, dy, board)
                key = (start, dx, dy)
                if key in seen_lines:
                    continue
                seen_lines.add(key)
                if length >= 5:
                    score += WEIGHT_WIN
                elif length == 4:
                    score += WEIGHT_FOUR
                elif length == 3:
                    score += WEIGHT_THREE
                elif length == 2:
                    score += WEIGHT_TWO
        return score

    @staticmethod
    def _line_start(pos: Position, player: Player, dx: int, dy: int, board) -> Position:
        """First cell of the line going backward along (-dx, -dy)."""
        cur = pos
        while True:
            nx, ny = cur.x - dx, cur.y - dy
            if not (1 <= nx <= board.size and 1 <= ny <= board.size):
                return cur
            prev = Position(nx, ny)
            if board.get(prev) != player:
                return cur
            cur = prev
