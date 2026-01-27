import random
import heapq
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

        # 1. 즉시 승리 수 체크 (내가 지금 두면 바로 이기는 수)
        winning_move = self._find_winning_move(board, candidates, self.color)
        if winning_move:
            y, x = winning_move
            return (x + 1, y + 1)
        
        # 2. 즉시 방어 수 체크 (상대가 다음 수에 이기는 수를 막는 수)
        blocking_move = self._find_blocking_move(board, candidates)
        if blocking_move:
            y, x = blocking_move
            return (x + 1, y + 1)

        # 후보를 정렬하여 좋은 수를 먼저 탐색 (상위 20개만 선택 - 최적화)
        candidates = self._sort_candidates(board, candidates, True, max_needed=20)

        best_move = candidates[0]
        best_score = float("-inf")

        # Minimax with alpha-beta pruning
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
        # 승리 체크 (깊이와 관계없이)
        winner = self._check_winner(board)
        if winner == self.color:
            return 1000000 - depth  # 빠르게 승리할수록 높은 점수
        elif winner == self.opponent:
            return -1000000 + depth  # 상대가 빠르게 승리할수록 낮은 점수
        
        # 기저 조건: 깊이 도달
        if depth == 0:
            # 로컬 평가 사용 (전판 스캔 대신)
            return self._evaluate_local(board)

        candidates = self._get_candidates(board)
        if not candidates:
            return 0

        # 깊이에 따라 후보 수 제한 (깊을수록 더 적게)
        max_candidates = self._get_max_candidates_for_depth(depth)
        
        # 후보를 점수 순으로 정렬 (상위 K개만 선택 - 최적화)
        candidates = self._sort_candidates(board, candidates, is_maximizing, max_needed=max_candidates * 2)
        
        # 즉시 위협 차단 후보 분리 (컷에서 제외)
        critical_moves = []
        regular_moves = []
        for move in candidates:
            y, x = move
            # 상대가 다음 수에 이기는 수인지 확인
            board[y][x] = self.opponent if is_maximizing else self.color
            winner = self._check_winner(board, (y, x))
            board[y][x] = "."
            if winner:
                critical_moves.append(move)
            else:
                regular_moves.append(move)
        
        # 즉시 위협 차단 후보는 항상 포함
        if len(regular_moves) > max_candidates - len(critical_moves):
            regular_moves = regular_moves[:max_candidates - len(critical_moves)]
        candidates = critical_moves + regular_moves

        if is_maximizing:
            max_eval = float('-inf')
            for y, x in candidates:
                board[y][x] = self.color
                eval = self._minimax(board, depth - 1, False, alpha, beta)
                board[y][x] = "."
                max_eval = max(max_eval, eval)
                alpha = max(alpha, max_eval)  # 버그 수정: max_eval 사용
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
                beta = min(beta, min_eval)  # 버그 수정: min_eval 사용
                if beta <= alpha:
                    break
            return min_eval

    def _find_winning_move(self, board: List[List[str]], candidates: List[Tuple[int, int]], color: str) -> Optional[Tuple[int, int]]:
        """즉시 승리 수 찾기 (내가 지금 두면 바로 이기는 수)"""
        for move in candidates:
            y, x = move
            board[y][x] = color
            winner = self._check_winner(board, (y, x))  # 마지막 수 기준 최적화
            board[y][x] = "."
            if winner == color:
                return move
        return None
    
    def _find_blocking_move(self, board: List[List[str]], candidates: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        """즉시 방어 수 찾기 (상대가 다음 수에 이기는 수를 막는 수)"""
        # 상대가 다음 수에 이기는 수 찾기
        opponent_threats = []
        for move in candidates:
            y, x = move
            board[y][x] = self.opponent
            winner = self._check_winner(board, (y, x))  # 마지막 수 기준 최적화
            board[y][x] = "."
            if winner == self.opponent:
                opponent_threats.append(move)
        
        # 상대의 위협이 있으면 막기
        if opponent_threats:
            # 여러 위협이 있으면 모두 막을 수 있는지 확인
            # 일단 첫 번째 위협을 막는 수 반환
            return opponent_threats[0]
        
        # 상대가 열린 4를 만들 수 있는 수 찾기 (다음 수에 승리 가능)
        for move in candidates:
            y, x = move
            board[y][x] = self.opponent
            # 열린 4가 있는지 확인
            if self._has_open_four(board, self.opponent):
                board[y][x] = "."
                return move
            board[y][x] = "."
        
        return None
    
    def _has_open_four(self, board: List[List[str]], color: str) -> bool:
        """열린 4가 있는지 확인 (양쪽이 모두 열린 4)"""
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        
        for y in range(self.board_size):
            for x in range(self.board_size):
                if board[y][x] != color:
                    continue
                
                for dx, dy in directions:
                    # 이 방향으로 연속된 돌 개수 확인
                    count = 1
                    # 앞쪽으로 연속 확인
                    nx, ny = x + dx, y + dy
                    while (0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                           board[ny][nx] == color):
                        count += 1
                        nx += dx
                        ny += dy
                    
                    # 뒤쪽으로 연속 확인
                    back_x, back_y = x - dx, y - dy
                    while (0 <= back_x < self.board_size and 
                           0 <= back_y < self.board_size and 
                           board[back_y][back_x] == color):
                        count += 1
                        back_x -= dx
                        back_y -= dy
                    
                    # 4개 연속이고 양쪽이 모두 열려있는지 확인
                    if count == 4:
                        # 앞쪽 끝 확인
                        forward_open = (0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                                       board[ny][nx] == ".")
                        # 뒤쪽 끝 확인
                        final_back_x, final_back_y = back_x + dx, back_y + dy
                        backward_open = (0 <= final_back_x < self.board_size and 
                                        0 <= final_back_y < self.board_size and 
                                        board[final_back_y][final_back_x] == ".")
                        
                        if forward_open and backward_open:
                            return True
        
        return False

    def _get_candidates(self, board: List[List[str]]) -> List[Tuple[int, int]]:
        """비어있는 칸 중 기존 돌의 인접한 구역과 전술적으로 중요한 위치 탐색"""
        candidates = set()
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]  # 가로, 세로, 대각선, 역대각선
        
        # 기본 후보: 기존 돌 주변 반경 2까지 (8방향 + 대각선 중간)
        for y in range(self.board_size):
            for x in range(self.board_size):
                if board[y][x] != ".":
                    # 거리 1: 8방향
                    for dy in range(-1, 2):
                        for dx in range(-1, 2):
                            if dx == 0 and dy == 0:
                                continue
                            ny, nx = y + dy, x + dx
                            if 0 <= ny < self.board_size and 0 <= nx < self.board_size and board[ny][nx] == ".":
                                candidates.add((ny, nx))
                    # 거리 2: 8방향 모두 확인 (점프 위협)
                    # 체스보드 거리(맨하탄 거리) 2인 모든 위치 확인
                    for dy in range(-2, 3):
                        for dx in range(-2, 3):
                            if dx == 0 and dy == 0:
                                continue
                            # 거리 1은 이미 처리했으므로 거리 2만 확인 (맨하탄 거리 2)
                            manhattan_dist = abs(dx) + abs(dy)
                            if manhattan_dist == 2:
                                ny, nx = y + dy, x + dx
                                if 0 <= ny < self.board_size and 0 <= nx < self.board_size and board[ny][nx] == ".":
                                    candidates.add((ny, nx))
        
        # 전술 후보: 4를 만들 수 있는 위치 (3이 있고 양쪽이 열린 경우)
        tactical_candidates = self._get_tactical_candidates(board, directions)
        candidates.update(tactical_candidates)
        
        return list(candidates)
    
    def _get_tactical_candidates(self, board: List[List[str]], directions: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """전술적으로 중요한 위치 찾기 (3 연속 + 양끝 열림만 - 강한 조건만 유지)"""
        tactical = set()
        
        # 내 돌과 상대 돌 모두 확인
        for color in [self.color, self.opponent]:
            for y in range(self.board_size):
                for x in range(self.board_size):
                    if board[y][x] != color:
                        continue
                    
                    for dx, dy in directions:
                        # 현재 위치에서 이 방향으로 연속된 돌 개수 확인
                        count = 1
                        # 앞쪽으로 연속 확인
                        nx, ny = x + dx, y + dy
                        while (0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                               board[ny][nx] == color):
                            count += 1
                            nx += dx
                            ny += dy
                        
                        # 뒤쪽으로 연속 확인
                        back_x, back_y = x - dx, y - dy
                        while (0 <= back_x < self.board_size and 
                               0 <= back_y < self.board_size and 
                               board[back_y][back_x] == color):
                            count += 1
                            back_x -= dx
                            back_y -= dy
                        
                        # 3개 연속이고 양쪽이 모두 열려있으면 4를 만들 수 있는 위치 추가 (강한 조건만)
                        if count == 3:
                            # 앞쪽 끝 확인 (보드 밖이면 닫힌 끝)
                            if (nx < 0 or nx >= self.board_size or 
                                ny < 0 or ny >= self.board_size):
                                forward_open = False
                            else:
                                forward_open = (board[ny][nx] == ".")
                            
                            # 뒤쪽 끝 확인 (보드 밖이면 닫힌 끝)
                            if (back_x < 0 or back_x >= self.board_size or 
                                back_y < 0 or back_y >= self.board_size):
                                backward_open = False
                            else:
                                backward_open = (board[back_y][back_x] == ".")
                            
                            # 양쪽이 모두 열려있을 때만 추가 (강한 조건)
                            if forward_open and backward_open:
                                # 양쪽 끝 모두 후보에 추가
                                tactical.add((ny, nx))
                                tactical.add((back_y, back_x))
        
        return list(tactical)
    
    def _get_max_candidates_for_depth(self, depth: int) -> int:
        """깊이에 따라 최대 후보 수 반환 (깊을수록 더 적게, 방어 수 고려)"""
        if depth >= 3:
            return 12  # 매우 깊은 레벨: 12개 (8→12로 완화)
        elif depth == 2:
            return 15  # 깊은 레벨: 15개 (12→15로 완화)
        elif depth == 1:
            return 20  # 얕은 레벨: 20개
        else:
            return 20  # 기본값
    
    def _sort_candidates(self, board: List[List[str]], candidates: List[Tuple[int, int]], is_maximizing: bool, max_needed: Optional[int] = None) -> List[Tuple[int, int]]:
        """후보를 가벼운 패턴 점수 순으로 정렬 (최적화: 상위 K개만 선택 가능)"""
        def get_move_score(move):
            y, x = move
            color_to_play = self.color if is_maximizing else self.opponent
            
            # 가벼운 로컬 패턴 점수만 계산 (_check_winner 제거 - 이미 get_move와 minimax에서 처리)
            board[y][x] = color_to_play
            score = self._evaluate_move_pattern_light(board, y, x, color_to_play)
            board[y][x] = "."
            return score
        
        # 상위 K개만 필요한 경우 heapq.nlargest 사용 (O(M log K))
        if max_needed is not None and max_needed < len(candidates):
            return [move for _, move in heapq.nlargest(max_needed, [(get_move_score(move), move) for move in candidates])]
        
        # 전체 정렬 (O(M log M))
        return sorted(candidates, key=get_move_score, reverse=True)
    
    def _evaluate_move_pattern_light(self, board: List[List[str]], y: int, x: int, color: str) -> int:
        """가벼운 로컬 패턴 점수 계산 (정렬용 - 빠른 버전)"""
        score = 0
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        opponent = self.opponent if color == self.color else self.color
        
        for dx, dy in directions:
            # 앞쪽으로 짧게만 확인 (로컬 평가)
            count = 1
            nx, ny = x + dx, y + dy
            check_count = 0
            while (check_count < 3 and 
                   0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                   board[ny][nx] == color):
                count += 1
                nx += dx
                ny += dy
                check_count += 1
            
            # 뒤쪽으로 짧게만 확인
            back_x, back_y = x - dx, y - dy
            check_count = 0
            while (check_count < 3 and 
                   0 <= back_x < self.board_size and 0 <= back_y < self.board_size and 
                   board[back_y][back_x] == color):
                count += 1
                back_x -= dx
                back_y -= dy
                check_count += 1
            
            # 간단한 패턴 점수
            if count >= 4:
                score += 10000
            elif count == 3:
                score += 1000
            elif count == 2:
                score += 100
            
            # 상대 위협도 간단히 확인
            opp_count = 0
            nx, ny = x + dx, y + dy
            check_count = 0
            while (check_count < 3 and 
                   0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                   board[ny][nx] == opponent):
                opp_count += 1
                nx += dx
                ny += dy
                check_count += 1
            
            back_x, back_y = x - dx, y - dy
            check_count = 0
            while (check_count < 3 and 
                   0 <= back_x < self.board_size and 0 <= back_y < self.board_size and 
                   board[back_y][back_x] == opponent):
                opp_count += 1
                back_x -= dx
                back_y -= dy
                check_count += 1
            
            if opp_count >= 3:
                score -= 5000  # 상대 위협 차단 중요
            elif opp_count == 2:
                score -= 500
        
        return score
    
    def _evaluate_move_pattern(self, board: List[List[str]], y: int, x: int, color: str) -> int:
        """특정 위치에 돌을 두었을 때 생성되는 패턴 점수 계산"""
        score = 0
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        opponent = self.opponent if color == self.color else self.color
        
        for dx, dy in directions:
            # 이 방향으로 연속된 돌 개수 확인
            count = 1
            
            # 앞쪽으로 연속 확인
            nx, ny = x + dx, y + dy
            while (0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                   board[ny][nx] == color):
                count += 1
                nx += dx
                ny += dy
            
            # 뒤쪽으로 연속 확인
            back_x, back_y = x - dx, y - dy
            while (0 <= back_x < self.board_size and 
                   0 <= back_y < self.board_size and 
                   board[back_y][back_x] == color):
                count += 1
                back_x -= dx
                back_y -= dy
            
            # 양쪽 끝의 상태 확인
            # 앞쪽 끝
            if (nx < 0 or nx >= self.board_size or 
                ny < 0 or ny >= self.board_size):
                forward_open = False
            else:
                forward_open = (board[ny][nx] == ".")
            
            # 뒤쪽 끝
            if (back_x < 0 or back_x >= self.board_size or 
                back_y < 0 or back_y >= self.board_size):
                backward_open = False
            else:
                backward_open = (board[back_y][back_x] == ".")
            
            # 패턴 점수 추가 (내 돌 기준)
            pattern_score = self._get_pattern_score(count, forward_open, backward_open)
            score += pattern_score
            
            # 상대의 패턴도 확인 (막아야 할 위협)
            # 앞쪽으로 상대 돌 확인
            opp_count = 0
            opp_nx, opp_ny = x + dx, y + dy
            while (0 <= opp_nx < self.board_size and 0 <= opp_ny < self.board_size and 
                   board[opp_ny][opp_nx] == opponent):
                opp_count += 1
                opp_nx += dx
                opp_ny += dy
            
            # 뒤쪽으로 상대 돌 확인
            opp_back_x, opp_back_y = x - dx, y - dy
            while (0 <= opp_back_x < self.board_size and 
                   0 <= opp_back_y < self.board_size and 
                   board[opp_back_y][opp_back_x] == opponent):
                opp_count += 1
                opp_back_x -= dx
                opp_back_y -= dy
            
            # 상대 패턴의 양쪽 끝 확인
            if (opp_nx < 0 or opp_nx >= self.board_size or 
                opp_ny < 0 or opp_ny >= self.board_size):
                opp_forward_open = False
            else:
                opp_forward_open = (board[opp_ny][opp_nx] == ".")
            
            if (opp_back_x < 0 or opp_back_x >= self.board_size or 
                opp_back_y < 0 or opp_back_y >= self.board_size):
                opp_backward_open = False
            else:
                opp_backward_open = (board[opp_back_y][opp_back_x] == ".")
            
            # 상대의 위협 패턴 점수 (차단 점수)
            if opp_count > 0:
                opp_pattern_score = self._get_pattern_score(opp_count, opp_forward_open, opp_backward_open)
                # 상대의 위협을 막는 것은 중요하므로 점수 추가
                score += opp_pattern_score // 2
        
        return score
    
    def _check_winner(self, board: List[List[str]], last_move: Optional[Tuple[int, int]] = None) -> Optional[str]:
        """보드에서 승리한 플레이어를 확인 (마지막 수 기준 최적화)"""
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        
        # 마지막 수가 주어지면 해당 위치 기준으로만 확인 (최적화)
        if last_move is not None:
            y, x = last_move
            if board[y][x] == ".":
                return None
            
            color = board[y][x]
            for dx, dy in directions:
                count = 1
                # 앞쪽으로 연속 확인
                nx, ny = x + dx, y + dy
                while (0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                       board[ny][nx] == color):
                    count += 1
                    nx += dx
                    ny += dy
                
                # 뒤쪽으로 연속 확인
                back_x, back_y = x - dx, y - dy
                while (0 <= back_x < self.board_size and 0 <= back_y < self.board_size and 
                       board[back_y][back_x] == color):
                    count += 1
                    back_x -= dx
                    back_y -= dy
                
                if count >= 5:
                    return color
            return None
        
        # 전체 스캔 (마지막 수가 없을 때만)
        for y in range(self.board_size):
            for x in range(self.board_size):
                if board[y][x] == ".":
                    continue
                
                color = board[y][x]
                for dx, dy in directions:
                    count = 1
                    nx, ny = x + dx, y + dy
                    while (0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                           board[ny][nx] == color):
                        count += 1
                        nx += dx
                        ny += dy
                    
                    if count >= 5:
                        return color
        
        return None

    def _evaluate_local(self, board: List[List[str]]) -> float:
        """로컬 평가 함수 (전판 스캔 대신 빠른 평가)"""
        score = 0
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]
        
        # 기존 돌 주변의 패턴만 빠르게 평가
        for y in range(self.board_size):
            for x in range(self.board_size):
                if board[y][x] == ".":
                    continue
                
                color = board[y][x]
                is_my_color = (color == self.color)
                
                # 각 방향으로 짧은 거리만 확인 (로컬 평가)
                for dx, dy in directions:
                    # 앞쪽으로 최대 4칸만 확인
                    count = 1
                    nx, ny = x + dx, y + dy
                    check_count = 0
                    while (check_count < 4 and 
                           0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                           board[ny][nx] == color):
                        count += 1
                        nx += dx
                        ny += dy
                        check_count += 1
                    
                    # 뒤쪽으로 최대 4칸만 확인
                    back_x, back_y = x - dx, y - dy
                    check_count = 0
                    while (check_count < 4 and 
                           0 <= back_x < self.board_size and 0 <= back_y < self.board_size and 
                           board[back_y][back_x] == color):
                        count += 1
                        back_x -= dx
                        back_y -= dy
                        check_count += 1
                    
                    # 간단한 패턴 점수 (로컬 평가용)
                    if count >= 5:
                        return 1000000 if is_my_color else -1000000
                    elif count == 4:
                        # 양쪽 끝 확인 (간단 버전)
                        forward_open = (0 <= nx < self.board_size and 0 <= ny < self.board_size and 
                                       board[ny][nx] == ".") if check_count < 4 else False
                        final_back_x, final_back_y = back_x + dx, back_y + dy
                        backward_open = (0 <= final_back_x < self.board_size and 
                                        0 <= final_back_y < self.board_size and 
                                        board[final_back_y][final_back_x] == ".") if check_count < 4 else False
                        
                        if forward_open and backward_open:
                            score += 10000 if is_my_color else -10000
                        elif forward_open or backward_open:
                            score += 1000 if is_my_color else -1000
                    elif count == 3:
                        score += 100 if is_my_color else -100
                    elif count == 2:
                        score += 10 if is_my_color else -10
        
        return score
    
    def _evaluate_board(self, board: List[List[str]]) -> float:
        """현재 보드 상태의 점수를 계산 (전판 스캔 - 느리지만 정확)"""
        # 단순 구현: 내 돌의 연속성 점수 합산 - 상대 돌의 연속성 점수 합산
        my_score = self._count_patterns(board, self.color)
        op_score = self._count_patterns(board, self.opponent)
        return my_score - op_score

    def _count_patterns(self, board: List[List[str]], color: str) -> int:
        """길이 5 윈도우를 슬라이딩하여 갭 패턴 포함 패턴 점수 계산"""
        score = 0
        directions = [(1, 0), (0, 1), (1, 1), (1, -1)]  # 가로, 세로, 대각선, 역대각선
        opponent = self.opponent if color == self.color else self.color
        window_size = 5
        evaluated_windows = set()  # 중복 평가 방지
        
        for y in range(self.board_size):
            for x in range(self.board_size):
                for dx, dy in directions:
                    # 윈도우의 시작 위치 계산 (중복 방지를 위해 왼쪽/위쪽에서만 시작)
                    start_x = x - 4 * dx
                    start_y = y - 4 * dy
                    # 시작 위치가 유효한지 확인
                    if start_x < 0 or start_y < 0:
                        continue
                    
                    # 윈도우가 보드 밖으로 나가는지 확인
                    end_x = start_x + (window_size - 1) * dx
                    end_y = start_y + (window_size - 1) * dy
                    if end_x < 0 or end_x >= self.board_size or end_y < 0 or end_y >= self.board_size:
                        continue
                    
                    # 시작 위치도 다시 한번 확인 (안전을 위해)
                    if start_x >= self.board_size or start_y >= self.board_size:
                        continue
                    
                    # 윈도우 고유 식별자 (중복 방지)
                    window_id = (start_x, start_y, dx, dy)
                    if window_id in evaluated_windows:
                        continue
                    evaluated_windows.add(window_id)
                    
                    # 윈도우 내부 분석
                    window_score = self._evaluate_window(board, start_x, start_y, dx, dy, window_size, color, opponent)
                    score += window_score
        
        return score
    
    def _evaluate_window(self, board: List[List[str]], start_x: int, start_y: int, 
                        dx: int, dy: int, window_size: int, color: str, opponent: str) -> int:
        """길이 5 윈도우를 분석하여 패턴 점수 계산 (최대 연속 길이, 갭 위치, 혼합 윈도우 고려)"""
        window_cells = []
        
        # 윈도우 내부 스캔
        for i in range(window_size):
            x = start_x + i * dx
            y = start_y + i * dy
            # 안전 체크: 인덱스 범위 확인
            if x < 0 or x >= self.board_size or y < 0 or y >= self.board_size:
                return 0
            cell = board[y][x]
            window_cells.append(cell)
        
        my_count = window_cells.count(color)
        opp_count = window_cells.count(opponent)
        empty_count = window_cells.count(".")
        
        # 양쪽 끝 개방 여부 확인
        before_x = start_x - dx
        before_y = start_y - dy
        if (before_x < 0 or before_x >= self.board_size or 
            before_y < 0 or before_y >= self.board_size):
            forward_open = False
        else:
            forward_open = (board[before_y][before_x] == ".")
        
        after_x = start_x + window_size * dx
        after_y = start_y + window_size * dy
        if (after_x < 0 or after_x >= self.board_size or 
            after_y < 0 or after_y >= self.board_size):
            backward_open = False
        else:
            backward_open = (board[after_y][after_x] == ".")
        
        is_open = forward_open and backward_open
        is_half_open = forward_open or backward_open
        
        score = 0
        
        # 내 패턴 평가
        if my_count > 0 and opp_count == 0:
            # 최대 연속 길이 계산
            max_continuous = self._get_max_continuous(window_cells, color)
            
            # 갭 위치 분석: 한 칸 메우면 4가 되는지
            can_make_four = self._can_make_four(window_cells, color)
            
            if max_continuous >= 5:
                score += 1000000  # 승리
            elif max_continuous == 4:
                if is_open:
                    score += 100000  # 열린 4
                elif is_half_open:
                    score += 10000   # 반열린 4
                else:
                    score += 1000    # 닫힌 4
            elif max_continuous == 3:
                if can_make_four and is_open:
                    score += 50000   # 갭이 있는 열린 3 (다음 수에 4 가능)
                elif is_open:
                    score += 1000    # 열린 3
                elif is_half_open:
                    score += 100     # 반열린 3
                else:
                    score += 10      # 닫힌 3
            elif max_continuous == 2:
                if is_open:
                    score += 10      # 열린 2
                elif is_half_open:
                    score += 1      # 반열린 2
        
        # 상대 위협 평가 (혼합 윈도우도 고려)
        if opp_count > 0:
            opp_max_continuous = self._get_max_continuous(window_cells, opponent)
            opp_can_make_four = self._can_make_four(window_cells, opponent)
            
            if opp_max_continuous >= 5:
                score -= 1000000  # 상대 승리 위협
            elif opp_max_continuous == 4:
                if is_open:
                    score -= 100000  # 상대 열린 4 위협
                elif is_half_open:
                    score -= 10000
                else:
                    score -= 1000
            elif opp_max_continuous == 3:
                if opp_can_make_four and is_open:
                    score -= 50000   # 상대 갭이 있는 열린 3 위협
                elif is_open:
                    score -= 1000
                elif is_half_open:
                    score -= 100
            elif opp_max_continuous == 2:
                if is_open:
                    score -= 10
        
        return score
    
    def _get_max_continuous(self, cells: List[str], color: str) -> int:
        """윈도우 내에서 최대 연속 길이 계산"""
        max_continuous = 0
        current = 0
        
        for cell in cells:
            if cell == color:
                current += 1
                max_continuous = max(max_continuous, current)
            else:
                current = 0
        
        return max_continuous
    
    def _can_make_four(self, cells: List[str], color: str) -> bool:
        """한 칸 메우면 4가 되는지 확인 (갭 위치 고려)"""
        # 빈칸이 1개이고, 나머지 4개가 모두 color인 경우
        if cells.count(".") == 1 and cells.count(color) == 4:
            return True
        
        # 갭이 있는 3 연속 패턴 확인 (예: X X . X 또는 X . X X)
        for i in range(len(cells) - 3):
            window = cells[i:i+4]
            if window.count(color) == 3 and window.count(".") == 1:
                return True
        
        return False
    
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