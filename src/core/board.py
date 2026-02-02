from typing import List, Tuple, Iterator, Optional, Set, overload
import numpy as np
from dataclasses import dataclass
from enum import Enum

class Player(Enum):
    """Player constants."""
    EMPTY = 0
    BLACK = 1
    WHITE = 2

    def symbol(self) -> str:
        return {0: ".", 1: "O", 2: "X"}[self.value]
    
    def opponent(self) -> "Player":
        if self == Player.BLACK:
            return Player.WHITE
        if self == Player.WHITE:
            return Player.BLACK
        return Player.EMPTY

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Position:
    """
    Immutable position on the board.
    Coordinates are 1-based: (1..15, 1..15)
    """
    x: int
    y: int

    def __post_init__(self):
        if not isinstance(self.x, int) or not isinstance(self.y, int):
            raise TypeError("Position coordinates must be integers")
        if self.x < 1 or self.y < 1:
            raise ValueError("Position coordinates must be >= 1")

    def __str__(self) -> str:
        """Return human-readable form like H8."""
        col = chr(ord("A") + self.x - 1)
        return f"{col}{self.y}"

    def in_bounds(self, size: int) -> bool:
        """Check if this position is within board size."""
        return 1 <= self.x <= size and 1 <= self.y <= size
    
class Board:
    """
    Represents the game board state.

    - Uses 1-based Position (x,y) externally.
    - Internally stores a size x size grid of Player.
    """

    def __init__(self, size: int = 15) -> None:
        if not isinstance(size, int) or size <= 0:
            raise ValueError("size must be a positive integer")
        self._size: int = size
        self._grid: List[List[Player]] = [
            [Player.EMPTY for _ in range(size)] for _ in range(size)
        ]
        self._moves: int = 0  # number of placed stones (non-empty)

    @property
    def size(self) -> int:
        return self._size

    @property
    def moves(self) -> int:
        return self._moves

    def copy(self) -> "Board":
        """Create a deep copy of the board."""
        new_board = Board(self.size)
        new_board._grid = np.copy(self._grid)
        new_board._moves = self._moves
        return new_board
    
    # ---------- Bounds / indexing ----------

    @overload
    def in_bounds(self, pos: Position) -> bool: ...
    
    @overload
    def in_bounds(self, x: int, y: int) -> bool: ...

    def in_bounds(self, arg1: Position | int, arg2: int | None = None) -> bool:
        if isinstance(arg1, Position):
            # in_bounds(pos)
            x, y = arg1.x, arg1.y
        else:
            # in_bounds(x, y)
            if arg2 is None:
                raise TypeError("in_bounds(x, y) requires both x and y")
            x, y = arg1, arg2

        return 1 <= x <= self._size and 1 <= y <= self._size

    def _idx(self, pos: Position) -> Tuple[int, int]:
        """Convert 1-based Position to 0-based (row, col)."""
        if not self.in_bounds(pos):
            raise ValueError(f"Out of bounds: {pos} for size={self._size}")
        return (pos.y - 1, pos.x - 1)

    # ---------- Cell access ----------

    def get(self, pos: Position) -> Player:
        r, c = self._idx(pos)
        return self._grid[r][c]

    def is_empty(self, pos: Position) -> bool:
        return self.get(pos) == Player.EMPTY

    def place(self, pos: Position, player: Player) -> None:
        """
        Place a stone at pos.

        Raises:
            ValueError if out of bounds, occupied, or player is EMPTY.
        """
        if player == Player.EMPTY:
            raise ValueError("Cannot place EMPTY")
        r, c = self._idx(pos)
        if self._grid[r][c] != Player.EMPTY:
            raise ValueError(f"Cell occupied at {pos}")
        self._grid[r][c] = player
        self._moves += 1
        
    def unplace(self, pos: Position) -> None:
        """
        Remove a stone at pos (set to EMPTY).

        Raises:
            ValueError if the cell is already empty.
        """
        if not self.in_bounds(pos):
            raise ValueError(f"Out of bounds: {pos}")

        r, c = self._idx(pos)
        if self._grid[r][c] == Player.EMPTY:
            raise ValueError(f"Cell already empty at {pos}")

        self._grid[r][c] = Player.EMPTY
        self._moves -= 1

    def swap_colors(self) -> None:
        """
        Swap BLACK <-> WHITE stones on the board.
        (EMPTY stays EMPTY)
        """
        for r in range(self._size):
            for c in range(self._size):
                if self._grid[r][c] == Player.BLACK:
                    self._grid[r][c] = Player.WHITE
                elif self._grid[r][c] == Player.WHITE:
                    self._grid[r][c] = Player.BLACK

    def clear(self) -> None:
        """Reset board to empty."""
        for r in range(self._size):
            for c in range(self._size):
                self._grid[r][c] = Player.EMPTY
        self._moves = 0

    # ---------- Iteration / helpers ----------

    def iter_stones(self) -> Iterator[Tuple[Position, Player]]:
        """Yield all non-empty stones as (Position, Player)."""
        for y in range(1, self._size + 1):
            for x in range(1, self._size + 1):
                p = self._grid[y - 1][x - 1]
                if p != Player.EMPTY:
                    yield Position(x, y), p

    def empty_positions(self) -> Iterator[Position]:
        """Yield all empty cells."""
        for y in range(1, self._size + 1):
            for x in range(1, self._size + 1):
                if self._grid[y - 1][x - 1] == Player.EMPTY:
                    yield Position(x, y)

    def is_empty_board(self) -> bool:
        """Check if board is completely empty."""
        return self._moves == 0

    def get_adjacent_positions(self, distance: int = 1) -> List[Position]:
        """
        Get all empty positions adjacent to existing stones.

        Args:
            distance: How many cells away to search (default: 1).
                      Uses Chebyshev neighborhood: any (dx,dy) with
                      max(|dx|,|dy|) <= distance, excluding (0,0).

        Returns:
            List of empty positions near stones (unique, sorted).
            If board is empty, returns all positions (common for opening move).
        """
        if distance < 1:
            raise ValueError("distance must be >= 1")

        if self.is_empty_board():
            return [Position(x, y) for y in range(1, self._size + 1) for x in range(1, self._size + 1)]

        candidates: Set[Position] = set()

        for (pos, _) in self.iter_stones():
            for dy in range(-distance, distance + 1):
                for dx in range(-distance, distance + 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = pos.x + dx, pos.y + dy
                    if 1 <= nx <= self._size and 1 <= ny <= self._size:
                        npos = Position(nx, ny)
                        if self.is_empty(npos):
                            candidates.add(npos)

        return sorted(candidates, key=lambda p: (p.y, p.x))
    
    # ---------- Directional scan (for win checks, patterns, renju later) ----------

    @staticmethod
    def directions() -> Tuple[Tuple[int, int], ...]:
        """4 unique directions (opposites are implied)."""
        return ((1, 0), (0, 1), (1, 1), (1, -1))

    def step(self, pos: Position, dx: int, dy: int) -> Optional[Position]:
        """Return next position by (dx,dy) or None if out of bounds."""
        nx, ny = pos.x + dx, pos.y + dy
        if 1 <= nx <= self._size and 1 <= ny <= self._size:
            return Position(nx, ny)
        return None

    def count_in_direction(self, start: Position, player: Player, dx: int, dy: int) -> int:
        """
        Count consecutive stones of `player` from `start` outward in direction (dx,dy),
        excluding the start cell itself.
        """
        count = 0
        cur = start
        while True:
            nxt = self.step(cur, dx, dy)
            if nxt is None:
                break
            if self.get(nxt) != player:
                break
            count += 1
            cur = nxt
        return count

    def line_length_through(self, pos: Position, player: Player, dx: int, dy: int) -> int:
        """
        Total consecutive length of `player` stones passing through `pos`
        along direction (dx,dy), including pos.
        """
        return (
            1
            + self.count_in_direction(pos, player, dx, dy)
            + self.count_in_direction(pos, player, -dx, -dy)
        )

    # ---------- Rendering (optional but useful for minimal UI) ----------

    def to_ascii(self, show_coords: bool = True) -> str:
        """
        Render board as ASCII.
        Uses Player.symbol(): EMPTY '.', BLACK 'O', WHITE 'X'
        """
        lines: List[str] = []
        if show_coords:
            header = " ".join([str(i).rjust(2) for i in range(1, self._size + 1)])
            lines.append("    " + header)
        for y in range(1, self._size + 1):
            row_syms = [self._grid[y - 1][x - 1].symbol().rjust(2) for x in range(1, self._size + 1)]
            if show_coords:
                lines.append(str(y).rjust(3) + " " + "".join(row_syms))
            else:
                lines.append("".join(row_syms))
        return "\n".join(lines)
    
    def to_cli(self) -> str:
        letters = [chr(ord("A") + i) for i in range(self._size)]
        lines = []
        lines.append("     " + " ".join(letters))
        for y in range(1, self._size + 1):
            row = []
            for x in range(1, self._size + 1):
                row.append(self._grid[y - 1][x - 1].symbol())
            lines.append(f"{str(y).rjust(3)}  " + " ".join(row))
        return "\n".join(lines)