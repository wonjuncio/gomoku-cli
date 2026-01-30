from typing import Optional
import time
from src.core.game import Game
from src.core.board import Position
from src.ai.movegen import MoveGenerator
from src.ai.config import AILevelConfig

class MinimaxAI:
    """Minimax AI with Alpha-Beta pruning and parallel search."""

    def __init__(
        self,
        level_config: AILevelConfig,
        use_multiprocessing: bool = True,
    ) -> None:
        """
        Initialize Minimax AI.

        Args:
            level_config: Configuration for the AI level
            use_multiprocessing: Enable parallel search at top levels
        """
        self.level_config = level_config
        
        self.use_multiprocessing = use_multiprocessing
        self.nodes_explored = 0
        self.depth_reached = 0

    def get_best_move(self, game: Game) -> Optional[Position]:
        return self._get_best_move_iterative(game, self.level_config.time_limit)
        
    def _get_best_move_iterative(self, game: Game, time_limit: float) -> Optional[Position]:
        start_time = time.time()
        best_move = None
        best_score = float("-inf")
        depth_reached = 0
        total_nodes_explored = 0
        
        move_gen = MoveGenerator(game, level_config=self.level_config)
        possible_moves = move_gen.get_ordered_moves()
        

        return best_move