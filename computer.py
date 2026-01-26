import random
from typing import List, Optional, Tuple

class GomokuAI:
    def __init__(self, color: str, lvl: int = 2):
        self.color = color # 'O' or 'X'
        self.opponent = "O" if color == "X" else "X"
        self.board_size = 0
        self.depth_limit = lvl
    
    def get_move(self, board: List[List[str]]) -> Optional[Tuple[int, int]]:
        self.board_size = len(board)

        candidates = self._get_candidates(board)
        if not candidates:
            c = self.board_size // 2
            return (c + 1, c + 1)

        best_move = candidates[0]
        best_score = float("-inf")

        # 2. Minimax 시작
        for move in candidates:
            y, x = move
            board[y][x] = self.color
            score = self._minimax(board, self.depth_limit - 1, False, float('-inf'), float('inf'))
            board[y][x] = "."

            if score > best_score:
                best_score = score
                best_move = move
        
        y, x = best_move
        return (x + 1, y + 1)

    def _minimax(self, board: List[List[str]], depth: int, is_maximizing: bool, alpha: float, beta: float) -> float:
        # 기저 조건: 승리 혹은 깊이 도달
        if depth == 0:
            return self._evaluate_board(board)

        candidates = self._get_candidates(board)
        if not candidates:
            return 0

        if is_maximizing:
            max_eval = float('-inf')
            for y, x in candidates:
                board[y][x] = self.color
                eval = self._minimax(board, depth - 1, False, alpha, beta)
                board[y][x] = "."
                max_eval = max(max_eval, eval)
                alpha = max(alpha, eval)
                if beta <= alpha:
                    break
            return max_eval
        else:
            min_eval = float('inf')
            for y, x in candidates:
                board[y][x] = self.opponent
                eval = self._minimax(board, depth - 1, True, alpha, beta)
                board[y][x] = "."
                min_eval = min(min_eval, eval)
                beta = min(beta, eval)
                if beta <= alpha:
                    break
            return min_eval

    def _get_candidates(self, board: List[List[str]]) -> List[Tuple[int, int]]:
        """비어있는 칸 중 기존 돌의 인접한 구역만 탐색하여 연산량 감소"""
        candidates = set()
        for y in range(self.board_size):
            for x in range(self.board_size):
                if board[y][x] != ".":
                    for dy in range(-1, 2):
                        for dx in range(-1, 2):
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < self.board_size and 0 <= nx < self.board_size and board[ny][nx] == ".":
                                candidates.add((ny, nx))
        return list(candidates)

    def _evaluate_board(self, board: List[List[str]]) -> float:
        """현재 보드 상태의 점수를 계산 (핵심 로직)"""
        # 단순 구현: 내 돌의 연속성 점수 합산 - 상대 돌의 연속성 점수 합산
        my_score = self._count_patterns(board, self.color)
        op_score = self._count_patterns(board, self.opponent)
        return my_score - op_score

    def _count_patterns(self, board: List[List[str]], color: str) -> int:
        """가로, 세로, 대각선의 패턴 점수 계산"""
        score = 0
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]  # 가로, 세로, 대각선, 역대각선
        
        for y in range(self.board_size):
            for x in range(self.board_size):
                if board[y][x] != color:
                    continue
                
                # 각 방향에 대해 패턴 검사
                for dx, dy in directions:
                    # 이전 위치를 확인하여 중복 카운팅 방지 (왼쪽/위쪽에서만 시작)
                    prev_x, prev_y = x - dx, y - dy
                    if (0 <= prev_x < self.board_size and 
                        0 <= prev_y < self.board_size and 
                        board[prev_y][prev_x] == color):
                        continue  # 이미 카운트된 패턴이므로 스킵
                    
                    # 연속된 돌 개수 세기
                    count = 1
                    nx, ny = x + dx, y + dy
                    while (0 <= nx < self.board_size and 
                           0 <= ny < self.board_size and 
                           board[ny][nx] == color):
                        count += 1
                        nx += dx
                        ny += dy
                    
                    # 패턴의 끝 위치
                    end_x, end_y = nx, ny
                    
                    # 반대 방향으로도 확인 (양쪽 끝 확인용)
                    back_x, back_y = x - dx, y - dy
                    
                    # 양쪽 끝의 상태 확인
                    forward_open = (end_x < 0 or end_x >= self.board_size or 
                                   end_y < 0 or end_y >= self.board_size or 
                                   board[end_y][end_x] == ".")
                    backward_open = (back_x < 0 or back_x >= self.board_size or 
                                    back_y < 0 or back_y >= self.board_size or 
                                    board[back_y][back_x] == ".")
                    
                    # 패턴 점수 계산
                    pattern_score = self._get_pattern_score(count, forward_open, backward_open)
                    score += pattern_score
        
        return score
    
    def _get_pattern_score(self, count: int, forward_open: bool, backward_open: bool) -> int:
        """패턴 길이와 개방 상태에 따른 점수 계산"""
        if count >= 5:
            return 1000000  # 5연속 (승리)
        
        is_open = forward_open and backward_open
        is_half_open = forward_open or backward_open
        
        if count == 4:
            if is_open:
                return 100000  # 열린 4 (다음 수에 승리 가능)
            elif is_half_open:
                return 10000   # 반열린 4
            else:
                return 1000    # 닫힌 4
        elif count == 3:
            if is_open:
                return 1000    # 열린 3
            elif is_half_open:
                return 100     # 반열린 3
            else:
                return 10      # 닫힌 3
        elif count == 2:
            if is_open:
                return 10      # 열린 2
            elif is_half_open:
                return 1       # 반열린 2
            else:
                return 0       # 닫힌 2 (거의 가치 없음)
        
        return 0  # 1개는 점수 없음