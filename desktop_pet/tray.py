"""システムトレイアイコンとメニュー。

右クリックメニューから「餌やり」「なでる」「時間操作」「終了」を行う。
実処理は PetController に委譲し、ウィンドウのボタンと重複させない。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from desktop_pet.controller import TIME_CONTROLS, PetController

ASSETS_DIR = Path(__file__).parent.parent / "assets" / "pet"


class PetTray(QSystemTrayIcon):
    def __init__(
        self,
        controller: PetController,
        get_window_pos: Callable[[], tuple[int, int]],
    ) -> None:
        icon_path = ASSETS_DIR / "normal.png"
        super().__init__(QIcon(str(icon_path)))
        self.setToolTip("デスクトップペット")

        menu = QMenu()
        menu.addAction("餌やり", controller.feed)
        menu.addAction("なでる", controller.pet)

        time_menu = menu.addMenu("時間を進める/戻す")
        for label, minutes in TIME_CONTROLS:
            # デフォルト引数でクロージャに現在のminutesを束縛する
            time_menu.addAction(
                label, lambda minutes=minutes: controller.change_time(minutes)
            )

        menu.addSeparator()
        menu.addAction("終了", lambda: controller.quit(get_window_pos()))

        self.setContextMenu(menu)
        self.setVisible(True)
