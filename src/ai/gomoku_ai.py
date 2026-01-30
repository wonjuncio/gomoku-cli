from typing import List, Optional, Tuple
from src.core.board import Player, Position
from src.core.game import Game
from src.ai.minimax import MinimaxAI
from src.ai.config import AI_LEVELS

class GomokuAI:
    def __init__(
        self, 
        player: Player, 
        lvl: int = 3,
        use_multiprocessing: bool = True,
    ) -> None:
        self.player = player
        self.opponent = player.opponent()
        self.use_multiprocessing = use_multiprocessing
        cfg = AI_LEVELS[lvl]
        self.ai = MinimaxAI(level_config=cfg, use_multiprocessing=use_multiprocessing)
    
    def get_move(self, game: Game) -> Optional[Position]:
        """
        Get the best move for the AI.
        1-based (x,y) Position.
        """
        return self.ai.get_best_move(game)