"""エントリーポイント。

QApplication起動、PetState読み込み、PetController/PetWindow/PetTray初期化、
QTimerによる定期更新、終了時の保存を行う。
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from desktop_pet.controller import PetController
from desktop_pet.pet_state import PetState
from desktop_pet.pet_window import PetWindow
from desktop_pet.tray import PetTray

STATUS_CHECK_INTERVAL_MS = 60 * 1000  # 1分ごとに時間経過を反映


def main() -> None:
    app = QApplication(sys.argv)
    # トレイアイコンのみでも動作継続できるようにする（ウィンドウを閉じても終了しない）
    app.setQuitOnLastWindowClosed(False)

    state = PetState.load_or_create()

    # window は on_change コールバック内で参照するため、後から生成して紐付ける
    window: PetWindow | None = None

    def on_change() -> None:
        if window is not None:
            window.refresh_appearance()

    controller = PetController(app, state, on_change=on_change)

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
        window.refresh_appearance()

    timer = QTimer()
    timer.timeout.connect(refresh)
    timer.start(STATUS_CHECK_INTERVAL_MS)

    app.aboutToQuit.connect(lambda: state.save())

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
