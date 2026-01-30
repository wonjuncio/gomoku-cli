from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.core.game import Game
from src.core.board import Player, Position
from src.ai.config import AILevelConfig


@dataclass(frozen=True)
class PrioritizedMove:
    position: Position
    priority: int


class MoveGenerator:
    """
    Generates and orders candidate moves for AI search (1-based Position).

    Rules/assumptions aligned to this project:
      - Position is 1-based (x: 1..size, y: 1..size)
      - capture is not used
      - legality is checked by game.can_move(pos) (includes renju forbiddance if enabled)
    """

    # 4 directions: horizontal, vertical, diag, anti-diag
    _DIRS: Tuple[Tuple[int, int], ...] = ((1, 0), (0, 1), (1, 1), (1, -1))

    def __init__(
        self,
        game: Game,
        level_config: AILevelConfig,
    ) -> None:
        self.game = game
        self.level_config = level_config

    def get_ordered_moves(self) -> List[Position]:
        """
        Return candidate moves ordered by heuristic priority (best first).
        """