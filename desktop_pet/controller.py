"""ペットの各アクションを一元管理するコントローラー。

ウィンドウ上のボタンとシステムトレイのメニューの両方から、
同じメソッドを呼ぶことで処理の重複を避ける。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QApplication

from desktop_pet.pet_state import PetState

# (表示ラベル, 分数) : 時間操作の選択肢。ウィンドウのボタンとトレイの両方で共有する。
TIME_CONTROLS: list[tuple[str, float]] = [
    ("+10分", 10),
    ("+1時間", 60),
    ("+1日", 60 * 24),
    ("-1時間", -60),
    ("-1日", -60 * 24),
]


class PetController:
    """餌やり・なでる・時間操作・終了の実処理をまとめるクラス。"""

    def __init__(
        self,
        app: QApplication,
        state: PetState,
        on_change: Callable[[], None],
    ) -> None:
        self._app = app
        self.state = state
        # ステータス変化後に呼ぶコールバック（見た目の再描画など）
        self._on_change = on_change

    def feed(self) -> bool:
        """餌やりの実処理。戻り値は「あげすぎ」だったかどうか（True=あげすぎ）。

        モーション再生の分岐（通常はハート演出、あげすぎはシェイク演出）に
        呼び出し側（PetWindow）が使う。ステータス反映自体はここで確定させる。
        """
        overfed = self.state.hunger >= 100
        if overfed:
            # あげすぎ時は満腹度を加算しない代わりに、機嫌を少し下げるペナルティを与える
            # （「無理に食べさせられて嫌がる」ことの表現。hunger自体は変化させない）。
            # apply_time_decay()はここでは呼ばない。満腹度の減少は時間経過（定期タイマー側の
            # apply_time_decay呼び出し）のみに委ね、アクション起点では発生させないため。
            self.state.mood = max(0.0, self.state.mood - 5.0)
        else:
            self.state.feed()
        self._on_change()
        return overfed

    def pet(self) -> None:
        self.state.pet()
        self._on_change()

    def change_time(self, minutes: float) -> None:
        if minutes >= 0:
            self.state.advance_time(minutes)
        else:
            self.state.rewind_time(-minutes)
        self._on_change()

    def quit(self, window_pos: tuple[int, int]) -> None:
        # 終了直前のウィンドウ位置を保存してからアプリを終了する
        self.state.window_position = [window_pos[0], window_pos[1]]
        self._app.quit()
