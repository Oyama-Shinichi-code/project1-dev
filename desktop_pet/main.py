"""エントリーポイント。

QApplication起動、PetState読み込み、PetController/PetWindow/PetTray初期化、
QTimerによる定期更新、終了時の保存を行う。
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from desktop_pet.api_key_store import load_api_key, prompt_for_api_key, save_api_key
from desktop_pet.controller import PetController
from desktop_pet.pet_state import PetState
from desktop_pet.pet_window import PetWindow
from desktop_pet.tray import PetTray

STATUS_CHECK_INTERVAL_MS = 60 * 1000  # 1分ごとに時間経過を反映
IDLE_NARRATION_INTERVAL_MS = 5 * 60 * 1000  # 5分ごとにアイドル実況（実時間基準）


def main() -> None:
    app = QApplication(sys.argv)
    # トレイアイコンのみでも動作継続できるようにする（ウィンドウを閉じても終了しない）
    app.setQuitOnLastWindowClosed(False)

    # 会話機能用のGemini APIキーが未設定なら、起動時に一度だけ入力を求める。
    # キャンセル/未入力でも起動は継続する（会話機能のみ使用不可、他の機能は通常通り）。
    if not load_api_key():
        entered_key = prompt_for_api_key()
        if entered_key:
            save_api_key(entered_key)

    state = PetState.load_or_create()

    # window は on_change コールバック内で参照するため、後から生成して紐付ける
    window: PetWindow | None = None

    def on_change() -> None:
        if window is not None:
            window.refresh_appearance()

    controller = PetController(app, state, on_change=on_change, get_api_key=load_api_key)

    window = PetWindow(controller)
    window.show()

    # 餌やり・なでる・時間操作・終了はウィンドウのボタンとトレイメニューの両方から
    # controller の同じメソッドを呼ぶことで処理を共通化している
    tray = PetTray(
        controller,
        get_window_pos=lambda: (window.pos().x(), window.pos().y()),
    )

    def refresh() -> None:
        state.apply_time_decay()
        state.maybe_trigger_attention_event()
        window.refresh_appearance()

    timer = QTimer()
    timer.timeout.connect(refresh)
    timer.start(STATUS_CHECK_INTERVAL_MS)

    idle_narration_timer = QTimer()
    idle_narration_timer.timeout.connect(controller.request_idle_narration)
    idle_narration_timer.start(IDLE_NARRATION_INTERVAL_MS)

    app.aboutToQuit.connect(lambda: state.save())

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
