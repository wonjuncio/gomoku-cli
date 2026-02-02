
from typing import List, Tuple, Optional
from dataclasses import dataclass
import random

from gomoku.core.game import Game
from gomoku.core.board import Player
from gomoku.core.position import Position
from gomoku.utils.config import config

try:
    from gomoku.cython_ext.optimized import (
        evaluate_position_fast, 
        get_ordered_moves_fast,
        get_ordered_moves_enhanced_fast,
        CYTHON_AVAILABLE
    )
except ImportError:
    CYTHON_AVAILABLE = False


@dataclass
class PrioritizedMove:
    """Move with priority score."""

    position: Position
    priority: int


class MoveGenerator:
    """Generates and orders candidate moves for AI search."""

    def __init__(self, game: Game) -> None:
        """
        Initialize move generator.

        Args:
            game: Game instance
        """
        self.game = game

    def get_ordered_moves(self, depth: int, max_moves: Optional[int] = None) -> List[Position]:
        """
        Get candidate moves ordered by priority.

        Args:
            depth: Current search depth
            max_moves: Maximum number of moves to return (None = all)

        Returns:
            List of positions ordered by priority (best first)
        """
        # Use Cython optimized version if available
        if CYTHON_AVAILABLE:
            # Determine max moves based on depth
            if max_moves is None:
                if depth >= 7:  # Adjusted threshold to match config
                    max_moves = config.MAX_MOVES_DEPTH_HIGH
                else:
                    max_moves = config.MAX_MOVES_DEPTH_LOW
            
            # Use enhanced move generation for better quality
            moves = get_ordered_moves_enhanced_fast(
                self.game.board.to_array(),
                self.game.current_player,
                max_moves,
                config.SEARCH_DISTANCE,
                depth
            )
            
            # Convert to Position objects
            return [Position(row, col) for row, col in moves]
        
        if self.game.board.is_empty_board():
            center = self.game.board.get_center_position()
            offset_row = random.randint(-1, 1)
            offset_col = random.randint(-1, 1)
            return [
                Position(
                    row=center.row + offset_row, col=center.col + offset_col
                )
            ]

        # Determine max moves based on depth
        if max_moves is None:
            if depth >= 7:  # Adjusted threshold to match config
                max_moves = config.MAX_MOVES_DEPTH_HIGH
            else:
                max_moves = config.MAX_MOVES_DEPTH_LOW

        # Get candidate positions
        candidates = self.game.board.get_adjacent_positions(
            distance=config.SEARCH_DISTANCE
        )

        if not candidates:
            return []

        # Evaluate and prioritize moves
        prioritized = []
        for pos in candidates:
            can_move, _ = self.game.can_move(pos)
            if can_move:
                priority = self._evaluate_move_priority(pos)
                prioritized.append(PrioritizedMove(pos, priority))

        # Sort by priority (descending)
        prioritized.sort(key=lambda m: m.priority, reverse=True)

        # Group by priority level for better organization
        winning_moves = [m for m in prioritized if m.priority >= 40000]
        blocking_moves = [m for m in prioritized if 20000 <= m.priority < 40000]
        threat_moves = [m for m in prioritized if 5000 <= m.priority < 20000]
        good_moves = [m for m in prioritized if 100 <= m.priority < 5000]
        default_moves = [m for m in prioritized if m.priority < 100]

        # Build final move list
        result = []
        result.extend([m.position for m in winning_moves])
        result.extend([m.position for m in blocking_moves])

        # Add some threats
        current_len = len(result)
        result.extend([m.position for m in threat_moves[:2]])

        # Fill up to max_moves with good moves
        if len(result) < max_moves and good_moves:
            needed = max(1, max_moves - current_len)
            result.extend([m.position for m in good_moves[:needed]])

        # Fill remaining with default moves
        current_len = len(result)
        if len(result) < max_moves and default_moves:
            needed = max_moves - current_len
            result.extend([m.position for m in default_moves[:needed]])

        # Remove duplicates while preserving order
        seen = set()
        unique_result = []
        for pos in result:
            pos_tuple = (pos.row, pos.col)
            if pos_tuple not in seen:
                seen.add(pos_tuple)
                unique_result.append(pos)

        return unique_result[:max_moves]

    def _evaluate_move_priority(self, position: Position) -> int:
        """
        Evaluate priority of a move for move ordering.

        Args:
            position: Position to evaluate

        Returns:
            Priority score (higher = better)
        """
        if CYTHON_AVAILABLE:
            # Use fast Cython implementation
            return evaluate_position_fast(
                self.game.board.to_array(),
                position.row,
                position.col,
                self.game.current_player,
                Player.opponent(self.game.current_player),
            )

        # Fallback Python implementation
        return self._evaluate_move_priority_python(position)

    def _evaluate_move_priority_python(self, position: Position) -> int:
        """
        Python fallback for move priority evaluation.

        Args:
            position: Position to evaluate

        Returns:
            Priority score
        """
        priority = 0
        player = self.game.current_player
        opponent = Player.opponent(player)

        # Make a fast copy to test the move (no history needed)
        test_game = self.game.fast_copy()

        # Test current player's move
        test_game.board.place_stone(position, player)

        # Check for immediate win
        is_win, _ = test_game.validator.check_win_condition(
            position, player, test_game.captures[player]
        )
        if is_win:
            return 50000

        # Check for captures
        if not test_game.no_capture:
            captures = test_game.validator.check_captures(position, player)
            priority += len(captures) * 500

        # Check threats (4-in-a-row, 3-in-a-row)
        for dy, dx in [(0, 1), (1, 0), (1, 1), (1, -1)]:
            length = self._count_line(test_game, position, player, dy, dx)
            if length >= 4:
                priority += 15000
            elif length == 3:
                priority += 200
            elif length == 2:
                priority += 20

        # Remove test stone
        test_game.board.remove_stone(position)

        # Test opponent's move (blocking)
        test_game.board.place_stone(position, opponent)

        # Check if blocks opponent win
        is_win, _ = test_game.validator.check_win_condition(
            position, opponent, test_game.captures[opponent]
        )
        if is_win:
            priority += 45000

        # Check if blocks opponent threats
        for dy, dx in [(0, 1), (1, 0), (1, 1), (1, -1)]:
            length = self._count_line(test_game, position, opponent, dy, dx)
            if length >= 4:
                priority += 12000

        return priority

    def _count_line(
        self, game: Game, position: Position, player: int, dy: int, dx: int
    ) -> int:
        """
        Count consecutive stones in direction.

        Args:
            game: Game instance
            position: Starting position
            player: Player to count
            dy, dx: Direction vector

        Returns:
            Line length
        """
        count = 1
        board_array = game.board.to_array()

        # Forward
        r, c = position.row + dy, position.col + dx
        while (
            0 <= r < game.board.size
            and 0 <= c < game.board.size
            and board_array[r, c] == player
            and count < 5
        ):
            count += 1
            r += dy
            c += dx

        # Backward
        if count < 5:
            r, c = position.row - dy, position.col - dx
            while (
                0 <= r < game.board.size
                and 0 <= c < game.board.size
                and board_array[r, c] == player
                and count < 5
            ):
                count += 1
                r -= dy
                c -= dx

        return count

