from dataclasses import dataclass, field
from typing import List, Optional
from src.core.board import Player, Position
from src.core.move import Move

@dataclass
class GameState:
    """Represents complete game state."""
    current_player: Player
    winner: Optional[Player] = None
    move_history: List[Move] = field(default_factory=list)
    last_move: Optional[Position] = None

    def is_game_over(self) -> bool:
        return self.winner is not None

    def record_move(self, move: Move) -> None:
        self.move_history.append(move)
        self.last_move = move.position

    def switch_turn(self) -> None:
        self.current_player = self.current_player.opponent()