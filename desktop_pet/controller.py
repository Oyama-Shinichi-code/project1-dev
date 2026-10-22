"""ペットの各アクションを一元管理するコントローラー。

ウィンドウ上のボタンとシステムトレイのメニューの両方から、
同じメソッドを呼ぶことで処理の重複を避ける。
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtWidgets import QApplication

from desktop_pet.ai_chat import EvaluationResult, EvaluationWorker, IdleNarrationWorker
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
        # 進行中のIdleNarrationWorkerへの参照（GC防止・多重送信防止）。
        self._active_idle_narration_worker: IdleNarrationWorker | None = None

    def feed(self) -> str:
        """餌やりの実処理。戻り値は "normal" | "overfed" | "woke_up"。

        睡眠中にこの操作が行われた場合は、餌やり自体の効果は発生させず
        強制起床のみ行う（"woke_up"）。モーション再生の分岐（通常はハート演出、
        あげすぎ/強制起床は困るモーション）に呼び出し側（PetWindow）が使う。
        """
        if self.state.wake_up_by_action():
            self._on_change()
            return "woke_up"
        overfed = self.state.hunger >= 100
        if overfed:
            # あげすぎ時は満腹度を加算しない代わりに、機嫌・なつき度を下げるペナルティを与える
            # （「無理に食べさせられて嫌がる」ことの表現。hunger自体は変化させない）。
            # apply_time_decay()はここでは呼ばない。満腹度の減少は時間経過（定期タイマー側の
            # apply_time_decay呼び出し）のみに委ね、アクション起点では発生させないため。
            self.state.overfeed_penalty()
        else:
            self.state.feed()
        self._on_change()
        return "overfed" if overfed else "normal"

    def pet(self) -> str:
        """なでるの実処理。戻り値は "normal" | "overpetted" | "woke_up"。

        睡眠中にこの操作が行われた場合は、なでる自体の効果は発生させず
        強制起床のみ行う（"woke_up"）。
        """
        if self.state.wake_up_by_action():
            self._on_change()
            return "woke_up"
        overpetted = self.state.pet()
        self._on_change()
        return "overpetted" if overpetted else "normal"

    def change_time(self, minutes: float) -> None:
        if minutes >= 0:
            self.state.advance_time(minutes)
        else:
            self.state.rewind_time(-minutes)
        self._on_change()

    def debug_start_sleep(self) -> None:
        """デバッグ用: 条件を無視して即座に入眠させる。"""
        self.state.start_sleep_debug()
        self._on_change()

    def set_bedtime(self, hour: int | None, minute: int | None) -> None:
        """お休み時間を設定する（Noneで未設定に戻す）。"""
        self.state.set_bedtime(hour, minute)
        self._on_change()

    def quit(self, window_pos: tuple[int, int]) -> None:
        # 終了直前のウィンドウ位置を保存してからアプリを終了する
        self.state.window_position = [window_pos[0], window_pos[1]]
        self._app.quit()

    def set_pet_name(self, name: str) -> None:
        """ペット名を設定する（入力欄のtextChangedから都度呼ばれる想定）。

        空文字列も許容し、その場合は「未設定」に戻す（会話機能が使えなくなる）。
        文字数・使用可能文字のバリデーションはQLineEdit側（setMaxLength・
        カスタムバリデータ）で入力段階に行うため、ここでは単純に反映するだけでよい。
        """
        self.state.name = name
        self._on_change()

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

        if not self.state.name:
            on_error("no_name", "まずは名前をつけよう")
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

    def request_idle_narration(self) -> bool:
        """何も操作していない間の定期実況（アイドル実況）をGemini APIに要求する。

        戻り値はワーカーを起動できたかどうか。APIキー未設定、または既に
        前回のリクエストが進行中の場合はFalse（呼び出し元は静かにスキップしてよい）。
        結果はstate.push_narration()経由でnarration_logに追記され、on_changeで
        UIへ通知される。失敗時はログに積まず何もしない（アイドル実況は失敗しても
        実害がないため、チャット機能のようにエラー文言をユーザーに出す必要はない）。
        """
        if self._active_idle_narration_worker is not None:
            return False
        api_key = self._get_api_key()
        if not api_key:
            return False

        status_summary = (
            f"満腹度:{self.state.hunger:.0f} 機嫌:{self.state.mood:.0f} "
            f"体力:{self.state.stamina:.0f} なでAP:{self.state.pet_ap:.0f} "
            f"レベル:{self.state.level}"
        )
        worker = IdleNarrationWorker(api_key, status_summary)
        worker.narration_succeeded.connect(self._on_idle_narration_succeeded)
        worker.finished.connect(self._clear_active_idle_narration_worker)
        self._active_idle_narration_worker = worker
        worker.start()
        return True

    def _on_idle_narration_succeeded(self, narration: str) -> None:
        self.state.push_narration(narration)
        self._on_change()

    def _clear_active_idle_narration_worker(self) -> None:
        self._active_idle_narration_worker = None
