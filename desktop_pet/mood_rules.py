"""AIの会話評価（5段階）をmood変化量に変換するロジック。

現状は評価段階ごとの数値幅から乱数で決めるだけだが、将来は「同じ発言の繰り返しで
減点」「拒否反応の連呼で指数関数的減点」「称賛では簡単に上がらない」等の複雑な
ルールに差し替える予定。compute_mood_delta()のシグネチャ（評価とstateを受け取り
floatを返す）を変えなければ、呼び出し側（controller.py）は無改修で済む。
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from desktop_pet.ai_chat import EvaluationResult

if TYPE_CHECKING:
    from desktop_pet.pet_state import PetState

# 評価段階ごとのmood変化量の乱数幅。仮の対称値（後で調整する前提）。
MOOD_DELTA_RANGES: dict[str, tuple[float, float]] = {
    "very_good": (8.0, 12.0),
    "good": (3.0, 6.0),
    "neutral": (-1.0, 1.0),
    "bad": (-6.0, -3.0),
    "very_bad": (-12.0, -8.0),
}


def compute_mood_delta(evaluation: EvaluationResult, state: "PetState") -> float:
    """評価段階からmood変化量を決める（現状は乱数のみ）。

    不適切な入力（is_inappropriate=True）の場合はmoodを一切変化させない
    （注意ナレーションのみ表示し、ペナルティも加点も与えない）。
    stateは将来chat_historyを参照した高度な評価（繰り返し検出等）に差し替える際に
    使う想定で、現時点では未使用。
    """
    if evaluation.is_inappropriate:
        return 0.0
    low, high = MOOD_DELTA_RANGES[evaluation.level]
    return random.uniform(low, high)
