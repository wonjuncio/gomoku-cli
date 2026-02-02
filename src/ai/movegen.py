from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from src.core.game import Game
from src.core.board import Player, Position
from src.ai.config import (
    AILevelConfig,
    MAX_MOVES_DEPTH_LOW,
    MAX_MOVES_DEPTH_HIGH,
    SEARCH_DISTANCE,
)


@dataclass(frozen=True)
class PrioritizedMove:
    """Move with priority score (higher = better)."""
    position: Position
    priority: int


# Priority bands (aligned with sample: winning, blocking, threat, good, default)
PRIORITY_WIN = 40_000
PRIORITY_BLOCK = 20_000
PRIORITY_THREAT_LOW = 5_000
PRIORITY_GOOD_LOW = 100


class MoveGenerator:
    """
    Generates and orders candidate moves for AI search (1-based Position).

    Rules/assumptions aligned to this project:
      - Position is 1-based (x: 1..size, y: 1..size)
      - Capture is not used
      - Legality is checked by game.can_move(pos) (includes Renju forbiddance if enabled)
    """

    _DIRS: Tuple[Tuple[int, int], ...] = ((1, 0), (0, 1), (1, 1), (1, -1))

    def __init__(self, game: Game, level_config: AILevelConfig) -> None:
        self.game = game
        self.level_config = level_config

    def get_ordered_moves(
        self,
        depth: Optional[int] = None,
        max_moves: Optional[int] = None,
    ) -> List[Position]:
        """
        Return candidate moves ordered by heuristic priority (best first).

        Args:
            depth: Current search depth (used to choose max_moves when max_moves is None).
            max_moves: Maximum number of moves to return (None = use depth vs config).

        Returns:
            List of positions ordered by priority (best first).
        """
        if max_moves is None:
            d = depth if depth is not None else self.level_config.max_depth
            max_moves = MAX_MOVES_DEPTH_HIGH if d >= 5 else MAX_MOVES_DEPTH_LOW

        if self.game.board.is_empty_board():
            center = (self.game.board.size + 1) // 2
            dx = random.randint(-1, 1)
            dy = random.randint(-1, 1)
            pos = Position(center + dx, center + dy)
            return [pos] if self.game.board.in_bounds(pos) else [Position(center, center)]

        candidates = self.game.board.get_adjacent_positions(distance=SEARCH_DISTANCE)
        if not candidates:
            return []

        prioritized: List[PrioritizedMove] = []
        for pos in candidates:
            if self.game.can_move(pos):
                priority = self._evaluate_move_priority(pos)
                prioritized.append(PrioritizedMove(pos, priority))

        prioritized.sort(key=lambda m: m.priority, reverse=True)

        winning = [m for m in prioritized if m.priority >= PRIORITY_WIN]
        blocking = [m for m in prioritized if PRIORITY_BLOCK <= m.priority < PRIORITY_WIN]
        threat = [m for m in prioritized if PRIORITY_THREAT_LOW <= m.priority < PRIORITY_BLOCK]
        good = [m for m in prioritized if PRIORITY_GOOD_LOW <= m.priority < PRIORITY_THREAT_LOW]
        default = [m for m in prioritized if m.priority < PRIORITY_GOOD_LOW]

        result: List[Position] = []
        result.extend(m.position for m in winning)
        result.extend(m.position for m in blocking)
        result.extend(m.position for m in threat[:2])
        need = max_moves - len(result)
        if need > 0 and good:
            result.extend(m.position for m in good[:need])
        need = max_moves - len(result)
        if need > 0 and default:
            result.extend(m.position for m in default[:need])

        seen: set = set()
        unique: List[Position] = []
        for pos in result:
            key = (pos.x, pos.y)
            if key not in seen:
                seen.add(key)
                unique.append(pos)
        return unique[:max_moves]

    def _evaluate_move_priority(self, position: Position) -> int:
        """
        Evaluate priority of a move for move ordering (higher = better).
        Tests our move (win + threats) and blocking opponent win/threats.
        """
        player = self.game.current_player
        opponent = player.opponent()
        priority = 0

        # Test current player's move
        test = self.game.copy()
        result = test.make_move(position)
        if not result.success:
            return 0
        if result.is_winning_move:
            return 50_000
        for dx, dy in test.board.directions():
            length = test.board.line_length_through(position, player, dx, dy)
            if length >= 4:
                priority += 15_000
            elif length == 3:
                priority += 200
            elif length == 2:
                priority += 20
        test.undo_last_move()

        # Test opponent's move at same cell (blocking)
        block = self.game.copy()
        block.switch_player()
        res = block.make_move(position)
        if res.success and res.is_winning_move:
            priority += 45_000
        if res.success:
            for dx, dy in block.board.directions():
                length = block.board.line_length_through(position, opponent, dx, dy)
                if length >= 4:
                    priority += 12_000
                    break
        return priority
