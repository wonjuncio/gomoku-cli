"""Heuristic evaluation functions for game states."""

from typing import Tuple, List, Optional
import numpy as np
import time

from gomoku.core.game import Game
from gomoku.core.board import Player
from gomoku.core.position import Position
from gomoku.utils.config import config
from gomoku.ai.zobrist_learning import zobrist_learner
from gomoku.ai.simple_dynamic import simple_learner

try:
    from gomoku.cython_ext.optimized import (
        count_line_length_fast,
        check_capture_pattern_fast,
        evaluate_patterns_fast,
        count_capture_threats_fast,
        CYTHON_AVAILABLE,
    )
except ImportError:
    CYTHON_AVAILABLE = False

try:
    from gomoku.cython_ext.heuristic_optimized import (
        evaluate_position_comprehensive_fast,
        evaluate_patterns_fast_enhanced,
        count_capture_threats_fast_enhanced,
    )
    HEURISTIC_CYTHON_AVAILABLE = True
except ImportError:
    HEURISTIC_CYTHON_AVAILABLE = False


class Heuristic:
    """Heuristic evaluator for game positions."""

    def __init__(self, game: Game, use_dynamic: bool = True) -> None:
        """
        Initialize heuristic evaluator.

        Args:
            game: Game instance to evaluate
            use_dynamic: Whether to use dynamic pattern learning
        """
        self.game = game
        self.use_dynamic = use_dynamic

    def evaluate(self, maximizing_player: int, depth: int) -> int:
        """
        Evaluate game state from maximizing player's perspective.
        Now uses Cython optimization when available.

        Args:
            maximizing_player: Player we're trying to maximize score for
            depth: Current search depth (for terminal state bonuses)

        Returns:
            Heuristic score (positive favors maximizing player)
        """
        # Check terminal states
        if self.game.winner is not None and self.game.winner != Player.EMPTY:
            if self.game.winner == Player.DRAW:
                return 0  # Draw is neutral
            elif self.game.winner == maximizing_player:
                return config.WEIGHT_WIN + depth  # Prefer faster wins
            else:
                return -(config.WEIGHT_WIN + depth)  # Avoid fast losses

        # Use Cython optimized version if available
        if HEURISTIC_CYTHON_AVAILABLE:
            return int(evaluate_position_comprehensive_fast(
                self.game.board.to_array(),
                maximizing_player,
                self.game.captures[Player.BLACK],
                self.game.captures[Player.WHITE],
                depth
            ))

        # Fallback to existing Python implementation
        minimizing_player = Player.opponent(maximizing_player)
        score = 0

        # 1. Capture advantage
        max_captures = self.game.captures[maximizing_player]
        min_captures = self.game.captures[minimizing_player]
        score += (max_captures - min_captures) * config.WEIGHT_CAPTURE

        # Bonus if close to winning by captures
        if max_captures >= 8:
            score += 5000
        if min_captures >= 8:
            score -= 5000

        # 2. Pattern evaluation
        max_threats = self._evaluate_patterns(maximizing_player)
        min_threats = self._evaluate_patterns(minimizing_player)
        score += max_threats - min_threats

        # 3. Capture threat evaluation
        max_threat_count = self._count_capture_threats(maximizing_player)
        min_threat_count = self._count_capture_threats(minimizing_player)
        score += (max_threat_count - min_threat_count) * config.WEIGHT_CAPTURE_THREAT

        # 4. Dynamic pattern evaluation
        if self.use_dynamic:
            dynamic_score = self._evaluate_dynamic_patterns(maximizing_player)
            score += dynamic_score

        return score

    def _evaluate_patterns(self, player: int) -> int:
        """
        Evaluate alignment patterns for a player.

        Args:
            player: Player to evaluate

        Returns:
            Pattern score
        """
        # Use Cython optimized version if available
        if CYTHON_AVAILABLE:
            return evaluate_patterns_fast(self.game.board.to_array(), player)
        
        # Fallback to Python implementation
        score = 0
        board_array = self.game.board.to_array()

        # Check all positions with player's stones
        for row in range(self.game.board.size):
            for col in range(self.game.board.size):
                if board_array[row, col] == player:
                    # Check all 4 directions
                    for dy, dx in [(0, 1), (1, 0), (1, 1), (1, -1)]:
                        length = self._count_line_length(
                            Position(row, col), player, dy, dx
                        )

                        if length >= 5:
                            score += config.WEIGHT_WIN
                        elif length == 4:
                            freedom = self._get_pattern_freedom(Position(row, col), player, dy, dx)
                            if freedom == 2:  # FREE
                                score += config.WEIGHT_FOUR
                            elif freedom == 1:  # HALF_FREE
                                score += config.WEIGHT_FOUR_HALF
                            else:  # FLANKED
                                score += 500
                        elif length == 3:
                            freedom = self._get_pattern_freedom(Position(row, col), player, dy, dx)
                            if freedom == 2:  # FREE
                                score += config.WEIGHT_THREE
                            elif freedom == 1:  # HALF_FREE
                                score += config.WEIGHT_THREE_HALF
                            else:  # FLANKED
                                score += 50
                        elif length == 2:
                            freedom = self._get_pattern_freedom(Position(row, col), player, dy, dx)
                            if freedom == 2:  # FREE
                                score += config.WEIGHT_TWO
                            elif freedom == 1:  # HALF_FREE
                                score += config.WEIGHT_TWO_HALF
                            else:  # FLANKED
                                score += 5

        return score

    def _count_line_length(
        self, position: Position, player: int, dy: int, dx: int
    ) -> int:
        """
        Count consecutive stones in a direction.

        Args:
            position: Starting position
            player: Player to count
            dy, dx: Direction vector

        Returns:
            Number of consecutive stones
        """
        if CYTHON_AVAILABLE:
            return count_line_length_fast(
                self.game.board.to_array(),
                position.row,
                position.col,
                dy,
                dx,
                player,
            )

        # Fallback Python implementation
        count = 1
        board_array = self.game.board.to_array()

        # Forward
        r, c = position.row + dy, position.col + dx
        while (
            0 <= r < self.game.board.size
            and 0 <= c < self.game.board.size
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
                0 <= r < self.game.board.size
                and 0 <= c < self.game.board.size
                and board_array[r, c] == player
                and count < 5
            ):
                count += 1
                r -= dy
                c -= dx

        return count

    def _is_pattern_open(
        self, position: Position, player: int, dy: int, dx: int
    ) -> bool:
        """
        Check if pattern is open (not blocked) on both ends.

        Args:
            position: Pattern position
            player: Player to check
            dy, dx: Direction vector

        Returns:
            True if both ends are open
        """
        freedom = self._get_pattern_freedom(position, player, dy, dx)
        return freedom == 2  # FREE

    def _get_pattern_freedom(
        self, position: Position, player: int, dy: int, dx: int
    ) -> int:
        """
        Check pattern freedom status.

        Args:
            position: Pattern position
            player: Player to check
            dy, dx: Direction vector

        Returns:
            0 = FLANKED (both ends blocked)
            1 = HALF_FREE (one end free, one blocked)
            2 = FREE (both ends free)
        """
        board_array = self.game.board.to_array()

        # Find start of pattern
        start_row, start_col = position.row, position.col
        while (
            0 <= start_row - dy < self.game.board.size
            and 0 <= start_col - dx < self.game.board.size
            and board_array[start_row - dy, start_col - dx] == player
        ):
            start_row -= dy
            start_col -= dx

        # Find end of pattern
        end_row, end_col = position.row, position.col
        while (
            0 <= end_row + dy < self.game.board.size
            and 0 <= end_col + dx < self.game.board.size
            and board_array[end_row + dy, end_col + dx] == player
        ):
            end_row += dy
            end_col += dx

        # Check if ends are empty
        open_start = (
            0 <= start_row - dy < self.game.board.size
            and 0 <= start_col - dx < self.game.board.size
            and board_array[start_row - dy, start_col - dx] == Player.EMPTY
        )

        open_end = (
            0 <= end_row + dy < self.game.board.size
            and 0 <= end_col + dx < self.game.board.size
            and board_array[end_row + dy, end_col + dx] == Player.EMPTY
        )

        # Return freedom status
        if open_start and open_end:
            return 2  # FREE
        elif open_start or open_end:
            return 1  # HALF_FREE
        else:
            return 0  # FLANKED

    def _count_capture_threats(self, player: int) -> int:
        """
        Count number of potential captures for player.

        Args:
            player: Player to count threats for

        Returns:
            Number of capture opportunities
        """
        if self.game.no_capture:
            return 0

        # Use Cython optimized version if available
        if CYTHON_AVAILABLE:
            return count_capture_threats_fast(self.game.board.to_array(), player)
        
        # Fallback to Python implementation
        threat_count = 0
        board_array = self.game.board.to_array()

        # Check all player positions
        for row in range(self.game.board.size):
            for col in range(self.game.board.size):
                if board_array[row, col] == player:
                    # Check capture patterns in all directions
                    captures = check_capture_pattern_fast(
                        board_array, row, col, player
                    )
                    threat_count += len(captures)

        return threat_count

    def _check_capture_direction(
        self, position: Position, player: int, dy: int, dx: int
    ) -> bool:
        """
        Check if capture is possible in direction.

        Args:
            position: Starting position
            player: Player making capture
            dy, dx: Direction vector

        Returns:
            True if capture possible
        """
        opponent = Player.opponent(player)
        board_array = self.game.board.to_array()

        positions = [
            Position(position.row + i * dy, position.col + i * dx) for i in range(1, 4)
        ]

        # Check bounds
        if not all(self.game.board.is_valid_position(p) for p in positions):
            return False

        # Check pattern: player - opp - opp - player
        return (
            board_array[positions[0].row, positions[0].col] == opponent
            and board_array[positions[1].row, positions[1].col] == opponent
            and board_array[positions[2].row, positions[2].col] == player
        )

    def _evaluate_dynamic_patterns(self, maximizing_player: int) -> int:
        """
        Evaluate dynamic patterns using both Zobrist and sequence learning.
        
        Args:
            maximizing_player: Player to maximize for
            
        Returns:
            Dynamic pattern score
        """
        if not self.use_dynamic:
            return 0
        
        score = 0
        
        # 1. Zobrist position learning
        board_array = self.game.board.to_array()
        board_hash = zobrist_learner.get_board_hash(board_array)
        position_score = zobrist_learner.get_position_score(board_hash)
        score += int(position_score * 30)  # Reduced weight
        
        # 2. Sequence learning (learns from past actions)
        game_history = self.game.get_game_history()
        if len(game_history) >= 2:
            sequence_score = simple_learner.get_sequence_score(game_history)
            
            # Apply game phase bonus
            total_moves = len(game_history)
            game_phase = simple_learner.get_game_phase(total_moves)
            phase_bonus = simple_learner.get_phase_bonus(game_phase)
            
            sequence_score *= phase_bonus
            score += int(sequence_score * 100)  # Higher weight for sequence learning
        
        return score
    
    def learn_from_position(self, score: float) -> None:
        """
        Learn from current board position.
        
        Args:
            score: Evaluation score of current position
        """
        if not self.use_dynamic:
            return
        
        # Get Zobrist hash of current board
        board_array = self.game.board.to_array()
        board_hash = zobrist_learner.get_board_hash(board_array)
        
        # Learn from this position
        zobrist_learner.learn_from_position(board_hash, score)
    
    def learn_from_game(self, game_history: List[Tuple[Position, int]], winner: Optional[int]) -> None:
        """
        Learn patterns from a completed game.
        
        Args:
            game_history: List of (position, player) tuples
            winner: Winner of the game (None if draw)
        """
        if not self.use_dynamic or winner is None:
            return
        
        # 1. Learn from final position (Zobrist)
        final_score = self.evaluate(winner, 0)  # Evaluate from winner's perspective
        self.learn_from_position(final_score)
        
        # 2. Learn from move sequences (NEW - learns from past actions)
        simple_learner.learn_from_game(game_history, winner)
        
        # Clean up old patterns periodically
        zobrist_learner.clear_old_patterns()

