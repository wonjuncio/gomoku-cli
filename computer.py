import random
from typing import List, Optional, Tuple

class GomokuAI:
    def __init__(self, color: str):
        self.color = color # 'O' or 'X'

    def get_move(self, board: List[List[str]]) -> Optional[Tuple[int, int]]:
        empty_cells = []
        for y in range(len(board)):
            for x in range(len(board[0])):
                if board[y][x] == ".":
                    empty_cells.append((x + 1, y + 1))
        
        if not empty_cells:
            return None
        return random.choice(empty_cells)