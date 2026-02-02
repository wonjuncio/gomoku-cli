from dataclasses import dataclass


# Heuristic weights for evaluation (no capture in this project)
WEIGHT_WIN = 50_000
WEIGHT_FOUR = 5_000
WEIGHT_THREE = 500
WEIGHT_TWO = 50
# Move count limits by depth (shallow = fewer moves for speed)
MAX_MOVES_DEPTH_LOW = 12
MAX_MOVES_DEPTH_HIGH = 18
# Adjacent search distance for move generation
SEARCH_DISTANCE = 2


@dataclass(frozen=True)
class AILevelConfig:
    max_depth: int
    time_limit: float
    randomize_top_k: int = 1  # 1이면 랜덤 없음

AI_LEVELS = {
    1: AILevelConfig(max_depth=2, time_limit=0.12, randomize_top_k=3),
    2: AILevelConfig(max_depth=3, time_limit=0.18, randomize_top_k=2),
    3: AILevelConfig(max_depth=4, time_limit=0.30, randomize_top_k=1),
    4: AILevelConfig(max_depth=5, time_limit=0.45, randomize_top_k=1),
    5: AILevelConfig(max_depth=6, time_limit=0.45, randomize_top_k=1),
}
