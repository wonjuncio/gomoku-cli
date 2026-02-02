"""Simple dynamic heuristic that learns from past player actions."""

from typing import Dict, List, Tuple, Optional
from collections import defaultdict, deque

from gomoku.core.board import Player
from gomoku.core.position import Position


class SimpleDynamicLearning:
    """Simple learning that tracks move sequences and their outcomes."""
    
    def __init__(self, max_sequence_length: int = 4):
        """
        Initialize simple dynamic learning.
        
        Args:
            max_sequence_length: Maximum length of move sequences to track
        """
        self.max_sequence_length = max_sequence_length
        self.sequence_scores: Dict[str, float] = defaultdict(float)
        self.sequence_count: Dict[str, int] = defaultdict(int)
        self.recent_games: deque = deque(maxlen=10)  # Keep last 10 games
    
    def learn_from_game(self, game_history: List[Tuple[Position, int]], winner: Optional[int]) -> None:
        """
        Learn from a complete game.
        
        Args:
            game_history: List of (position, player) tuples
            winner: Winner of the game (None if draw)
        """
        if winner is None or len(game_history) < 2:
            return
        
        # Store this game for learning
        self.recent_games.append((game_history, winner))
        
        # Learn from move sequences in this game
        self._learn_from_sequences(game_history, winner)
    
    def _learn_from_sequences(self, game_history: List[Tuple[Position, int]], winner: int) -> None:
        """Learn from move sequences in the game."""
        # Learn from sequences of different lengths
        for length in range(2, min(len(game_history) + 1, self.max_sequence_length + 1)):
            for start in range(len(game_history) - length + 1):
                sequence = game_history[start:start + length]
                sequence_key = self._encode_sequence(sequence)
                
                # Check if this sequence was played by the winner
                winner_played = any(move[1] == winner for move in sequence)
                
                if winner_played:
                    # This sequence led to success
                    self._update_sequence_score(sequence_key, True)
                else:
                    # This sequence was played by loser
                    self._update_sequence_score(sequence_key, False)
    
    def _update_sequence_score(self, sequence_key: str, success: bool) -> None:
        """Update score for a move sequence."""
        self.sequence_count[sequence_key] += 1
        
        # Use exponential moving average
        alpha = 0.1  # Learning rate
        current_score = self.sequence_scores[sequence_key]
        new_score = 1.0 if success else 0.0
        
        self.sequence_scores[sequence_key] = (1 - alpha) * current_score + alpha * new_score
    
    def _encode_sequence(self, moves: List[Tuple[Position, int]]) -> str:
        """Encode a sequence of moves as a string."""
        if not moves:
            return ""
        
        # Create relative encoding (relative to first move)
        first_pos = moves[0][0]
        encoded = []
        
        for pos, player in moves:
            rel_row = pos.row - first_pos.row
            rel_col = pos.col - first_pos.col
            encoded.append(f"{rel_row},{rel_col},{player}")
        
        return "|".join(encoded)
    
    def get_sequence_score(self, moves: List[Tuple[Position, int]]) -> float:
        """
        Get score for a sequence of moves.
        
        Args:
            moves: List of (position, player) tuples
            
        Returns:
            Score for this sequence (0.0 to 1.0)
        """
        if len(moves) < 2:
            return 0.0
        
        # Check all subsequences and return best score
        best_score = 0.0
        
        for length in range(2, min(len(moves) + 1, self.max_sequence_length + 1)):
            for start in range(len(moves) - length + 1):
                sequence = moves[start:start + length]
                sequence_key = self._encode_sequence(sequence)
                
                if sequence_key in self.sequence_scores:
                    score = self.sequence_scores[sequence_key]
                    
                    # Weight by frequency (more frequent = more reliable)
                    count = self.sequence_count[sequence_key]
                    frequency_weight = min(1.0, count / 3.0)  # Cap at 1.0
                    score *= frequency_weight
                    
                    best_score = max(best_score, score)
        
        return best_score
    
    def get_game_phase(self, total_moves: int) -> str:
        """Determine game phase based on number of moves."""
        if total_moves < 6:
            return 'opening'
        elif total_moves < 20:
            return 'midgame'
        else:
            return 'endgame'
    
    def get_phase_bonus(self, game_phase: str) -> float:
        """Get bonus multiplier for current game phase."""
        phase_bonuses = {
            'opening': 0.5,   # Less important in opening
            'midgame': 1.0,   # Most important in midgame
            'endgame': 1.5    # Very important in endgame
        }
        return phase_bonuses.get(game_phase, 1.0)


# Global simple learning instance
simple_learner = SimpleDynamicLearning()

