"""Main AI engine interface."""

from typing import Optional
import time

from gomoku.core.game import Game
from gomoku.core.position import Position
from gomoku.ai.minimax import MinimaxAI
from gomoku.utils.timer import global_timer
from gomoku.utils.config import config


class AIEngine:
    """High-level AI engine interface."""

    def __init__(
        self,
        depth: int = config.DEFAULT_AI_DEPTH,
        time_limit: float = config.MAX_AI_TIME,
        use_multiprocessing: bool = config.USE_MULTIPROCESSING,
        verbose: bool = False,
    ) -> None:
        """
        Initialize AI engine.

        Args:
            depth: Search depth
            time_limit: Maximum time per move (seconds)
            use_multiprocessing: Enable parallel search
            verbose: Print debug information
        """
        self.depth = depth
        self.time_limit = time_limit
        self.use_multiprocessing = use_multiprocessing
        self.verbose = verbose
        self.ai = MinimaxAI(depth=depth, use_multiprocessing=use_multiprocessing)

    def get_move(self, game: Game) -> Optional[Position]:
        """
        Get best move for current game state.

        Args:
            game: Current game state

        Returns:
            Best move position, or None if no valid moves
        """
        global_timer.start_move()

        if self.verbose:
            self._print_thinking_header()

        start_time = time.time()
        best_move = self.ai.get_best_move(game)
        elapsed = time.time() - start_time

        global_timer.end_move()

        if self.verbose:
            self._print_move_result(best_move, elapsed)

        return best_move

    def get_move_with_timing(self, game: Game) -> tuple[Optional[Position], float]:
        """
        Get best move for current game state with timing.

        Args:
            game: Current game state

        Returns:
            Tuple of (best move position, elapsed time), or (None, 0.0) if no valid moves
        """
        global_timer.start_move()

        if self.verbose:
            self._print_thinking_header()

        start_time = time.time()
        best_move = self.ai.get_best_move(game)
        elapsed = time.time() - start_time

        global_timer.end_move()

        if self.verbose:
            self._print_move_result(best_move, elapsed)

        return best_move, elapsed

    def _print_thinking_header(self) -> None:
        """Print AI thinking header with details."""
        print("\n" + "=" * 60)
        algorithm = "Alpha-Beta Pruning" if self.use_multiprocessing else "Alpha-Beta"
        parallel = " (Parallel)" if self.use_multiprocessing else ""
        print(f"🤖 AI Calculating{parallel}...")
        print(f"   Algorithm: {algorithm}")
        print(f"   Max Depth: {self.depth}")
        print(f"   Time Limit: {self.time_limit}s")

    def _print_move_result(self, best_move: Optional[Position], elapsed: float) -> None:
        """Print detailed move result information."""
        # Calculation metrics
        print(f"\n⏱️  Calculation Time: {elapsed:.3f} seconds")
        print(f"🔍 Nodes Explored: {self.ai.nodes_explored:,}")
        
        if self.ai.nodes_explored > 0:
            nodes_per_sec = self.ai.nodes_explored / elapsed if elapsed > 0 else 0
            print(f"⚡ Search Speed: {nodes_per_sec:,.0f} nodes/sec")
        
        # Depth information
        print(f"📊 Search Depth: {self.depth}")
        
        # Move selection
        if best_move:
            print(f"🎯 Selected Move: {best_move}")
        else:
            print("❓ No valid move found")
        
        # Performance validation
        if elapsed <= self.time_limit:
            status = "✅ PASS"
            perf_msg = f"Within time limit ({self.time_limit}s)"
        else:
            status = "⚠️  WARNING"
            perf_msg = f"Exceeded time limit ({self.time_limit}s)"
        
        print(f"{status}: {perf_msg}")
        print("=" * 60 + "\n")

    def reset_statistics(self) -> None:
        """Reset timing statistics."""
        global_timer.reset_stats()

    def get_statistics(self) -> dict:
        """
        Get performance statistics.

        Returns:
            Dictionary with timing statistics
        """
        stats = global_timer.get_stats()
        return {
            "total_moves": stats.total_moves,
            "average_time": stats.average_time,
            "min_time": stats.min_time,
            "max_time": stats.max_time,
            "total_time": stats.total_time,
            "within_limit": stats.average_time <= self.time_limit,
        }

    def print_statistics(self) -> None:
        """Print performance statistics."""
        stats = self.get_statistics()

        if stats["total_moves"] == 0:
            print("No moves made yet")
            return

        print("\n" + "📊" * 20)
        print("📈 AI PERFORMANCE STATISTICS")
        print(f"🎯 Total moves: {stats['total_moves']}")
        print(f"⏱️  Average time: {stats['average_time']:.3f}s")
        print(f"⚡ Fastest move: {stats['min_time']:.3f}s")
        print(f"🐌 Slowest move: {stats['max_time']:.3f}s")
        print(f"🕒 Total time: {stats['total_time']:.3f}s")

        if stats["within_limit"]:
            print(
                f"✅ PASS: Average time ≤ {self.time_limit}s "
                f"({stats['average_time']:.3f}s)"
            )
        else:
            print(
                f"❌ FAIL: Average time > {self.time_limit}s "
                f"({stats['average_time']:.3f}s)"
            )
        print("📊" * 20)

