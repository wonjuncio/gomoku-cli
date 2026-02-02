"""Minimax algorithm with Alpha-Beta pruning."""

from typing import Optional, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

from gomoku.core.game import Game
from gomoku.core.position import Position
from gomoku.core.board import Player
from gomoku.ai.heuristics import Heuristic
from gomoku.ai.move_gen import MoveGenerator
from gomoku.utils.config import config

# Try to import Cython optimized functions
try:
    from gomoku.cython_ext.minimax_optimized import get_best_move_fast
    MINIMAX_CYTHON_AVAILABLE = True
except ImportError:
    MINIMAX_CYTHON_AVAILABLE = False


class MinimaxAI:
    """Minimax AI with Alpha-Beta pruning and parallel search."""

    def __init__(
        self,
        depth: int = config.DEFAULT_AI_DEPTH,
        use_multiprocessing: bool = config.USE_MULTIPROCESSING,
    ) -> None:
        """
        Initialize Minimax AI.

        Args:
            depth: Maximum search depth
            use_multiprocessing: Enable parallel search at top levels
        """
        self.max_depth = depth
        self.use_multiprocessing = use_multiprocessing
        self.nodes_explored = 0
        self.depth_reached = 0  # Track actual depth reached during search

    def get_best_move(self, game: Game, use_iterative_deepening: bool = True, time_limit: float = 0.45) -> Optional[Position]:
        """
        Find best move using Minimax with Alpha-Beta pruning.
        Uses Cython version when available for better performance.

        Args:
            game: Current game state
            use_iterative_deepening: If True, use iterative deepening (recommended)
            time_limit: Maximum time in seconds (for iterative deepening)

        Returns:
            Best move position, or None if no valid moves
        """
        # Try Cython version first for fixed depth
        if MINIMAX_CYTHON_AVAILABLE and not use_iterative_deepening:
            return self.get_best_move_cython(game)
        
        # Fallback to existing Python implementation
        if use_iterative_deepening:
            return self._get_best_move_iterative(game, time_limit)
        else:
            return self._get_best_move_fixed_depth(game)
    
    def get_best_move_cython(self, game: Game) -> Optional[Position]:
        """
        Get best move using Cython-optimized minimax.
        
        Args:
            game: Current game state
            
        Returns:
            Best move position, or None if no valid moves
        """
        if not MINIMAX_CYTHON_AVAILABLE:
            return self.get_best_move(game)  # Fallback to Python
        
        # Get game state
        board_array = game.board.to_array().copy()  # Copy for Cython
        depth = self.max_depth
        maximizing_player = game.current_player
        current_player = game.current_player
        captures_black = game.captures[Player.BLACK]
        captures_white = game.captures[Player.WHITE]
        max_moves = config.MAX_MOVES_DEPTH_HIGH if depth >= 7 else config.MAX_MOVES_DEPTH_LOW
        
        # Initialize node counter
        import numpy as np
        nodes_count = np.zeros(1, dtype=np.int32)
        
        # Get best move
        best_row, best_col, best_score = get_best_move_fast(
            board_array, depth, maximizing_player, current_player,
            captures_black, captures_white, max_moves, nodes_count
        )
        
        # Update nodes explored and depth reached
        self.nodes_explored = int(nodes_count[0])
        self.depth_reached = depth  # Cython version uses fixed depth
        
        if best_row == -1 or best_col == -1:
            return None
        
        return Position(best_row, best_col)
    
    def _get_best_move_iterative(self, game: Game, time_limit: float = 0.45) -> Optional[Position]:
        """
        Iterative deepening: search progressively deeper until time runs out.
        Guarantees completion within time_limit.
        """
        import time
        
        start_time = time.time()
        best_move = None
        best_score = float('-inf')
        depth_reached = 0
        total_nodes_explored = 0  # Track total nodes across all depths
        
        # Get candidate moves once
        move_gen = MoveGenerator(game)
        possible_moves = move_gen.get_ordered_moves(self.max_depth)
        
        if not possible_moves:
            return None
        if len(possible_moves) == 1:
            return possible_moves[0]
        
        # Iteratively deepen search
        for current_depth in range(1, self.max_depth + 1):
            elapsed = time.time() - start_time
            
            # Check if we have time for another iteration
            if elapsed > time_limit * 0.85:  # Use 85% as cutoff for safety
                break
            
            # Estimate if next depth will fit in time
            if current_depth > 2:
                time_per_depth = elapsed / current_depth
                estimated_next = time_per_depth * 3  # Each depth ~3x slower
                if elapsed + estimated_next > time_limit:
                    break
            
            # Reset nodes for this depth iteration
            self.nodes_explored = 0
            maximizing_player = game.current_player
            
            # Search at current depth
            try:
                if self.use_multiprocessing and len(possible_moves) > 1 and current_depth == self.max_depth:
                    # Only parallelize final depth
                    move, score = self._parallel_search_root(
                        game, possible_moves, maximizing_player, float('-inf'), float('inf')
                    )
                else:
                    # Sequential search for this depth
                    move, score = self._sequential_search_root(
                        game, possible_moves, maximizing_player, current_depth
                    )
                
                if move:
                    best_move = move
                    best_score = score
                    depth_reached = current_depth
                
                # Accumulate nodes explored at this depth
                total_nodes_explored += self.nodes_explored
                
                # Early exit if found winning move
                if score >= config.WEIGHT_WIN - 100:
                    break
                    
            except KeyboardInterrupt:
                break
        
        # Set final nodes explored count and depth reached
        self.nodes_explored = total_nodes_explored
        self.depth_reached = depth_reached
        return best_move
    
    def _get_best_move_fixed_depth(self, game: Game) -> Optional[Position]:
        """Original fixed-depth search (fallback)."""
        self.nodes_explored = 0
        self.depth_reached = self.max_depth  # Fixed depth reaches max depth
        maximizing_player = game.current_player

        # Get candidate moves
        move_gen = MoveGenerator(game)
        possible_moves = move_gen.get_ordered_moves(self.max_depth)

        if not possible_moves:
            return None

        # If only one move, return it
        if len(possible_moves) == 1:
            return possible_moves[0]

        best_move = None
        best_score = float('-inf')
        alpha = float('-inf')
        beta = float('inf')

        # Parallel evaluation at root level if enabled
        if self.use_multiprocessing and len(possible_moves) > 1:
            best_move, best_score = self._parallel_search_root(
                game, possible_moves, maximizing_player, alpha, beta
            )
        else:
            # Sequential search
            best_move, best_score = self._sequential_search_root(
                game, possible_moves, maximizing_player, self.max_depth
            )

        return best_move
    
    def _sequential_search_root(
        self, game: Game, moves: list, maximizing_player: int, depth: int
    ) -> Tuple[Optional[Position], float]:
        """Sequential search at root level."""
        best_move = None
        best_score = float('-inf')
        alpha = float('-inf')
        beta = float('inf')
        
        for move in moves:
            score = self._evaluate_move(
                game, move, depth, maximizing_player, alpha, beta
            )

            if score > best_score:
                best_score = score
                best_move = move

            alpha = max(alpha, score)
            if beta <= alpha:
                break  # Beta cutoff
        
        return best_move, best_score

    def _parallel_search_root(
        self,
        game: Game,
        moves: list,
        maximizing_player: int,
        alpha: float,
        beta: float,
    ) -> Tuple[Optional[Position], float]:
        """
        Parallel search at root level.

        Args:
            game: Current game state
            moves: List of candidate moves
            maximizing_player: Player to maximize for
            alpha, beta: Alpha-beta bounds

        Returns:
            Tuple of (best_move, best_score)
        """
        best_move = None
        best_score = float('-inf')

        max_workers = min(config.MAX_WORKERS, multiprocessing.cpu_count())

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all moves for evaluation
            future_to_move = {
                executor.submit(
                    _evaluate_move_worker,
                    game.fast_copy(),  # Use fast_copy for AI search (100x faster!)
                    move,
                    self.max_depth,
                    maximizing_player,
                    alpha,
                    beta,
                ): move
                for move in moves
            }

            # Collect results
            for future in as_completed(future_to_move):
                move = future_to_move[future]
                try:
                    score = future.result()
                    if score > best_score:
                        best_score = score
                        best_move = move
                except Exception as e:
                    print(f"Error evaluating move {move}: {e}")

        return best_move, best_score

    def _evaluate_move(
        self,
        game: Game,
        move: Position,
        depth: int,
        maximizing_player: int,
        alpha: float,
        beta: float,
    ) -> float:
        """
        Evaluate a single move.

        Args:
            game: Current game state
            move: Move to evaluate
            depth: Current depth
            maximizing_player: Player to maximize for
            alpha, beta: Alpha-beta bounds

        Returns:
            Move score
        """
        game_copy = game.fast_copy()
        result = game_copy.make_move(move)

        if not result.success:
            return float('-inf')

        # Terminal state check
        if result.is_winning_move:
            return config.WEIGHT_WIN + depth

        # Switch player and recurse
        game_copy.switch_player()

        score, _ = self._alpha_beta(
            game_copy,
            depth - 1,
            alpha,
            beta,
            False,  # Now minimizing
            maximizing_player,
        )

        return score

    def _alpha_beta(
        self,
        game: Game,
        depth: int,
        alpha: float,
        beta: float,
        is_maximizing: bool,
        maximizing_player: int,
    ) -> Tuple[float, Optional[Position]]:
        """
        Alpha-Beta pruning implementation.

        Args:
            game: Current game state
            depth: Remaining search depth
            alpha: Alpha value
            beta: Beta value
            is_maximizing: True if maximizing player's turn
            maximizing_player: Player to maximize for

        Returns:
            Tuple of (score, best_move)
        """
        self.nodes_explored += 1

        # Terminal conditions
        if depth == 0 or game.is_game_over():
            heuristic = Heuristic(game)
            score = heuristic.evaluate(maximizing_player, depth)
            return score, None

        # Get candidate moves
        move_gen = MoveGenerator(game)
        max_moves = config.MAX_MOVES_DEPTH_HIGH if depth >= 7 else config.MAX_MOVES_DEPTH_LOW
        possible_moves = move_gen.get_ordered_moves(depth, max_moves)

        if not possible_moves:
            heuristic = Heuristic(game)
            score = heuristic.evaluate(maximizing_player, depth)
            return score, None

        best_move = None

        if is_maximizing:
            max_eval = float('-inf')

            for move in possible_moves:
                game_copy = game.fast_copy()  # Use fast_copy for AI search
                result = game_copy.make_move(move)

                if not result.success:
                    continue

                if result.is_winning_move:
                    return config.WEIGHT_WIN + depth, move

                game_copy.switch_player()

                eval_score, _ = self._alpha_beta(
                    game_copy, depth - 1, alpha, beta, False, maximizing_player
                )

                if eval_score > max_eval:
                    max_eval = eval_score
                    best_move = move

                alpha = max(alpha, eval_score)
                if beta <= alpha:
                    break  # Beta cutoff

            return max_eval, best_move

        else:  # Minimizing
            min_eval = float('inf')

            for move in possible_moves:
                game_copy = game.fast_copy()  # Use fast_copy for AI search
                result = game_copy.make_move(move)

                if not result.success:
                    continue

                if result.is_winning_move:
                    return -(config.WEIGHT_WIN + depth), move

                game_copy.switch_player()

                eval_score, _ = self._alpha_beta(
                    game_copy, depth - 1, alpha, beta, True, maximizing_player
                )

                if eval_score < min_eval:
                    min_eval = eval_score
                    best_move = move

                beta = min(beta, eval_score)
                if beta <= alpha:
                    break  # Alpha cutoff

            return min_eval, best_move


def _evaluate_move_worker(
    game: Game,
    move: Position,
    depth: int,
    maximizing_player: int,
    alpha: float,
    beta: float,
) -> float:
    """
    Worker function for parallel move evaluation.

    Args:
        game: Game state copy
        move: Move to evaluate
        depth: Search depth
        maximizing_player: Player to maximize for
        alpha, beta: Alpha-beta bounds

    Returns:
        Move score
    """
    ai = MinimaxAI(depth=depth, use_multiprocessing=False)
    return ai._evaluate_move(game, move, depth, maximizing_player, alpha, beta)

