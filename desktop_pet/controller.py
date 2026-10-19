"""ペットの各アクションを一元管理するコントローラー。

ウィンドウ上のボタンとシステムトレイのメニューの両方から、
同じメソッドを呼ぶことで処理の重複を避ける。
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtWidgets import QApplication

from desktop_pet.ai_chat import EvaluationResult, EvaluationWorker
from desktop_pet.mood_rules import compute_mood_delta
from desktop_pet.pet_state import ChatHistoryEntry, PetState

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
        get_api_key: Callable[[], str | None],
    ) -> None:
        self._app = app
        self.state = state
        # ステータス変化後に呼ぶコールバック（見た目の再描画など）
        self._on_change = on_change
        # 呼び出すたびに最新の.envを読み直す想定の関数を注入する
        # （実行中にAPIキーを設定し直した場合も次回送信で反映されるように）
        self._get_api_key = get_api_key
        # 進行中のEvaluationWorkerへの参照（GC防止のため必須）。多重送信の防止にも使う。
        self._active_chat_worker: EvaluationWorker | None = None

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

    def submit_chat_message(
        self,
        text: str,
        on_result: Callable[[ChatHistoryEntry], None],
        on_error: Callable[[str, str], None],
    ) -> bool:
        """ユーザーの発言をGemini APIへ送信し、評価結果をmoodに反映する。

        戻り値はワーカーを起動できたかどうか。既に送信中（多重送信）、または
        APIキー未設定の場合はFalseを返し、on_errorでエラー内容を通知する。
        結果・エラーは非同期（QThread）で届くため、呼び出し元はon_result/on_errorの
        コールバックで結果を受け取る。
        """
        if self._active_chat_worker is not None:
            on_error("busy", "前回の送信の返信待ちです。")
            return False

        api_key = self._get_api_key()
        if not api_key:
            on_error("no_api_key", "APIキーが設定されていません。")
            return False

        worker = EvaluationWorker(api_key, text, self.state.name)
        worker.evaluation_succeeded.connect(
            lambda result: self._on_chat_evaluation_succeeded(text, result, on_result)
        )
        worker.evaluation_failed.connect(on_error)
        worker.finished.connect(self._clear_active_chat_worker)
        self._active_chat_worker = worker
        worker.start()
        return True

    def _on_chat_evaluation_succeeded(
        self,
        user_text: str,
        result: EvaluationResult,
        on_result: Callable[[ChatHistoryEntry], None],
    ) -> None:
        delta = compute_mood_delta(result, self.state)
        self.state.apply_chat_mood_delta(delta)
        entry = ChatHistoryEntry(
            user_text=user_text,
            narration=result.narration,
            level=result.level,
            mood_delta=delta,
            timestamp=datetime.now().isoformat(),
            is_inappropriate=result.is_inappropriate,
        )
        self.state.chat_history.append(entry)
        self._on_change()
        on_result(entry)

    def _clear_active_chat_worker(self) -> None:
        self._active_chat_worker = None
