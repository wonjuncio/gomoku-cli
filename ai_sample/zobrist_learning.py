"""Simple Zobrist-based pattern learning for dynamic heuristic."""

import random
from typing import Dict, Optional
from collections import defaultdict

from gomoku.core.board import Player
from gomoku.core.position import Position


class ZobristLearning:
    """Simple pattern learning using Zobrist hashing."""
    
    def __init__(self, board_size: int = 19):
        """
        Initialize Zobrist learning.
        
        Args:
            board_size: Size of the game board
        """
        self.board_size = board_size
        self.pattern_scores: Dict[int, float] = defaultdict(float)  # hash -> score
        self.pattern_frequency: Dict[int, int] = defaultdict(int)   # hash -> count
        self._initialize_zobrist_table()
    
    def _initialize_zobrist_table(self) -> None:
        """Initialize Zobrist hash table."""
        # Create random numbers for each (position, player) combination
        self.zobrist_table = {}
        
        for row in range(self.board_size):
            for col in range(self.board_size):
                for player in [Player.BLACK, Player.WHITE]:
                    # Use position and player as key
                    key = (row, col, player)
                    self.zobrist_table[key] = random.getrandbits(64)
    
    def get_board_hash(self, board_array) -> int:
        """
        Calculate Zobrist hash of current board state.
        
        Args:
            board_array: 2D numpy array representing board
            
        Returns:
            Zobrist hash of board state
        """
        board_hash = 0
        actual_size = board_array.shape[0]  # Get actual board size
        
        for row in range(actual_size):
            for col in range(actual_size):
                if board_array[row, col] != Player.EMPTY:
                    key = (row, col, int(board_array[row, col]))
                    if key in self.zobrist_table:
                        board_hash ^= self.zobrist_table[key]
        
        return board_hash
    
    def learn_from_position(self, board_hash: int, score: float) -> None:
        """
        Learn from a board position and its evaluation.
        
        Args:
            board_hash: Zobrist hash of the position
            score: Evaluation score of the position
        """
        # Update pattern frequency
        self.pattern_frequency[board_hash] += 1
        
        # Update pattern score using exponential moving average
        alpha = 0.1  # Learning rate
        current_score = self.pattern_scores[board_hash]
        self.pattern_scores[board_hash] = (1 - alpha) * current_score + alpha * score
    
    def get_position_score(self, board_hash: int) -> float:
        """
        Get learned score for a board position.
        
        Args:
            board_hash: Zobrist hash of the position
            
        Returns:
            Learned score for the position
        """
        if board_hash not in self.pattern_scores:
            return 0.0
        
        # Weight by frequency (more frequent = more reliable)
        frequency = self.pattern_frequency[board_hash]
        frequency_weight = min(1.0, frequency / 5.0)  # Cap at 1.0
        
        return self.pattern_scores[board_hash] * frequency_weight
    
    def clear_old_patterns(self, max_patterns: int = 1000) -> None:
        """Clear old patterns to prevent memory bloat."""
        if len(self.pattern_scores) <= max_patterns:
            return
        
        # Keep only the most frequent patterns
        sorted_patterns = sorted(
            self.pattern_frequency.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        # Clear less frequent patterns
        patterns_to_keep = {hash_val for hash_val, _ in sorted_patterns[:max_patterns]}
        
        self.pattern_scores = {
            k: v for k, v in self.pattern_scores.items() 
            if k in patterns_to_keep
        }
        self.pattern_frequency = {
            k: v for k, v in self.pattern_frequency.items() 
            if k in patterns_to_keep
        }


# Global learning instance
zobrist_learner = ZobristLearning()
