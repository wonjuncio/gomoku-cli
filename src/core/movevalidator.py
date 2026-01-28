from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.core.board import Board, Position, Player
from src.core.move import Move, MoveResult
from src.core.gamestate import GameState


@dataclass
class MoveValidator:
    """
    Validates moves according to Gomoku rules.
    If renju=True (default), apply Renju forbidden-move rules for BLACK:
      - Overline (6+ in a row) forbidden
      - Double-three (33) forbidden
      - Double-four (44) forbidden
      - BLACK wins only with EXACTLY 5; WHITE wins with 5+
    """
    renju: bool = True

    def validate(self, board: Board, state: GameState, move: Move) -> MoveResult:
        # ---------- Common validations ----------
        if state.winner is not None:
            return MoveResult.fail("Game is already over.")

        if move.player != state.current_player:
            return MoveResult.fail("Not your turn.")

        if not board.in_bounds(move.position):
            return MoveResult.fail("Move is out of bounds.")

        if not board.is_empty(move.position):
            return MoveResult.fail("Cell is already occupied.")

        # ---------- Win / forbidden checks (virtual placement) ----------
        winning = self._is_winning_move(board, move.position, move.player)

        if self.renju and move.player == Player.BLACK:
            # Overline forbidden for black
            if self._is_overline(board, move.position, Player.BLACK):
                return MoveResult.fail("Forbidden move (Renju): overline (6+).")

            # Double-three / Double-four forbidden for black
            threes = self._count_open_threes(board, move.position, Player.BLACK)
            if threes >= 2:
                return MoveResult.fail("Forbidden move (Renju): double-three (33).")

            fours = self._count_fours(board, move.position, Player.BLACK)
            if fours >= 2:
                return MoveResult.fail("Forbidden move (Renju): double-four (44).")

        return MoveResult.ok(is_winning_move=winning)

    # ============================================================
    # Virtual evaluation helpers (do NOT mutate the board)
    # ============================================================

    def _cell_virtual(self, board: Board, pos: Position, placed_pos: Position, placed_player: Player) -> Player:
        if pos == placed_pos:
            return placed_player
        return board.get(pos)

    def _line_length_through_virtual(self, board: Board, center: Position, player: Player, dx: int, dy: int) -> int:
        # count same-color stones through center in direction (dx,dy), including center as player
        total = 1

        # forward
        cur = center
        while True:
            nxt = Position(cur.x + dx, cur.y + dy)
            if not board.in_bounds(nxt):
                break
            if self._cell_virtual(board, nxt, center, player) != player:
                break
            total += 1
            cur = nxt

        # backward
        cur = center
        while True:
            nxt = Position(cur.x - dx, cur.y - dy)
            if not board.in_bounds(nxt):
                break
            if self._cell_virtual(board, nxt, center, player) != player:
                break
            total += 1
            cur = nxt

        return total

    def _is_overline(self, board: Board, pos: Position, player: Player) -> bool:
        # For black in renju: any line length >= 6 is forbidden
        for dx, dy in board.directions():
            if self._line_length_through_virtual(board, pos, player, dx, dy) >= 6:
                return True
        return False

    def _is_winning_move(self, board: Board, pos: Position, player: Player) -> bool:
        for dx, dy in board.directions():
            length = self._line_length_through_virtual(board, pos, player, dx, dy)
            if self.renju and player == Player.BLACK:
                if length == 5:
                    return True
            else:
                if length >= 5:
                    return True
        return False

    # ============================================================
    # Pattern-based Renju checks (approx but practical)
    # ============================================================

    def _build_line_string(self, board: Board, center: Position, player: Player, dx: int, dy: int, span: int = 4) -> str:
        """
        Build a 1D string of cells along a direction around center:
          - 'B' for BLACK
          - 'W' for WHITE
          - '.' for EMPTY
          - 'X' for border/outside
        Includes the virtual placed stone at center for `player`.
        Length = 2*span + 1 (default 9).
        """
        chars: List[str] = []
        for k in range(-span, span + 1):
            pos = Position(center.x + k * dx, center.y + k * dy)
            if not board.in_bounds(pos):
                chars.append("X")
                continue
            cell = self._cell_virtual(board, pos, center, player)
            if cell == Player.EMPTY:
                chars.append(".")
            elif cell == Player.BLACK:
                chars.append("B")
            else:
                chars.append("W")
        return "".join(chars)

    def _count_open_threes(self, board: Board, center: Position, player: Player) -> int:
        """
        Count directions that contain an "open three" created by placing at center.
        Open three patterns (common practical set):
          .BBB.
          .BB.B.
          .B.BB.
        """
        if player != Player.BLACK:
            return 0  # renju forbiddens apply to black only (for our use)

        patterns = [".BBB.", ".BB.B.", ".B.BB."]

        count = 0
        for dx, dy in board.directions():
            s = self._build_line_string(board, center, player, dx, dy, span=4)

            # Reject if the pattern crosses borders (X) in a way that fakes openness
            if "X" in s:
                # Still can have valid patterns; we'll just search normally since patterns use '.'
                pass

            if any(p in s for p in patterns):
                count += 1
        return count

    def _count_fours(self, board: Board, center: Position, player: Player) -> int:
        """
        Count directions that contain a "four" (one move away from five).
        Practical patterns to detect:
          Open four:  .BBBB.
          Closed/straight four: BBBB. or .BBBB
          Broken fours (with one gap): BBB.B, BB.BB, B.BBB
        """
        if player != Player.BLACK:
            return 0

        patterns = [
            ".BBBB.",  # open four
            "BBBB.",   # straight four (right open)
            ".BBBB",   # straight four (left open)
            "BBB.B",   # broken four
            "BB.BB",
            "B.BBB",
        ]

        count = 0
        for dx, dy in board.directions():
            s = self._build_line_string(board, center, player, dx, dy, span=5)  # 조금 더 넓게
            if any(p in s for p in patterns):
                count += 1
        return count
