"""Minimax with Alpha-Beta pruning and iterative deepening."""

import random
import time
from typing import List, Optional, Tuple

from src.core.game import Game
from src.core.board import Position
from src.ai.config import (
    AILevelConfig,
    WEIGHT_WIN,
    MAX_MOVES_DEPTH_LOW,
    MAX_MOVES_DEPTH_HIGH,
)
from src.ai.heuristics import Heuristic
from src.ai.movegen import MoveGenerator


class MinimaxAI:
    """Minimax AI with Alpha-Beta pruning and iterative deepening."""

    def __init__(
        self,
        level_config: AILevelConfig,
        use_multiprocessing: bool = False,
    ) -> None:
        self.level_config = level_config
        self.use_multiprocessing = use_multiprocessing
        self.nodes_explored = 0
        self.depth_reached = 0

    def get_best_move(self, game: Game) -> Optional[Position]:
        """Find best move within time_limit using iterative deepening."""
        return self._get_best_move_iterative(game, self.level_config.time_limit)

    def _get_best_move_iterative(self, game: Game, time_limit: float) -> Optional[Position]:
        """Search deeper until time runs out; return best move so far."""
        start = time.time()
        best_move: Optional[Position] = None
        best_score = float("-inf")
        depth_reached = 0
        total_nodes = 0
        max_depth = self.level_config.max_depth

        move_gen = MoveGenerator(game, level_config=self.level_config)
        max_moves = MAX_MOVES_DEPTH_HIGH if max_depth >= 5 else MAX_MOVES_DEPTH_LOW
        possible_moves = move_gen.get_ordered_moves(max_moves=max_moves)

        if not possible_moves:
            return None
        if len(possible_moves) == 1:
            return possible_moves[0]

        maximizing_player = game.current_player

        move_scores: List[Tuple[Position, float]] = []  # last iteration's (move, score) for randomize_top_k

        for current_depth in range(1, max_depth + 1):
            elapsed = time.time() - start
            if elapsed > time_limit * 0.85:
                break
            if current_depth > 2:
                time_per_depth = elapsed / current_depth
                if elapsed + time_per_depth * 3 > time_limit:
                    break

            self.nodes_explored = 0
            move, score, move_scores = self._sequential_search_root(
                game, possible_moves, maximizing_player, current_depth
            )
            if move is not None:
                best_move = move
                best_score = score
                depth_reached = current_depth
            total_nodes += self.nodes_explored
            if score >= WEIGHT_WIN - 100:
                break

        self.nodes_explored = total_nodes
        self.depth_reached = depth_reached

        # randomize_top_k: among top-k moves by score, pick one at random (1 = no random)
        k = self.level_config.randomize_top_k
        if k > 1 and move_scores:
            move_scores.sort(key=lambda t: t[1], reverse=True)
            top = [m for m, s in move_scores[:k]]
            if top:
                return random.choice(top)
        return best_move

    def _sequential_search_root(
        self,
        game: Game,
        moves: list,
        maximizing_player,
        depth: int,
    ) -> Tuple[Optional[Position], float, List[Tuple[Position, float]]]:
        """Sequential alpha-beta at root. Returns (best_move, best_score, all (move, score))."""
        best_move = None
        best_score = float("-inf")
        alpha = float("-inf")
        beta = float("inf")
        move_scores: List[Tuple[Position, float]] = []
        for move in moves:
            score = self._evaluate_move(
                game, move, depth, maximizing_player, alpha, beta
            )
            move_scores.append((move, score))
            if score > best_score:
                best_score = score
                best_move = move
            alpha = max(alpha, score)
            if beta <= alpha:
                break
        return best_move, best_score, move_scores

    def _evaluate_move(
        self,
        game: Game,
        move: Position,
        depth: int,
        maximizing_player,
        alpha: float,
        beta: float,
    ) -> float:
        """Score one root move by making it and running alpha-beta for opponent."""
        game_copy = game.copy()
        result = game_copy.make_move(move)
        if not result.success:
            return float("-inf")
        if result.is_winning_move:
            return WEIGHT_WIN + depth
        game_copy.switch_player()
        score, _ = self._alpha_beta(
            game_copy, depth - 1, alpha, beta, False, maximizing_player
        )
        return score

    def _alpha_beta(
        self,
        game: Game,
        depth: int,
        alpha: float,
        beta: float,
        is_maximizing: bool,
        maximizing_player,
    ) -> Tuple[float, Optional[Position]]:
        """Alpha-beta recursion. Returns (score, best_move)."""
        self.nodes_explored += 1

        if depth == 0 or game.is_game_over():
            h = Heuristic(game)
            return h.evaluate(maximizing_player, depth), None

        move_gen = MoveGenerator(game, level_config=self.level_config)
        max_moves = MAX_MOVES_DEPTH_HIGH if depth >= 5 else MAX_MOVES_DEPTH_LOW
        possible_moves = move_gen.get_ordered_moves(max_moves=max_moves)

        if not possible_moves:
            h = Heuristic(game)
            return h.evaluate(maximizing_player, depth), None

        best_move = None

        if is_maximizing:
            max_eval = float("-inf")
            for move in possible_moves:
                game_copy = game.copy()
                result = game_copy.make_move(move)
                if not result.success:
                    continue
                if result.is_winning_move:
                    return WEIGHT_WIN + depth, move
                game_copy.switch_player()
                eval_score, _ = self._alpha_beta(
                    game_copy, depth - 1, alpha, beta, False, maximizing_player
                )
                if eval_score > max_eval:
                    max_eval = eval_score
                    best_move = move
                alpha = max(alpha, eval_score)
                if beta <= alpha:
                    break
            return max_eval, best_move

        min_eval = float("inf")
        for move in possible_moves:
            game_copy = game.copy()
            result = game_copy.make_move(move)
            if not result.success:
                continue
            if result.is_winning_move:
                return -(WEIGHT_WIN + depth), move
            game_copy.switch_player()
            eval_score, _ = self._alpha_beta(
                game_copy, depth - 1, alpha, beta, True, maximizing_player
            )
            if eval_score < min_eval:
                min_eval = eval_score
                best_move = move
            beta = min(beta, eval_score)
            if beta <= alpha:
                break
        return min_eval, best_move
