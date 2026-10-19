"""常駐の透過ウィンドウ（ペット本体表示）。

- フレームレス・最前面・背景透過
- クリックでなでるアクション
- ドラッグで移動
- 画像下のボタン列（餌やり/なでる/時間操作/終了、折りたたみ可）
- ステータスゲージ（満腹度/機嫌/体力、折りたたみ可）
- 餌やりモーション（餌アイコン表示＋食べかすパーティクル＋完食ハート/あげすぎシェイク）
- なでるモーション（画像バウンド＋キラキラパーティクル）
"""
from __future__ import annotations

import ctypes
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QCursor, QIcon, QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.controller import TIME_CONTROLS, PetController
from desktop_pet.pet_state import ChatHistoryEntry
from desktop_pet.effects import ParticleEffectWidget, make_crumb_config, make_sparkle_config

ASSETS_DIR = Path(__file__).parent / "assets" / "pet"
NORMAL_ANIM_DIR = ASSETS_DIR / "normal"
NORMAL_ANIM_FRAMES = ["normal_flame1.png", "normal_flame2.png", "normal_flame3.png"]
NORMAL_ANIM_INTERVAL_MS = 400  # フレーム切り替え間隔(ms)
ANGRY_ANIM_DIR = ASSETS_DIR / "angry"
ANGRY_ANIM_FRAMES = ["angry_flame1.png", "angry_flame2.png"]
HUNGRY_ANIM_DIR = ASSETS_DIR / "hungry"
HUNGRY_ANIM_FRAMES = ["hungry_flame1.png", "hungry_flame2.png"]
# 表情ごとの往復アニメーションフレーム一覧（この辞書に無い表情は静止画のまま）
EXPRESSION_ANIM_FRAMES: dict[str, tuple[Path, list[str]]] = {
    "normal": (NORMAL_ANIM_DIR, NORMAL_ANIM_FRAMES),
    "angry": (ANGRY_ANIM_DIR, ANGRY_ANIM_FRAMES),
    "hungry": (HUNGRY_ANIM_DIR, HUNGRY_ANIM_FRAMES),
}
ANGRY_EFFECT_ICON = "💢"
# 怒りエフェクトのタイミング(ms): 左下表示→(A)後に右上も追加表示(左下は残る)
# →(B)後に左下だけ消える→(C)後に右上も消えて休止→(D)後に最初から繰り返す
ANGRY_EFFECT_TOP_RIGHT_DELAY_MS = 300  # 左下表示から右上が追加表示されるまで
ANGRY_EFFECT_BOTTOM_LEFT_HIDE_MS = 400  # 右上追加表示から左下が消えるまで
ANGRY_EFFECT_TOP_RIGHT_HIDE_MS = 400  # 左下消滅から右上が消えるまで
ANGRY_EFFECT_PAUSE_MS = 700  # 右上消滅から休止している時間（次サイクルまで）
PET_SIZE = 200  # 表示サイズ（元画像は512x512なので縮小表示）
BUTTON_SIZE = 36  # ボタン列の1つあたりのサイズ(px)

# Win32 SetWindowPos用の定数。
# QtのWindowStaysOnBottomHintだけでは「他ウィンドウクリック時に最背面が崩れる」
# ため、user32.dllを直接叩いてOSレベルでZ-orderを固定する（Windows専用）。
_HWND_TOPMOST = -1
_HWND_BOTTOM = 1
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010


def _set_window_z_order(hwnd: int, insert_after: int) -> None:
    """指定したHWNDをinsert_after(HWND_TOPMOST/HWND_BOTTOM)の位置に固定する。"""
    ctypes.windll.user32.SetWindowPos(
        hwnd, insert_after, 0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
    )

FEED_ICON_DURATION_MS = 1000  # 餌アイコンのフェードイン→表示→フェードアウトの合計時間
HEART_DURATION_MS = 2600  # 完食ハート演出の時間（確認しやすいよう通常の2倍に設定）
SHAKE_DURATION_MS = 600  # あげすぎシェイクの時間
PET_BOUNCE_DURATION_MS = 500  # なでるモーション（バウンド）の時間
HAPPY_ANIM_INTERVAL_MS = 180  # ハート演出中の加速アニメーション間隔(ms)

ANIM_SPEED_SLIDER_MIN_MS = 100  # 速度調整スライダーの最小間隔(ms)
ANIM_SPEED_SLIDER_MAX_MS = 1000  # 速度調整スライダーの最大間隔(ms)

MIN_SCALE = 0.5  # 最小スケール（PET_SIZE=200基準で表示100px相当）
MAX_SCALE = 2.0  # 最大スケール（PET_SIZE=200基準で表示400px相当）
RESIZE_GRIP_SIZE = 32  # 角のリサイズグリップのサイズ(px、ウィンドウ座標系・スケール不問)
# 以前20pxだったが、見た目のデザインが無い状態(design_visible=False)だと
# マウスを正確に合わせづらく「機能していないように見える」ため、当たり判定を広げた。

MENU_TOGGLE_SIZE = 24  # メニュートグルボタンのサイズ(px、スケール不問の固定値)
MENU_ANIM_DURATION_MS = 240  # メニュー開閉アニメーションの時間(ms)
CHAT_PANEL_WIDTH = 220  # 会話入力パネルの幅(px、スケール不問)
CHAT_PANEL_HEIGHT = 110  # 会話入力パネルの高さ(px、スケール不問)
CHAT_SCORE_ANIM_DURATION_MS = 1400  # 評価スコア表示がフェードイン→浮かんで消えるまでの時間
CHAT_CLOSE_BUTTON_MARGIN = 6  # 閉じるボタンとchat_panel下端の間の余白(px)


def _make_scaling_icon(size: int) -> QIcon:
    """「拡大縮小」を連想させるアイコンを描画して生成する（grip_design_toggle_button用）。

    左上⇔右下の対角線上に、外向きの矢印が付いた四角い枠を描く
    （ウィンドウの角をドラッグしてリサイズする操作を直感的に示す）。
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    margin = max(2, int(size * 0.2))
    pen = QPen(Qt.white)
    pen.setWidth(max(1, int(size * 0.08)))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)

    # 対角線上の小さい四角(左上寄り)と大きい四角(右下寄り)で「拡大」を表現
    small = max(3, int(size * 0.26))
    large = max(5, int(size * 0.42))
    painter.drawRect(margin, margin, small, small)
    painter.drawRect(size - margin - large, size - margin - large, large, large)

    # 対角線を貫く矢印で両方向への拡大縮小を示す
    arrow_start_x = margin + small + 1
    arrow_start_y = margin + small + 1
    arrow_end_x = size - margin - large - 1
    arrow_end_y = size - margin - large - 1
    painter.drawLine(arrow_start_x, arrow_start_y, arrow_end_x, arrow_end_y)

    painter.end()
    return QIcon(pixmap)


DRAG_START_THRESHOLD_PX = 6  # この距離以上動いたら「クリック」ではなく「並び替えドラッグ」とみなす


class _DraggableToggleButton(QPushButton):
    """右下に縦積みされるトグルボタン。ドラッグ&ドロップで並び順を入れ替えられる。

    通常のクリック操作と、並び替えのためのドラッグ操作を同じマウスボタンで
    区別する必要があるため、「press後にDRAG_START_THRESHOLD_PX以上動いたら
    ドラッグ」「動かずreleaseしたらクリック」という閾値判定を自前で行う
    （QPushButton標準のclickedシグナルは、ドラッグ中に誤って発火しないよう
    ドラッグが確定した時点でブロックする）。
    """

    def __init__(self, button_id: str, window: "PetWindow", parent: QWidget) -> None:
        super().__init__(parent)
        self.button_id = button_id
        self._window = window
        self._press_pos: QPoint | None = None
        self._dragging = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._press_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.globalPosition().toPoint() - self._press_pos
            if not self._dragging and delta.manhattanLength() >= DRAG_START_THRESHOLD_PX:
                self._dragging = True
                self._window.begin_toggle_button_drag(self.button_id)
            if self._dragging:
                self._window.update_toggle_button_drag(event.globalPosition().toPoint())
                return  # ドラッグ中はQPushButtonのhover等の既定動作を抑止する
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        was_dragging = self._dragging
        self._press_pos = None
        self._dragging = False
        if was_dragging:
            self._window.end_toggle_button_drag()
            return  # ドラッグ確定時はclickedを発火させない（意図しない押下を防ぐ）
        super().mouseReleaseEvent(event)


class _ResizeGrip(QWidget):
    """ウィンドウの四隅に重ねて置く専用のリサイズハンドル。

    ボタン列やステータスパネルと重なる位置にあるため、通常のPetWindow.mouseMoveEvent内の
    座標判定では他のウィジェットにイベントが吸収されてカーソル変化・ドラッグ判定ができない。
    専用の小さな子ウィジェットとして独立させることで、確実にマウスイベントを受け取る。
    """

    # 角ごとのカーソル形状（左上/右下は同じ斜め、右上/左下は逆の斜め）
    _CURSOR_BY_CORNER = {
        "top_left": Qt.SizeFDiagCursor,
        "bottom_right": Qt.SizeFDiagCursor,
        "top_right": Qt.SizeBDiagCursor,
        "bottom_left": Qt.SizeBDiagCursor,
    }

    def __init__(self, window: "PetWindow", corner: str, design_visible: bool = True) -> None:
        super().__init__(window)
        self._window = window
        self._corner = corner
        # デザイン（L字マーク）の表示/非表示。OFFでもクリック判定（リサイズ機能）には影響しない。
        self.design_visible = design_visible
        self.setFixedSize(RESIZE_GRIP_SIZE, RESIZE_GRIP_SIZE)
        self.setCursor(QCursor(self._CURSOR_BY_CORNER[corner]))
        # 親(PetWindow)がWA_TranslucentBackgroundのため、素のQWidgetだと
        # このウィジェットも半透明合成扱いになり、alphaの薄い領域でクリックが
        # 背後（PetWindowのmousePressEvent等）へ素通りすることがある。
        # このウィジェット自身にもWA_TranslucentBackgroundを与えてピクセル単位の
        # 透過合成にすることで、alpha=1のごく薄い塗り部分だけがクリック判定として
        # 機能しつつ、見た目は背景に溶け込んで四角い継ぎ目が出ないようにする。
        # （WA_OpaquePaintEventを使うと矩形全体が不透明ブロックとして合成され、
        # design_visible=False時でも四角く見えてしまったため、こちらに変更）
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._window.begin_resize(event.globalPosition().toPoint(), self._corner)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.LeftButton:
            self._window.update_resize(event.globalPosition().toPoint())

    def paintEvent(self, event: QPaintEvent) -> None:
        """角の位置にL字型のコーナーマークを描き、リサイズ可能な場所だと一目で分かるようにする。

        白い縁取り＋黒い線の二重描画にすることで、デスクトップの壁紙がどんな色でも視認できる。
        design_visible=Falseの場合はL字マークは描かないが、完全な透明(alpha=0)のまま
        にすると、親ウィンドウのWA_TranslucentBackgroundの影響でこの領域のクリックが
        背後へ素通りしてしまう（Windowsの透過ウィンドウで実機クリックのみ発生し、
        QTestでのシミュレーションでは再現されない問題だった）。そのため、ほぼ見えない
        ごく薄いalphaで塗りつぶし、クリック判定だけは機能させる。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.design_visible:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
            return
        # マーク自体はクリック当たり判定(RESIZE_GRIP_SIZE)より小さく描き、
        # 見た目の主張を抑える（当たり判定サイズは変更しない）。
        margin = 8
        length = (RESIZE_GRIP_SIZE - margin * 2) // 2
        if self._corner == "top_left":
            points = [(margin, margin + length), (margin, margin), (margin + length, margin)]
        else:  # top_right
            points = [
                (RESIZE_GRIP_SIZE - margin - length, margin),
                (RESIZE_GRIP_SIZE - margin, margin),
                (RESIZE_GRIP_SIZE - margin, margin + length),
            ]
        for color, width in ((Qt.white, 3), (Qt.black, 1)):
            pen = QPen(color)
            pen.setWidth(width)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(*points[0], *points[1])
            painter.drawLine(*points[1], *points[2])

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._window.end_resize()


class PetWindow(QWidget):
    def __init__(self, controller: PetController) -> None:
        super().__init__()
        self.controller = controller
        self.state = controller.state
        self._drag_offset: QPoint | None = None
        self._scale = 1.0  # 表示スケール係数（1.0が基準サイズ、PET_SIZE等の定数に乗算して使う）
        self._resizing = False  # 角ドラッグでリサイズ中かどうか
        self._resize_start_pos: QPoint | None = None  # リサイズ開始時のグローバル座標
        self._resize_start_scale = 1.0  # リサイズ開始時のスケール
        self._resize_corner: str | None = None  # ドラッグ中の角("top_left"等)
        self._resize_anchor = QPoint(0, 0)  # リサイズ中、固定したままにする対角の角の座標
        self._feeding_in_progress = False  # 餌やりモーション中の多重実行防止フラグ
        self._petting_in_progress = False  # なでるモーション中の多重実行防止フラグ
        self._current_expression: str | None = None  # 直前に表示した表情（再起動判定用）
        self._current_image_path: Path | None = None  # 直前に表示した画像パス（スケール変更時の再描画用）
        self._normal_frame_index = 0
        self._normal_frame_direction = 1  # 往復(ピンポン)の進行方向: +1 or -1
        self._angry_bottom_left_ref: QLabel | None = None  # 表示中の左下怒りアイコン（GC防止）
        self._angry_top_right_ref: QLabel | None = None  # 表示中の右上怒りアイコン（GC防止）
        self._angry_effect_active = False  # 怒りエフェクトのサイクルが進行中かどうか（stop時の多重singleShot防止）
        self._always_on_top = True  # ウィンドウの最前面固定状態（トグルボタンで切り替え）
        # モーション（餌やり/なでる）がアニメーションの一時停止・加速を制御している間は
        # refresh_appearance側の表情変化によるタイマー起動/停止を無視する。
        # これにより「カス散布中に満腹度が変わって表情が切り替わる」等のケースでも
        # モーション側の制御（停止させたい/加速させたい）が優先され、意図しない
        # タイマー再起動（速度リセットや二重起動）が起きない。
        self._motion_controls_animation = False
        self._menu_open = False  # アクションボタン列（折りたたみメニュー）の開閉状態
        self._grip_design_visible = True  # リサイズグリップのL字デザイン表示状態(top_rightは対象外・常にFalse)
        self._menu_animation_group: QParallelAnimationGroup | None = None  # 実行中のメニュー開閉アニメーション(多重開始防止用に保持)
        self._button_bar_open_height = 0  # 開いた時のbutton_barの高さ(px)。_apply_scaleで確定する
        self._status_open = False  # ステータスパネル（折りたたみメニュー）の開閉状態
        self._status_animation_group: QParallelAnimationGroup | None = None  # 実行中のステータスパネル開閉アニメーション(多重開始防止用に保持)
        self._status_panel_open_height = 0  # 開いた時のstatus_panelの高さ(px)。_apply_scaleで確定する
        self._chat_open = False  # 会話入力パネルの開閉状態
        self._chat_animation_group: QParallelAnimationGroup | None = None  # 実行中の会話パネル開閉アニメーション(多重開始防止用に保持)
        self._chat_panel_open_height = 0  # 開いた時のchat_panelの高さ(px)。_apply_scaleで確定する

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.label = QLabel(self)
        self.label.setFixedSize(PET_SIZE, PET_SIZE)
        self.label.setAlignment(Qt.AlignCenter)
        # 透過PNGの透明部分からデスクトップが透けて見えるよう、ラベル自体の背景も透過にする
        self.label.setStyleSheet("background: transparent;")

        self._normal_anim_timer = QTimer(self)
        self._normal_anim_timer.setInterval(NORMAL_ANIM_INTERVAL_MS)
        self._normal_anim_timer.timeout.connect(self._advance_normal_frame)

        # 最背面固定モードの間、定期的にSetWindowPos(HWND_BOTTOM)を送り直して
        # Z-orderを維持する（Windowsの仕様上、最背面は一回限りの指示のため）
        self._keep_bottom_timer = QTimer(self)
        self._keep_bottom_timer.setInterval(500)
        self._keep_bottom_timer.timeout.connect(self._reassert_bottom_z_order)

        self._build_status_bars()
        self._build_anim_speed_panel()
        self._build_button_bar()
        self._build_quit_toggle_button()
        self._build_menu_toggle_button()
        self._build_status_toggle_button()
        self._build_grip_design_toggle_button()
        self._build_always_on_top_toggle_button()
        self._build_chat_toggle_button()
        self._build_chat_panel()
        self._all_toggle_buttons = (
            self.quit_toggle_button,
            self.menu_toggle_button,
            self.status_toggle_button,
            self.grip_design_toggle_button,
            self.always_on_top_toggle_button,
            self.chat_toggle_button,
        )
        # ボタンID→ウィジェットの対応表。並び順はstate.toggle_button_orderが正であり、
        # ここはIDから実体を引くためだけに使う（今後ボタンが増えてもここに1行
        # 追加しDEFAULT_TOGGLE_BUTTON_ORDERに加えるだけで対応できる）。
        self._toggle_button_by_id: dict[str, _DraggableToggleButton] = {
            button.button_id: button for button in self._all_toggle_buttons
        }
        self._drag_button_id: str | None = None  # 現在ドラッグ中のボタンID（非ドラッグ中はNone）
        self._drag_drop_index: int = -1  # ドラッグ中、現在カーソルが示している挿入先インデックス
        self._drop_indicator = QWidget(self)  # ドラッグ中、挿入先を示す青い横線
        self._drop_indicator.setStyleSheet("background-color: rgba(70, 150, 255, 230); border-radius: 1px;")
        self._drop_indicator.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        # chat_panelはstatus_panelよりさらに上（ウィンドウ最上部）に出すため、
        # レイアウトの一番最初に追加する。両方ともmaximumHeightで畳む方式なので、
        # 同時に開いても自動的に縦に積まれ、ペット画像や互いに重ならない。
        layout.addWidget(self.chat_panel)
        layout.addWidget(self.status_panel)
        layout.addWidget(self.anim_speed_panel)
        layout.addWidget(self.label)
        # 末尾にstretchを入れないと、ウィンドウ高さを直接setGeometryで変更した際に
        # QVBoxLayoutが余白の配分先を一意に決められず、maximumHeight=0で畳んでいる
        # status_panel側にy座標のズレとして現れることがあった（高さ自体は0のまま）。
        # stretchを「余白を受け止める専用の伸縮要素」として末尾に置くことで、
        # 他の要素（label等）の位置を変えずに余白をここへ集約させる。
        layout.addStretch(1)
        # button_barは「☰アイコンの位置からぬるっと拡大して現れる」演出のため、
        # レイアウト管理から外し絶対配置にする（geometryを自由にアニメーションさせるため）。
        # 開閉中のウィンドウ全体の高さ拡張は_toggle_menu内で手動計算する。

        # メニュー・ステータスパネル・会話パネルは初期状態で閉じておく（maximumHeight=0/非表示で畳む）
        self.button_bar.hide()
        self.status_panel.setMaximumHeight(0)
        self.chat_panel.setMaximumHeight(0)

        # リサイズグリップ（四隅）・トグルボタン類はレイアウト管理外の
        # 子ウィジェットとして絶対配置する（他のウィジェットの上に重ねて表示するため、layoutには追加しない）
        # 左下・右下はメニュー/ステータストグルボタンと重なる位置にあり、
        # トグルボタンが前面に来ることでグリップがマウスイベントを受け取れず
        # 機能しないことがあったため、上2角のみをリサイズ対象にする。
        # top_rightはデザイン（L字マーク）を常に非表示にする（機能は他の角と同様に動作する）
        self._resize_grips = {
            "top_left": _ResizeGrip(self, "top_left", design_visible=True),
            "top_right": _ResizeGrip(self, "top_right", design_visible=False),
        }
        for grip in self._resize_grips.values():
            grip.show()
            grip.raise_()
        for toggle_button in self._all_toggle_buttons:
            toggle_button.show()
            toggle_button.raise_()

        # 速度確認作業は完了したため非表示化（ロジック・スライダー自体は残す）
        self.anim_speed_panel.setVisible(False)

        x, y = self.state.window_position
        self.move(x, y)

        # 初期状態（常に最前面）をWin32レベルでも明示しておく
        # （Qt標準フラグのみでも機能するが、最背面への切り替えとの対称性のため統一する）
        _set_window_z_order(int(self.winId()), _HWND_TOPMOST)

        self.refresh_appearance()
        self.refresh_status_bars()
        self._apply_scale(1.0)  # 各ウィジェットのサイズ・フォントを基準スケールで確定させる

    # --- スケール管理 ---
    def _pet_size(self) -> int:
        """現在のスケールを反映したペット画像の表示サイズ(px)。"""
        return int(PET_SIZE * self._scale)

    def _button_size(self) -> int:
        return int(BUTTON_SIZE * self._scale)

    def _toggle_button_size(self) -> int:
        """現在のスケールを反映したトグルボタン(☰📊/拡大縮小アイコン/📌)の表示サイズ(px)。

        縮小時にボタン4段分の縦積みがウィンドウ高さを超えて見切れる不具合が
        あったため、MENU_TOGGLE_SIZEを固定値ではなくスケール連動にした。
        視認性・クリックしやすさを保つため最小14pxでクランプする。
        """
        return max(14, int(MENU_TOGGLE_SIZE * self._scale))

    def _apply_scale(self, scale: float) -> None:
        """スケール係数を確定し、ウィンドウ全体のサイズ・フォント・画像を再適用する。

        MIN_SCALE〜MAX_SCALEにクランプしてから反映するため、呼び出し側は
        範囲外の値を渡しても安全。
        """
        # メニュー開閉アニメーションとリサイズ操作が同時に走ると、geometryの
        # 設定元が競合して状態が壊れうるため、リサイズ時は進行中のアニメーションを打ち切る
        if self._menu_animation_group is not None:
            self._menu_animation_group.stop()
            self._menu_animation_group = None
        if self._status_animation_group is not None:
            self._status_animation_group.stop()
            self._status_animation_group = None

        self._scale = max(MIN_SCALE, min(MAX_SCALE, scale))
        pet_size = self._pet_size()
        button_size = self._button_size()

        self.label.setFixedSize(pet_size, pet_size)
        if self._current_image_path is not None:
            # 元画像から再スケールする（表示中のpixmapを再拡大すると多重縮小で劣化するため）
            pixmap = QPixmap(str(self._current_image_path))
            if not pixmap.isNull():
                pixmap = pixmap.scaled(
                    pet_size, pet_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.label.setPixmap(pixmap)

        for button in self._all_buttons:
            button.setFixedSize(button_size, button_size)

        # トグルボタン(☰/📊/拡大縮小アイコン/📌)もスケールに追従させる。
        # 固定サイズのままだと縮小時に4段の縦積みがウィンドウ高さを超えて
        # 見切れてしまうため、_toggle_button_size()で算出したサイズに揃える。
        toggle_size = self._toggle_button_size()
        for toggle_button in self._all_toggle_buttons:
            toggle_button.setFixedSize(toggle_size, toggle_size)
        toggle_font_px = max(8, int(14 * self._scale))
        for toggle_button in (
            self.quit_toggle_button,
            self.menu_toggle_button,
            self.status_toggle_button,
            self.always_on_top_toggle_button,
            self.chat_toggle_button,
        ):
            style = toggle_button.styleSheet()
            toggle_button.setStyleSheet(style.replace("font-size: 14px", f"font-size: {toggle_font_px}px"))
        scaling_icon_size = max(8, int(toggle_size * 0.65))
        self.grip_design_toggle_button.setIcon(_make_scaling_icon(scaling_icon_size))
        self.grip_design_toggle_button.setIconSize(QSize(scaling_icon_size, scaling_icon_size))

        button_font_px = max(8, int(16 * self._scale))
        button_style = (
            "QPushButton {"
            " background-color: rgba(255, 255, 255, 160);"
            f" border: none; border-radius: 6px; font-size: {button_font_px}px;"
            "}"
            "QPushButton:hover { background-color: rgba(255, 255, 255, 220); }"
            "QPushButton:disabled { background-color: rgba(255, 255, 255, 60); }"
        )
        for button in self._all_buttons:
            button.setStyleSheet(button_style)
        # button_bar自体もstatus_panelと同じ理由で幅を明示的に固定する
        # （中のボタンをsetFixedSizeで縮めただけではbutton_barのsizeHint
        # キャッシュが追従せず、古い大きい幅のまま残ってしまう）
        self.button_bar.setFixedWidth(pet_size)
        # レイアウト外の絶対配置になったため、開いた時の実寸サイズ・位置は
        # 自前で管理する。labelの位置はこの時点ではまだ確定していないため
        # （resize()はこの後）、実際のgeometry再配置は本メソッド末尾で行う。
        self._button_bar_open_height = self.button_bar.sizeHint().height()

        gauge_height = max(4, int(8 * self._scale))
        label_font_px = max(7, int(10 * self._scale))
        label_width = max(16, int(28 * self._scale))
        # status_panel自体の幅をpet_sizeに明示的に固定する。これが無いと、
        # 中のQProgressBar/QLabelをsetFixedWidthで縮めても、status_panelの
        # sizeHintキャッシュが縮小方向に追従せず、ウィンドウ全体の幅が
        # ステータスパネルの古い（大きい）幅に引っ張られたままになる。
        panel_h_margin = 6  # _build_status_barsのpanel_layout.setContentsMargins(6, 4, 6, 4)と合わせる
        row_spacing = 4  # 各rowのsetSpacing(4)と合わせる
        self.status_panel.setFixedWidth(pet_size)
        gauge_width = max(20, pet_size - label_width - row_spacing - panel_h_margin * 2)
        for bar in (self.hunger_bar, self.mood_bar, self.stamina_bar):
            bar.setFixedWidth(gauge_width)
            bar.setFixedHeight(gauge_height)
        for text_label in self._status_text_labels:
            text_label.setStyleSheet(f"color: white; font-size: {label_font_px}px;")
            text_label.setFixedWidth(label_width)
        # button_barと同様、折りたたみの「開いた時の高さ」をスケールに応じて更新する。
        # 閉じている時はmaximumHeight=0を維持する（折りたたみ状態を壊さない）。
        self._status_panel_open_height = self.status_panel.sizeHint().height()
        if self._status_open:
            self.status_panel.setMaximumHeight(self._status_panel_open_height)

        # chat_panelもstatus_panelと同じ理由で幅を固定し、開いた高さを更新する。
        # 本体の高さはウィンドウの縦サイズに対して固定割合（最大CHAT_PANEL_HEIGHT）にし、
        # そこに閉じるボタン用の余白（panel_layout.addSpacingで確保済み）を加えた
        # sizeHint().height()を実際の「開いた高さ」として使う。
        self.chat_panel.setFixedWidth(pet_size)
        content_height = min(CHAT_PANEL_HEIGHT, max(80, int(pet_size * 0.6)))
        self.chat_result_scroll.setMinimumHeight(max(20, content_height - 40))
        self._chat_panel_open_height = self.chat_panel.sizeHint().height()
        if self._chat_open:
            self.chat_panel.setMaximumHeight(self._chat_panel_open_height)

        # レイアウト管理下の子ウィジェットのサイズ変更をウィンドウ全体に反映させる。
        # adjustSize()単体だと、一度大きくなったウィンドウが縮小方向にはうまく
        # 追従しない（Qtのレイアウトキャッシュにより最小サイズが大きいまま残る）
        # ことがあるため、制約を一旦解除してからレイアウトを再計算させる。
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)  # QWIDGETSIZE_MAX（実質無制限）
        self.layout().invalidate()
        self.layout().activate()
        # adjustSize()はレイアウト外の絶対配置の子ウィジェット（リサイズグリップ・
        # トグルボタン類）の現在位置も暗黙的に考慮してしまい、縮小前の古い位置が
        # 残っていると最小幅がそれに引っ張られて縮小できないことがあった。
        # そのため、レイアウトのsizeHintから直接resize()してウィンドウサイズを
        # 確定させる（絶対配置の子ウィジェットの影響を受けない）。
        self.resize(self.layout().sizeHint())
        if self._menu_open:
            # button_barはレイアウト外のため、layout().sizeHint()にはその高さが
            # 含まれない。メニューが開いたままリサイズされた場合は、ここで
            # ウィンドウ高さにbutton_bar分を追加し、button_bar自体も
            # labelの実位置を基準に（アニメーションなしで）再配置する。
            self.resize(self.width(), self.height() + self._button_bar_open_height)
            self.button_bar.setGeometry(self._button_bar_open_rect())
        # ウィンドウサイズが確定した後、グリップ・トグルボタン類を追従させる
        self._reposition_overlay_widgets()

    # --- ステータスゲージの構築 ---
    def _build_status_bars(self) -> None:
        """満腹度/機嫌/体力を小さいQProgressBarで常時表示するパネル。"""
        self.status_panel = QWidget(self)
        self.status_panel.setStyleSheet(
            "background-color: rgba(0, 0, 0, 110); border-radius: 8px;"
        )
        # sizePolicyを明示しないと、ウィンドウ高さを直接setGeometryで変更した際に
        # QVBoxLayoutが余白をこのウィジェットの上下に配分してしまい、
        # maximumHeight=0で畳んでいてもy座標がシフトしてlabel位置がズレる
        # （button_bar等、label位置を基準に絶対配置する要素とのズレの原因になる）。
        self.status_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        panel_layout = QVBoxLayout(self.status_panel)
        panel_layout.setContentsMargins(6, 4, 6, 4)
        panel_layout.setSpacing(2)

        self.hunger_bar = self._make_status_bar()
        self.mood_bar = self._make_status_bar()
        self.stamina_bar = self._make_status_bar()
        self._status_text_labels: list[QLabel] = []  # _apply_scaleでフォント/幅を再適用するため保持

        for label_text, bar in (
            ("満腹", self.hunger_bar),
            ("機嫌", self.mood_bar),
            ("体力", self.stamina_bar),
        ):
            row = QHBoxLayout()
            row.setSpacing(4)
            text_label = QLabel(label_text, self.status_panel)
            text_label.setStyleSheet("color: white; font-size: 10px;")
            text_label.setFixedWidth(28)
            self._status_text_labels.append(text_label)
            row.addWidget(text_label)
            row.addWidget(bar)
            panel_layout.addLayout(row)

    def _make_status_bar(self) -> QProgressBar:
        bar = QProgressBar(self.status_panel)
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setFixedWidth(PET_SIZE - 40)
        return bar

    def refresh_status_bars(self) -> None:
        """現在のステータス値をゲージに反映し、値に応じて色を変える。"""
        for bar, value in (
            (self.hunger_bar, self.state.hunger),
            (self.mood_bar, self.state.mood),
            (self.stamina_bar, self.state.stamina),
        ):
            bar.setValue(int(value))
            bar.setStyleSheet(
                "QProgressBar { background-color: rgba(255,255,255,60); border-radius: 4px; }"
                f"QProgressBar::chunk {{ background-color: {self._gauge_color(value)}; border-radius: 4px; }}"
            )

    @staticmethod
    def _gauge_color(value: float) -> str:
        """値が低いほど赤、高いほど緑に近づく簡易な2色補間。"""
        if value >= 50:
            return "#4caf50" if value >= 75 else "#8bc34a"
        return "#f44336" if value < 25 else "#ff9800"

    # --- アニメーション速度調整スライダーの構築（確認用・一時機能） ---
    def _build_anim_speed_panel(self) -> None:
        """通常アニメーションのフレーム切り替え間隔をリアルタイム調整するスライダー。

        動作確認用の一時的なUIのため永続化はしない（再起動でデフォルト値に戻る）。
        """
        self.anim_speed_panel = QWidget(self)
        self.anim_speed_panel.setStyleSheet(
            "background-color: rgba(0, 0, 0, 110); border-radius: 8px;"
        )
        # status_panelと同じ理由でFixedにする（setVisible(False)でも
        # レイアウトの余白配分計算自体には影響しないため明示が必要）。
        self.anim_speed_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        panel_layout = QHBoxLayout(self.anim_speed_panel)
        panel_layout.setContentsMargins(6, 4, 6, 4)
        panel_layout.setSpacing(4)

        self.anim_speed_slider = QSlider(Qt.Horizontal, self.anim_speed_panel)
        self.anim_speed_slider.setRange(ANIM_SPEED_SLIDER_MIN_MS, ANIM_SPEED_SLIDER_MAX_MS)
        self.anim_speed_slider.setValue(NORMAL_ANIM_INTERVAL_MS)
        self.anim_speed_slider.setFixedWidth(PET_SIZE - 60)
        self.anim_speed_slider.valueChanged.connect(self._on_anim_speed_changed)

        self.anim_speed_label = QLabel(f"{NORMAL_ANIM_INTERVAL_MS}ms", self.anim_speed_panel)
        self.anim_speed_label.setStyleSheet("color: white; font-size: 10px;")
        self.anim_speed_label.setFixedWidth(40)

        panel_layout.addWidget(self.anim_speed_slider)
        panel_layout.addWidget(self.anim_speed_label)

    def _on_anim_speed_changed(self, value: int) -> None:
        """スライダー変更を即座にラベル表示とタイマー間隔の両方へ反映する。

        setInterval()は実行中のQTimerにも安全に呼べ、次回のtimeout予定から
        新しい間隔が使われる（往復フレームのindex/directionには影響しない）。
        """
        self.anim_speed_label.setText(f"{value}ms")
        self._normal_anim_timer.setInterval(value)

    # --- ボタン列の構築 ---
    def _build_button_bar(self) -> None:
        """ペット画像下に常時表示する操作ボタン列を作る。

        透過ウィンドウ上でもボタンが視認できるよう、半透明パネルを背景に敷く。
        """
        self.button_bar = QWidget(self)
        self.button_bar.setStyleSheet(
            "background-color: rgba(0, 0, 0, 110); border-radius: 8px;"
        )
        bar_layout = QHBoxLayout(self.button_bar)
        bar_layout.setContentsMargins(4, 4, 4, 4)
        bar_layout.setSpacing(4)

        button_style = (
            "QPushButton {"
            " background-color: rgba(255, 255, 255, 160);"
            " border: none; border-radius: 6px; font-size: 16px;"
            "}"
            "QPushButton:hover { background-color: rgba(255, 255, 255, 220); }"
            "QPushButton:disabled { background-color: rgba(255, 255, 255, 60); }"
        )

        self.feed_button = QPushButton("🍖", self.button_bar)
        self.feed_button.setToolTip("餌やり")
        self.feed_button.clicked.connect(self._on_feed_clicked)

        self.pet_button = QPushButton("👋", self.button_bar)
        self.pet_button.setToolTip("なでる")
        self.pet_button.clicked.connect(self._on_pet_clicked)

        self.time_button = QPushButton("⏰", self.button_bar)
        self.time_button.setToolTip("時間操作")
        self.time_button.clicked.connect(self._on_time_clicked)

        self._all_buttons = (
            self.feed_button,
            self.pet_button,
            self.time_button,
        )
        for button in self._all_buttons:
            button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            button.setStyleSheet(button_style)
            bar_layout.addWidget(button)

    def _build_quit_toggle_button(self) -> None:
        """常時表示する終了ボタン（❌）。縦積みスタックの一員として並び替え対象になる。

        以前はアクションメニュー(button_bar)内にあったが、他のトグルボタンと
        同じ「常時表示の縦積みスタック」にまとめてほしいとの要望で移設した。
        """
        self.quit_toggle_button = _DraggableToggleButton("quit", self, self)
        self.quit_toggle_button.setText("❌")
        self.quit_toggle_button.setToolTip("終了（ドラッグで並び替え可能）")
        self.quit_toggle_button.setFixedSize(MENU_TOGGLE_SIZE, MENU_TOGGLE_SIZE)
        self.quit_toggle_button.setStyleSheet(
            "QPushButton {"
            " background-color: rgba(60, 60, 60, 200);"
            " border: 1.5px solid rgba(255, 255, 255, 220);"
            " border-radius: 6px; font-size: 14px; color: white;"
            "}"
            "QPushButton:hover { background-color: rgba(90, 90, 90, 220); }"
        )
        self.quit_toggle_button.clicked.connect(self._on_quit_clicked)

    # --- メニュートグルボタンの構築・開閉制御 ---
    def _build_menu_toggle_button(self) -> None:
        """常時表示する小さな開閉ボタン（☰）。クリックでbutton_barの開閉をトグルする。"""
        self.menu_toggle_button = _DraggableToggleButton("menu", self, self)
        self.menu_toggle_button.setText("☰")
        self.menu_toggle_button.setToolTip("メニュー（ドラッグで並び替え可能）")
        self.menu_toggle_button.setFixedSize(MENU_TOGGLE_SIZE, MENU_TOGGLE_SIZE)
        # 白い背景の上でも視認できるよう、枠線と影でアイコンの輪郭を強調する
        # （半透明の背景だけだと白背景のデスクトップにほぼ溶け込んでしまうため）
        self.menu_toggle_button.setStyleSheet(
            "QPushButton {"
            " background-color: rgba(60, 60, 60, 200);"
            " border: 1.5px solid rgba(255, 255, 255, 220);"
            " border-radius: 6px; font-size: 14px; color: white;"
            "}"
            "QPushButton:hover { background-color: rgba(90, 90, 90, 220); }"
        )
        self.menu_toggle_button.clicked.connect(self._toggle_menu)

    def _build_status_toggle_button(self) -> None:
        """常時表示する小さな開閉ボタン（📊）。クリックでstatus_panelの開閉をトグルする。

        見た目はmenu_toggle_buttonと統一し、縦に積み上がる1つ目のボタンとして配置する。
        """
        self.status_toggle_button = _DraggableToggleButton("status", self, self)
        self.status_toggle_button.setText("📊")
        self.status_toggle_button.setToolTip("ステータス（ドラッグで並び替え可能）")
        self.status_toggle_button.setFixedSize(MENU_TOGGLE_SIZE, MENU_TOGGLE_SIZE)
        self.status_toggle_button.setStyleSheet(
            "QPushButton {"
            " background-color: rgba(60, 60, 60, 200);"
            " border: 1.5px solid rgba(255, 255, 255, 220);"
            " border-radius: 6px; font-size: 14px; color: white;"
            "}"
            "QPushButton:hover { background-color: rgba(90, 90, 90, 220); }"
        )
        self.status_toggle_button.clicked.connect(self._toggle_status_panel)

    def _build_grip_design_toggle_button(self) -> None:
        """リサイズグリップのL字デザインの表示/非表示を切り替えるボタン（拡大縮小アイコン）。

        OFFにしてもリサイズ機能自体（クリック判定）は常に動作する。
        見た目はmenu_toggle_button/status_toggle_buttonと統一し、縦積みの3段目に置く。
        絵文字の👁だと「拡大縮小の表示切り替え」であることが伝わりにくいため、
        対角線上の矢印でスケーリングを直感的に示す自作アイコンを使う。
        """
        self.grip_design_toggle_button = _DraggableToggleButton("grip_design", self, self)
        icon_size = int(MENU_TOGGLE_SIZE * 0.65)
        self.grip_design_toggle_button.setIcon(_make_scaling_icon(icon_size))
        self.grip_design_toggle_button.setIconSize(QSize(icon_size, icon_size))
        self.grip_design_toggle_button.setToolTip("リサイズハンドルの表示切り替え（ドラッグで並び替え可能）")
        self.grip_design_toggle_button.setFixedSize(MENU_TOGGLE_SIZE, MENU_TOGGLE_SIZE)
        self.grip_design_toggle_button.setStyleSheet(
            "QPushButton {"
            " background-color: rgba(60, 60, 60, 200);"
            " border: 1.5px solid rgba(255, 255, 255, 220);"
            " border-radius: 6px; font-size: 14px; color: white;"
            "}"
            "QPushButton:hover { background-color: rgba(90, 90, 90, 220); }"
        )
        self.grip_design_toggle_button.clicked.connect(self._toggle_grip_design)

    def _toggle_grip_design(self) -> None:
        """全リサイズグリップのL字デザイン表示/非表示を一括で切り替える。

        top_rightは常にデザイン非表示固定のため対象外にする
        （元々design_visible=Falseなので、切り替えても見た目に変化が出ない）。
        """
        self._grip_design_visible = not self._grip_design_visible
        self._update_top_left_grip_design()

    def _update_top_left_grip_design(self) -> None:
        """top_leftグリップの実際のデザイン表示状態を再計算して反映する。

        ユーザーが👁ボタンで設定したON/OFF(_grip_design_visible)と、
        status_panel表示中は強制的にデザインを隠す仕様の両方を踏まえて
        最終的な表示状態を決める（クリック判定=リサイズ機能自体は影響を受けない）。
        """
        grip = self._resize_grips["top_left"]
        grip.design_visible = self._grip_design_visible and not self._status_open
        grip.update()

    def _build_always_on_top_toggle_button(self) -> None:
        """常時最前面表示のON/OFFを切り替えるボタン（📌）。

        見た目は他のトグルボタンと統一し、縦積みの4段目に置く。
        """
        self.always_on_top_toggle_button = _DraggableToggleButton("always_on_top", self, self)
        self.always_on_top_toggle_button.setText("📌")
        self.always_on_top_toggle_button.setFixedSize(MENU_TOGGLE_SIZE, MENU_TOGGLE_SIZE)
        self.always_on_top_toggle_button.clicked.connect(self._toggle_always_on_top)
        self._update_always_on_top_button_style()

    def _update_always_on_top_button_style(self) -> None:
        """最前面/最背面の現在状態に応じてボタンの見た目（色・ツールチップ）を切り替える。

        状態が一見して分かるよう、最前面=目立つ青系、最背面=通常のグレーにする。
        """
        if self._always_on_top:
            self.always_on_top_toggle_button.setToolTip(
                "常に最前面に表示中（クリックで最背面へ、ドラッグで並び替え可能）"
            )
            self.always_on_top_toggle_button.setStyleSheet(
                "QPushButton {"
                " background-color: rgba(40, 110, 220, 220);"
                " border: 1.5px solid rgba(255, 255, 255, 220);"
                " border-radius: 6px; font-size: 14px; color: white;"
                "}"
                "QPushButton:hover { background-color: rgba(60, 130, 240, 240); }"
            )
        else:
            self.always_on_top_toggle_button.setToolTip(
                "常に最背面に表示中（クリックで最前面へ、ドラッグで並び替え可能）"
            )
            self.always_on_top_toggle_button.setStyleSheet(
                "QPushButton {"
                " background-color: rgba(60, 60, 60, 200);"
                " border: 1.5px solid rgba(255, 255, 255, 220);"
                " border-radius: 6px; font-size: 14px; color: white;"
                "}"
                "QPushButton:hover { background-color: rgba(90, 90, 90, 220); }"
            )

    def _toggle_always_on_top(self) -> None:
        """常時最前面表示/常時最背面表示を切り替える。

        最前面側はQtのWindowStaysOnTopHint（Win32のHWND_TOPMOST相当）で、
        他ウィンドウをクリックされても崩れない持続的な固定として機能する。
        一方、HWND_BOTTOMによる最背面は一回限りの「今だけ一番後ろ」という
        指示でしかなく、Windowsの仕様上は他ウィンドウがアクティブになる
        たびに前後関係が崩れる。これを「常に最背面」として維持するため、
        最背面モードの間はQTimerで定期的にSetWindowPos(HWND_BOTTOM)を
        送り直し続ける（_keep_bottom_timerで制御）。
        """
        self._always_on_top = not self._always_on_top
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self._always_on_top)
        self.show()
        self._update_always_on_top_button_style()

        hwnd = int(self.winId())
        if self._always_on_top:
            self._keep_bottom_timer.stop()
            _set_window_z_order(hwnd, _HWND_TOPMOST)
        else:
            _set_window_z_order(hwnd, _HWND_BOTTOM)
            self._keep_bottom_timer.start()

        self._raise_resize_grips()
        for toggle_button in self._all_toggle_buttons:
            toggle_button.raise_()

    def _reassert_bottom_z_order(self) -> None:
        """最背面モード中、定期的にウィンドウを最背面へ送り直す（_keep_bottom_timer用）。"""
        _set_window_z_order(int(self.winId()), _HWND_BOTTOM)

    def _build_chat_toggle_button(self) -> None:
        """話しかける機能のON/OFFを切り替えるボタン（💬）。

        見た目は他のトグルボタンと統一し、縦積みスタックの一員として並び替え対象になる。
        """
        self.chat_toggle_button = _DraggableToggleButton("chat", self, self)
        self.chat_toggle_button.setText("💬")
        self.chat_toggle_button.setToolTip("話しかける（ドラッグで並び替え可能）")
        self.chat_toggle_button.setFixedSize(MENU_TOGGLE_SIZE, MENU_TOGGLE_SIZE)
        self.chat_toggle_button.setStyleSheet(
            "QPushButton {"
            " background-color: rgba(60, 60, 60, 200);"
            " border: 1.5px solid rgba(255, 255, 255, 220);"
            " border-radius: 6px; font-size: 14px; color: white;"
            "}"
            "QPushButton:hover { background-color: rgba(90, 90, 90, 220); }"
        )
        self.chat_toggle_button.clicked.connect(self._toggle_chat_panel)

    def _build_chat_panel(self) -> None:
        """話しかける入力欄パネル（テキスト入力＋送信ボタン＋スクロール可能な結果表示）。

        status_panelと同様、ウィンドウ最上部（status_panelが開いていればそのさらに上）に
        配置する絶対配置パネル。ウィンドウ全体のgeometryも開閉に合わせて拡張する。
        """
        self.chat_panel = QWidget(self)
        self.chat_panel.setStyleSheet(
            "background-color: rgba(30, 30, 30, 230);"
            " border: 1.5px solid rgba(255, 255, 255, 200); border-radius: 8px;"
        )
        panel_layout = QVBoxLayout(self.chat_panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(6)

        input_row = QHBoxLayout()
        input_row.setSpacing(4)
        self.chat_input = QLineEdit(self.chat_panel)
        self.chat_input.setPlaceholderText("話しかけてみる...")
        self.chat_input.setStyleSheet(
            "background-color: rgba(255, 255, 255, 230); border-radius: 4px; padding: 2px 4px;"
        )
        self.chat_input.returnPressed.connect(self._on_chat_send_clicked)
        self.chat_send_button = QPushButton("送信", self.chat_panel)
        self.chat_send_button.setStyleSheet(
            "QPushButton {"
            " background-color: rgba(255, 255, 255, 160);"
            " border: none; border-radius: 6px; font-size: 12px;"
            "}"
            "QPushButton:hover { background-color: rgba(255, 255, 255, 220); }"
            "QPushButton:disabled { background-color: rgba(255, 255, 255, 60); }"
        )
        self.chat_send_button.clicked.connect(self._on_chat_send_clicked)
        input_row.addWidget(self.chat_input)
        input_row.addWidget(self.chat_send_button)

        # ナレーションが長い場合に見切れないよう、結果表示部分をスクロール可能にする
        self.chat_result_label = QLabel("", self.chat_panel)
        self.chat_result_label.setWordWrap(True)
        self.chat_result_label.setStyleSheet("color: white; font-size: 12px;")
        self.chat_result_scroll = QScrollArea(self.chat_panel)
        self.chat_result_scroll.setWidget(self.chat_result_label)
        self.chat_result_scroll.setWidgetResizable(True)
        self.chat_result_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            " QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self.chat_result_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        panel_layout.addLayout(input_row)
        panel_layout.addWidget(self.chat_result_scroll)
        # 閉じるボタン用の余白をレイアウト内に確保する（chat_panel自体の高さに
        # 含めることで、下に続くstatus_panel等が自動的にその分押し下げられ、
        # 重なりが構造的に起きないようにする）。
        panel_layout.addSpacing(MENU_TOGGLE_SIZE + CHAT_CLOSE_BUTTON_MARGIN)

        # 評価スコア(mood変化量)をふわっと表示するラベル。chat_panelの右上に重ねて
        # 絶対配置し、結果が出るたびにフェードイン→少し上に浮かびながら消える。
        self.chat_score_label = QLabel("", self.chat_panel)
        self.chat_score_label.setStyleSheet(
            "color: rgba(255, 230, 120, 255); font-size: 14px; font-weight: bold;"
            " background: transparent;"
        )
        self.chat_score_label.setAlignment(Qt.AlignRight)
        self.chat_score_label.adjustSize()
        self.chat_score_label.hide()

        # 閉じるボタン（背景・枠なしの赤い×のみ）。chat_panelの子にして、
        # 上で確保した余白部分（chat_panel下端寄り）に絶対配置で重ねる。
        self.chat_close_button = QPushButton("✕", self.chat_panel)
        self.chat_close_button.setFixedSize(MENU_TOGGLE_SIZE, MENU_TOGGLE_SIZE)
        self.chat_close_button.setStyleSheet(
            "QPushButton {"
            " background: transparent; border: none;"
            " color: rgba(230, 60, 60, 255); font-size: 16px; font-weight: bold;"
            "}"
            "QPushButton:hover { color: rgba(255, 90, 90, 255); }"
        )
        self.chat_close_button.clicked.connect(self._toggle_chat_panel)
        self.chat_close_button.hide()

    def _toggle_chat_panel(self) -> None:
        """会話パネルの開閉状態をアニメーション付きで切り替える（_toggle_status_panelと同じ仕組み）。

        chat_panelはレイアウト内でstatus_panelより上（ウィンドウ最上部）に
        配置してあるため、maximumHeightアニメーションで開閉すれば、status_panelや
        label等の他要素は自動的に押し下げられ、重なりが構造的に起きない
        （以前の絶対配置オーバーレイ方式はペット画像に重なる不具合があったため、
        status_panelと同じレイアウト内方式に作り直した）。
        """
        self._raise_resize_grips()
        self._chat_open = not self._chat_open
        target_panel_height = self._chat_panel_open_height if self._chat_open else 0

        current_geo = self.geometry()
        height_diff = target_panel_height - self.chat_panel.maximumHeight()
        # status_panelと同じく「下から上に」展開させるため、高さが増える分だけ
        # y座標を上へ動かし、ウィンドウの下端を固定点として扱う。
        target_geo = QRect(
            current_geo.x(),
            current_geo.y() - height_diff,
            current_geo.width(),
            current_geo.height() + height_diff,
        )

        if self._chat_animation_group is not None:
            self._chat_animation_group.stop()

        panel_anim = QPropertyAnimation(self.chat_panel, b"maximumHeight", self)
        panel_anim.setDuration(MENU_ANIM_DURATION_MS)
        panel_anim.setStartValue(self.chat_panel.maximumHeight())
        panel_anim.setEndValue(target_panel_height)
        panel_anim.setEasingCurve(QEasingCurve.InOutCubic)

        geo_anim = QPropertyAnimation(self, b"geometry", self)
        geo_anim.setDuration(MENU_ANIM_DURATION_MS)
        geo_anim.setStartValue(current_geo)
        geo_anim.setEndValue(target_geo)
        geo_anim.setEasingCurve(QEasingCurve.InOutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(panel_anim)
        group.addAnimation(geo_anim)
        group.finished.connect(self._on_chat_animation_finished)
        self._chat_animation_group = group
        group.start()

        if self._chat_open:
            self.chat_input.setFocus()
            self.chat_close_button.show()
            self.chat_close_button.raise_()
        else:
            self.chat_close_button.hide()

    def _on_chat_animation_finished(self) -> None:
        """会話パネル開閉アニメーション終了時、グリップ再配置と閉じるボタン位置更新を行う。"""
        self._chat_animation_group = None
        self._reposition_overlay_widgets()
        if self._chat_open:
            self._reposition_chat_close_button()

    def _reposition_chat_close_button(self) -> None:
        """閉じるボタンをchat_panel内の最下部（_build_chat_panelでaddSpacingした余白）に配置する。

        chat_close_buttonはchat_panelの子ウィジェットなので、座標はchat_panel内の
        相対位置で指定する（status_panel等との重なりは、この余白をchat_panel自体の
        高さに含めることで構造的に防いでいる）。
        """
        self.chat_close_button.move(
            8, self.chat_panel.height() - MENU_TOGGLE_SIZE - 4
        )
        self.chat_close_button.raise_()

    def _raise_resize_grips(self) -> None:
        """リサイズグリップを最前面に上げ直す。

        status_panel/button_barの開閉アニメーションに伴うレイアウト再計算で、
        グリップが他のウィジェットの下に隠れてクリックを受け付けなくなることが
        あったため、開閉操作のたびに明示的に呼び直して確実に最前面を維持する。
        """
        for grip in self._resize_grips.values():
            grip.raise_()

    def _button_bar_open_rect(self) -> QRect:
        """button_barが開いた状態で占める、ウィンドウ座標系での矩形（ペット画像の直下）。"""
        pet_size = self._pet_size()
        return QRect(
            self.label.x(), self.label.y() + self.label.height() + 4,
            pet_size, self._button_bar_open_height,
        )

    def _close_menu_immediately(self) -> None:
        """アニメーションなしでメニューを即座に閉じる（リサイズ開始時に使う）。

        進行中の開閉アニメーションがあれば打ち切り、button_barを隠して
        ウィンドウ高さも開いていた分だけ即座に縮める。
        """
        if self._menu_animation_group is not None:
            self._menu_animation_group.stop()
            self._menu_animation_group = None
        if not self._menu_open:
            return
        self._menu_open = False
        current_geo = self.geometry()
        self.setGeometry(
            current_geo.x(), current_geo.y(),
            current_geo.width(), current_geo.height() - self.button_bar.height(),
        )
        self.button_bar.hide()
        if self.button_bar.graphicsEffect() is not None:
            self.button_bar.graphicsEffect().setOpacity(0.0)

    def _toggle_menu(self) -> None:
        """button_barの開閉状態をアニメーション付きで切り替える。

        「☰アイコンの位置から小さく現れて実寸へぬるっと広がる」演出のため、
        button_barはレイアウト外の絶対配置にしてあり、geometry（位置＋サイズ）を
        直接アニメーションさせる。閉じた状態の矩形は常にmenu_toggle_buttonの
        現在位置・サイズを基準にする（ドラッグ&ドロップで☰の段位置が変わっても
        常にそこから出入りするように見せるため）。中のボタンは広がりに合わせて
        不透明度をフェードイン/アウトさせ、縮んだ状態でボタンの形が潰れて
        見えることを隠す。

        ウィンドウ全体の高さは、button_bar自体のgeometryアニメーションとは
        切り離し、開く時は先に最終サイズへ即時確定する（QVBoxLayoutが
        ウィンドウサイズ変更のたびにlabel位置を再計算し、アニメーション中に
        open_rectの基準がずれてしまう問題を避けるため）。透過ウィンドウなので
        button_barが小さい間、周囲は透明のままで見た目には影響しない。
        """
        self._raise_resize_grips()
        self._menu_open = not self._menu_open

        closed_rect = QRect(self.menu_toggle_button.pos(), self.menu_toggle_button.size())
        start_rect = self.button_bar.geometry() if self.button_bar.isVisible() else closed_rect

        # button_barはlabel下端から4pxのマージンを空けて配置されるため、
        # ウィンドウの拡張量にもその分を含める（含めないとbutton_barの下端が
        # ウィンドウ高さをわずかに超えてはみ出す）。
        current_geo = self.geometry()
        target_bar_height = self._button_bar_open_height + 4 if self._menu_open else 0
        current_bar_height = self.button_bar.height() + 4 if self.button_bar.isVisible() else 0
        height_diff = target_bar_height - current_bar_height
        target_geo = QRect(
            current_geo.x(), current_geo.y(), current_geo.width(), current_geo.height() + height_diff
        )

        if self._menu_animation_group is not None:
            self._menu_animation_group.stop()

        if self._menu_open:
            # 開く場合: 先にウィンドウを最終サイズへ確定してからlabel位置を
            # 再計算し、その位置を基準にend_rect(open_rect)を求める
            self.setGeometry(target_geo)
            end_rect = self._button_bar_open_rect()
        else:
            end_rect = closed_rect

        if self.button_bar.graphicsEffect() is None:
            self._button_bar_opacity_effect = QGraphicsOpacityEffect(self.button_bar)
            self.button_bar.setGraphicsEffect(self._button_bar_opacity_effect)
        opacity_effect = self.button_bar.graphicsEffect()

        self.button_bar.setGeometry(start_rect)
        self.button_bar.show()
        self.button_bar.raise_()

        geo_anim = QPropertyAnimation(self.button_bar, b"geometry", self)
        geo_anim.setDuration(MENU_ANIM_DURATION_MS)
        geo_anim.setStartValue(start_rect)
        geo_anim.setEndValue(end_rect)
        geo_anim.setEasingCurve(QEasingCurve.OutCubic if self._menu_open else QEasingCurve.InCubic)

        opacity_anim = QPropertyAnimation(opacity_effect, b"opacity", self)
        opacity_anim.setDuration(MENU_ANIM_DURATION_MS)
        opacity_anim.setStartValue(opacity_effect.opacity())
        opacity_anim.setEndValue(1.0 if self._menu_open else 0.0)
        opacity_anim.setEasingCurve(QEasingCurve.OutCubic if self._menu_open else QEasingCurve.InCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(geo_anim)
        group.addAnimation(opacity_anim)
        # 閉じる場合のみ、アニメーション完了後にウィンドウを縮小する
        # （開く場合は既に上でsetGeometry済みなのでtarget_geoの再適用は不要）
        if not self._menu_open:
            group.finished.connect(lambda: self.setGeometry(target_geo))
        group.finished.connect(self._on_menu_animation_finished)
        self._menu_animation_group = group
        group.start()

    def _on_menu_animation_finished(self) -> None:
        """メニュー開閉アニメーション終了時、後始末とグリップ再配置を行う。"""
        self._menu_animation_group = None
        if not self._menu_open:
            self.button_bar.hide()
        self._reposition_overlay_widgets()

    def _toggle_status_panel(self) -> None:
        """status_panelの開閉状態をアニメーション付きで切り替える（_toggle_menuと同じ仕組み）。

        button_barとは別のアニメーショングループ・開閉フラグで管理するため、
        両者は独立して開閉できる（同時にアニメーションしても互いの
        QPropertyAnimationは別オブジェクトなので干渉しない）。
        """
        self._raise_resize_grips()
        self._status_open = not self._status_open
        self._update_top_left_grip_design()
        target_panel_height = self._status_panel_open_height if self._status_open else 0

        current_geo = self.geometry()
        height_diff = target_panel_height - self.status_panel.maximumHeight()
        # status_panelはウィンドウ最上部にあるため、button_barと同じ「下端が伸びる」
        # 計算のままだと上端固定で下方向にせり出して見える。ペット画像やボタン列の
        # 位置は変えずに「下から上に」展開させたいので、高さが増える分だけy座標を
        # 上へ動かし、ウィンドウの下端を固定点として扱う。
        target_geo = QRect(
            current_geo.x(),
            current_geo.y() - height_diff,
            current_geo.width(),
            current_geo.height() + height_diff,
        )

        if self._status_animation_group is not None:
            self._status_animation_group.stop()

        panel_anim = QPropertyAnimation(self.status_panel, b"maximumHeight", self)
        panel_anim.setDuration(MENU_ANIM_DURATION_MS)
        panel_anim.setStartValue(self.status_panel.maximumHeight())
        panel_anim.setEndValue(target_panel_height)
        panel_anim.setEasingCurve(QEasingCurve.InOutCubic)

        geo_anim = QPropertyAnimation(self, b"geometry", self)
        geo_anim.setDuration(MENU_ANIM_DURATION_MS)
        geo_anim.setStartValue(current_geo)
        geo_anim.setEndValue(target_geo)
        geo_anim.setEasingCurve(QEasingCurve.InOutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(panel_anim)
        group.addAnimation(geo_anim)
        group.finished.connect(self._on_status_animation_finished)
        self._status_animation_group = group
        group.start()

    def _on_status_animation_finished(self) -> None:
        """status_panel開閉アニメーション終了時、サイズ制約の後始末とグリップ再配置を行う。"""
        self._status_animation_group = None
        self._reposition_overlay_widgets()

    # --- ボタンのクリックハンドラ（実処理はcontrollerに委譲） ---
    def _on_feed_clicked(self) -> None:
        if self._feeding_in_progress:
            # モーション再生中の連打は無視（ボタン無効化と二重の安全策）
            return
        self._start_feed_motion()

    def _on_pet_clicked(self) -> None:
        if self._petting_in_progress:
            return
        self._start_pet_motion()

    def _on_time_clicked(self) -> None:
        # ボタンの直下にサブメニューをポップアップ表示する
        menu = QMenu(self)
        for label, minutes in TIME_CONTROLS:
            menu.addAction(label, lambda minutes=minutes: self.controller.change_time(minutes))
        menu.exec(self.time_button.mapToGlobal(QPoint(0, self.time_button.height())))

    def _on_quit_clicked(self) -> None:
        self.controller.quit((self.pos().x(), self.pos().y()))

    # --- 会話機能 ---
    def _on_chat_send_clicked(self) -> None:
        text = self.chat_input.text().strip()
        if not text:
            return
        self.chat_send_button.setEnabled(False)
        self.chat_result_label.setText("考え中…")
        started = self.controller.submit_chat_message(
            text, self._on_chat_result, self._on_chat_error
        )
        if not started:
            self.chat_send_button.setEnabled(True)

    def _on_chat_result(self, entry: ChatHistoryEntry) -> None:
        self.chat_input.clear()
        self.chat_send_button.setEnabled(True)
        if entry.is_inappropriate:
            # AIが生成したナレーション文は表示せず、クライアント側で固定の注意文を
            # 赤字表示する（AIの出力をそのまま信頼しない方が安全なため）。
            self.chat_result_label.setText("不適切なワードが含まれているため，ペットには伝えませんでした")
            self.chat_result_label.setStyleSheet("color: rgba(255, 100, 100, 255); font-size: 12px;")
        else:
            self.chat_result_label.setText(entry.narration)
            self.chat_result_label.setStyleSheet("color: white; font-size: 12px;")
        self.refresh_appearance()  # mood変化を表情に反映
        if entry.mood_delta != 0.0:
            self._play_chat_score_animation(entry.mood_delta)

    def _play_chat_score_animation(self, mood_delta: float) -> None:
        """評価スコア(mood変化量)をchat_panel右上にふわっと表示する。

        符号付きの数値（例: +9.3 / -6.1）をフェードインしつつ少し上に浮かべ、
        最後にフェードアウトして消す（_play_full_heartと同じ演出パターン）。
        """
        sign = "+" if mood_delta >= 0 else ""
        self.chat_score_label.setText(f"{sign}{mood_delta:.1f}")
        self.chat_score_label.setStyleSheet(
            "color: rgba(255, 230, 120, 255); font-size: 14px; font-weight: bold;"
            " background: transparent;"
            if mood_delta >= 0
            else "color: rgba(255, 120, 120, 255); font-size: 14px; font-weight: bold;"
            " background: transparent;"
        )
        self.chat_score_label.adjustSize()

        start_x = self.chat_panel.width() - self.chat_score_label.width() - 10
        start_y = 6
        self.chat_score_label.move(start_x, start_y)
        opacity_effect = QGraphicsOpacityEffect(self.chat_score_label)
        self.chat_score_label.setGraphicsEffect(opacity_effect)
        self.chat_score_label.show()
        self.chat_score_label.raise_()

        pos_anim = QPropertyAnimation(self.chat_score_label, b"pos", self)
        pos_anim.setDuration(CHAT_SCORE_ANIM_DURATION_MS)
        pos_anim.setStartValue(QPoint(start_x, start_y))
        pos_anim.setEndValue(QPoint(start_x, start_y - 16))
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)

        opacity_anim = QPropertyAnimation(opacity_effect, b"opacity", self)
        opacity_anim.setDuration(CHAT_SCORE_ANIM_DURATION_MS)
        opacity_anim.setKeyValueAt(0.0, 0.0)
        opacity_anim.setKeyValueAt(0.2, 1.0)
        opacity_anim.setKeyValueAt(0.7, 1.0)
        opacity_anim.setKeyValueAt(1.0, 0.0)

        def on_finished() -> None:
            self.chat_score_label.hide()

        opacity_anim.finished.connect(on_finished)
        self._chat_score_anim_refs = (pos_anim, opacity_anim)  # GC防止
        pos_anim.start()
        opacity_anim.start()

    def _on_chat_error(self, kind: str, message: str) -> None:
        self.chat_send_button.setEnabled(True)
        display = {
            "no_api_key": "APIキーが設定されていません。",
            "busy": "前回の返信を待っています…",
            "network": "通信エラーが発生しました。ネットワークを確認してください。",
            "http": "APIからエラー応答がありました。しばらくしてから再試行してください。",
            "parse": "応答の解析に失敗しました。",
            "unknown": "予期しないエラーが発生しました。",
        }.get(kind, "エラーが発生しました。")
        self.chat_result_label.setText(display)

    # --- 見た目更新 ---
    def refresh_appearance(self) -> None:
        """ステータスに応じて表示画像を切り替える（hungry > angry > normal）。

        on_changeコールバック経由でステータス変化のたびに毎回呼ばれるため、
        表情が変わっていない場合は何もしない（アニメーションの二重起動・
        フレーム位置リセットによるチラつきを防ぐ）。
        """
        expression = self.state.current_expression()
        if expression == self._current_expression:
            self.refresh_status_bars()
            return
        self._current_expression = expression

        if expression in EXPRESSION_ANIM_FRAMES:
            anim_dir, anim_frames = EXPRESSION_ANIM_FRAMES[expression]
            self._normal_frame_index = 0
            self._normal_frame_direction = 1
            self._set_pixmap_from_path(anim_dir / anim_frames[0])
            # モーション側が一時停止/加速を制御している間は、ここでタイマーを
            # 起動しない（モーション終了時の意図したタイミングで再開させる）
            if not self._motion_controls_animation:
                self._normal_anim_timer.start()
        else:
            if not self._motion_controls_animation:
                self._normal_anim_timer.stop()
            self._set_pixmap_from_path(ASSETS_DIR / f"{expression}.png")

        if expression == "angry":
            self._start_angry_effect()
        else:
            self._stop_angry_effect()

        self.refresh_status_bars()

    def _set_pixmap_from_path(self, image_path: Path) -> None:
        pixmap = QPixmap(str(image_path))
        if not pixmap.isNull():
            self._current_image_path = image_path  # スケール変更時に元画像から再スケールするため記録
            pet_size = self._pet_size()
            # KeepAspectRatio + SmoothTransformationでもアルファチャンネルは保持される
            pixmap = pixmap.scaled(
                pet_size, pet_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.label.setPixmap(pixmap)

    def _advance_normal_frame(self) -> None:
        """現在の表情の往復(ピンポン)アニメーションを1フレーム進める。

        1→2→3→2→1→2→...のように端で折り返し、重複なく往復する。
        normal/angryで共通のフレーム送りロジックを使う
        （EXPRESSION_ANIM_FRAMESに表情ごとの画像フォルダ・フレーム一覧を定義）。
        """
        anim_dir, anim_frames = EXPRESSION_ANIM_FRAMES.get(
            self._current_expression, (NORMAL_ANIM_DIR, NORMAL_ANIM_FRAMES)
        )
        last_index = len(anim_frames) - 1
        self._normal_frame_index += self._normal_frame_direction
        if self._normal_frame_index >= last_index:
            self._normal_frame_index = last_index
            self._normal_frame_direction = -1
        elif self._normal_frame_index <= 0:
            self._normal_frame_index = 0
            self._normal_frame_direction = 1
        self._set_pixmap_from_path(anim_dir / anim_frames[self._normal_frame_index])

    # --- 怒りエフェクト（angry表情の間、ループ表示） ---
    # サイクル: 左下表示 →(TOP_RIGHT_DELAY)→ 右上も追加表示(左下は残る)
    # →(BOTTOM_LEFT_HIDE)→ 左下だけ消える →(TOP_RIGHT_HIDE)→ 右上も消えて休止
    # →(PAUSE)→ 最初から繰り返す
    def _start_angry_effect(self) -> None:
        """怒りエフェクトのループを開始する（既に開始済みなら何もしない）。"""
        if self._angry_effect_active:
            return
        self._angry_effect_active = True
        self._angry_cycle_show_bottom_left()

    def _stop_angry_effect(self) -> None:
        """怒りエフェクトのループを止め、表示中のアイコンを消す。

        _angry_effect_activeをFalseにすることで、進行中のsingleShotチェーンが
        予約済みでも次のステップで自分自身を停止する（タイマーを直接キャンセル
        する手段がQTimer.singleShotには無いため、フラグで止める方式にしている）。
        """
        self._angry_effect_active = False
        if self._angry_bottom_left_ref is not None:
            self._angry_bottom_left_ref.deleteLater()
            self._angry_bottom_left_ref = None
        if self._angry_top_right_ref is not None:
            self._angry_top_right_ref.deleteLater()
            self._angry_top_right_ref = None

    def _make_angry_icon(self, *, top_right: bool) -> QLabel:
        """怒りエフェクトの💢アイコンを1個生成して表示する（右上=中サイズ、左下=小サイズ）。"""
        pet_size = self._pet_size()
        icon_size = max(16, int((22 if top_right else 16) * self._scale))
        icon_font_px = max(11, int((19 if top_right else 14) * self._scale))
        if top_right:
            x = self.label.x() + int(pet_size * 0.68)
            y = self.label.y() + int(pet_size * 0.02)
        else:
            x = self.label.x() + int(pet_size * 0.28)
            y = self.label.y() + int(pet_size * 0.50)

        icon = QLabel(ANGRY_EFFECT_ICON, self)
        icon.setStyleSheet(f"font-size: {icon_font_px}px;")
        icon.setFixedSize(icon_size, icon_size)
        icon.move(x, y)
        icon.show()
        return icon

    def _angry_cycle_show_bottom_left(self) -> None:
        if not self._angry_effect_active:
            return
        self._angry_bottom_left_ref = self._make_angry_icon(top_right=False)
        QTimer.singleShot(ANGRY_EFFECT_TOP_RIGHT_DELAY_MS, self._angry_cycle_show_top_right)

    def _angry_cycle_show_top_right(self) -> None:
        if not self._angry_effect_active:
            return
        self._angry_top_right_ref = self._make_angry_icon(top_right=True)
        QTimer.singleShot(ANGRY_EFFECT_BOTTOM_LEFT_HIDE_MS, self._angry_cycle_hide_bottom_left)

    def _angry_cycle_hide_bottom_left(self) -> None:
        if not self._angry_effect_active:
            return
        if self._angry_bottom_left_ref is not None:
            self._angry_bottom_left_ref.deleteLater()
            self._angry_bottom_left_ref = None
        QTimer.singleShot(ANGRY_EFFECT_TOP_RIGHT_HIDE_MS, self._angry_cycle_hide_top_right)

    def _angry_cycle_hide_top_right(self) -> None:
        if not self._angry_effect_active:
            return
        if self._angry_top_right_ref is not None:
            self._angry_top_right_ref.deleteLater()
            self._angry_top_right_ref = None
        QTimer.singleShot(ANGRY_EFFECT_PAUSE_MS, self._angry_cycle_show_bottom_left)

    # --- モーション中の立ち絵アニメーション制御（餌やり/なでる共通） ---
    def _pause_normal_animation(self) -> None:
        """モーション開始時に通常アニメーションを停止し、以後の制御権をモーション側に渡す。

        表情変化によるrefresh_appearance側のタイマー起動/停止はこのフラグが
        立っている間は無視される（このメソッドと_resume_normal_animationの
        対になる呼び出しでのみタイマーを操作する）。
        """
        self._motion_controls_animation = True
        self._normal_anim_timer.stop()

    def _resume_normal_animation(self, interval_ms: int) -> None:
        """通常アニメーションを指定間隔で再開し、表情変化側への制御を返す。

        通常速度への復帰は常にスライダーの現在値を基準速度として使う
        （スライダー自体を「基準速度」とみなす設計）。
        """
        self._motion_controls_animation = False
        if self._current_expression in EXPRESSION_ANIM_FRAMES:
            self._normal_anim_timer.setInterval(interval_ms)
            self._normal_anim_timer.start()

    # --- 餌やりモーション ---
    def _set_buttons_enabled(self, enabled: bool) -> None:
        for button in self._all_buttons:
            button.setEnabled(enabled)

    def _start_feed_motion(self) -> None:
        """餌やりモーションを開始する。

        モーション中は全ボタンを無効化し、ステータス反映（controller.feed呼び出し）は
        モーション終了時にまとめて行う。これにより連打しても多重実行されない。
        """
        self._feeding_in_progress = True
        self._set_buttons_enabled(False)
        self._pause_normal_animation()  # カス散布中はフレーム固定表示にする

        # 既に満腹の場合は食べかすモーションを出さず、確定処理と演出のみ即座に行う
        # （controller.feed()を呼ぶ前にstateを直接見て判定する）
        if self.state.hunger >= 100:
            self.controller.feed()  # hunger>=100での呼び出しのためoverfed=True確定
            self._play_overfed_motion(on_complete=self._end_feed_motion)
            return

        # 口元あたり（画像中央よりやや下）を基準位置とする
        pet_size = self._pet_size()
        mouth_x = self.label.x() + pet_size // 2
        mouth_y = self.label.y() + int(pet_size * 0.6)

        # 餌アイコン（フェードイン→表示→フェードアウト）
        icon_size = max(20, int(36 * self._scale))
        icon_font_px = max(14, int(28 * self._scale))
        feed_icon = QLabel("🍖", self)
        feed_icon.setStyleSheet(f"font-size: {icon_font_px}px;")
        feed_icon.setFixedSize(icon_size, icon_size)
        feed_icon.setAlignment(Qt.AlignCenter)
        feed_icon.move(mouth_x - icon_size // 2, mouth_y - icon_size // 2)
        opacity_effect = QGraphicsOpacityEffect(feed_icon)
        feed_icon.setGraphicsEffect(opacity_effect)
        feed_icon.show()

        fade_anim = QPropertyAnimation(opacity_effect, b"opacity", self)
        fade_anim.setDuration(FEED_ICON_DURATION_MS)
        # フェードイン(0->1)→表示維持→フェードアウト(1->0)の3段構成をキーフレームで表現
        fade_anim.setKeyValueAt(0.0, 0.0)
        fade_anim.setKeyValueAt(0.25, 1.0)
        fade_anim.setKeyValueAt(0.75, 1.0)
        fade_anim.setKeyValueAt(1.0, 0.0)
        self._feed_icon_ref = feed_icon  # GC防止のため参照を保持

        # 食べかすパーティクル（口元中心に重ねて表示）
        particle_area = max(40, int(80 * self._scale))
        particle_widget = ParticleEffectWidget(
            self, make_crumb_config(self._scale), on_finished=lambda: None
        )
        particle_widget.setGeometry(
            QRect(mouth_x - particle_area // 2, mouth_y - particle_area // 2, particle_area, particle_area)
        )
        particle_widget.show()

        def on_motion_finished() -> None:
            feed_icon.deleteLater()
            # パーティクルは自身のタイマーで終了・deleteLateLater済みのため触らない
            self._finish_feed_motion()

        fade_anim.finished.connect(on_motion_finished)
        fade_anim.start()

    def _finish_feed_motion(self) -> None:
        """餌やりモーション終了時にステータス反映と後続演出を確定させる。

        ボタン再有効化・進行中フラグ解除は後続演出（ハート/シェイク）が
        完全に終わるタイミングまで持ち越す（on_completで渡す）。
        """
        overfed = self.controller.feed()
        if overfed:
            self._play_overfed_motion(on_complete=self._end_feed_motion)
        else:
            self._play_full_heart(on_complete=self._end_feed_motion)

    def _end_feed_motion(self) -> None:
        """餌やりモーション（演出含め）の完全終了時に進行中フラグとボタンを戻す。"""
        self._feeding_in_progress = False
        self._set_buttons_enabled(True)

    def _play_full_heart(self, on_complete: Callable[[], None] | None = None) -> None:
        """ハートが上に浮かびながらフワフワして消える演出（餌やり完食・なでる共通）。

        表示開始と同時にアニメーションを180msへ加速し、消滅と同時に
        通常速度（スライダーの基準値）へ戻す。on_completはハート消滅時に呼ばれる。
        """
        self._resume_normal_animation(HAPPY_ANIM_INTERVAL_MS)

        pet_size = self._pet_size()
        heart_size = max(14, int(24 * self._scale))
        heart_font_px = max(10, int(20 * self._scale))
        drift = max(4, int(6 * self._scale))  # 左右の揺れ幅
        rise = max(10, int(20 * self._scale))  # 1区間あたりの上昇量

        start_x = self.label.x() + pet_size // 2 - heart_size // 2
        start_y = self.label.y() + int(10 * self._scale)

        heart = QLabel("❤️", self)
        heart.setStyleSheet(f"font-size: {heart_font_px}px;")
        heart.setFixedSize(heart_size, heart_size)
        heart.move(start_x, start_y)
        opacity_effect = QGraphicsOpacityEffect(heart)
        heart.setGraphicsEffect(opacity_effect)
        heart.show()

        # 位置アニメーション: 上方向に移動しつつ左右にわずかに揺れる（フワフワ感）
        pos_anim = QPropertyAnimation(heart, b"pos", self)
        pos_anim.setDuration(HEART_DURATION_MS)
        pos_anim.setKeyValueAt(0.0, QPoint(start_x, start_y))
        pos_anim.setKeyValueAt(0.33, QPoint(start_x - drift, start_y - rise))
        pos_anim.setKeyValueAt(0.66, QPoint(start_x + drift, start_y - rise * 2))
        pos_anim.setKeyValueAt(1.0, QPoint(start_x, start_y - rise * 3))
        pos_anim.setEasingCurve(QEasingCurve.InOutSine)

        opacity_anim = QPropertyAnimation(opacity_effect, b"opacity", self)
        opacity_anim.setDuration(HEART_DURATION_MS)
        opacity_anim.setKeyValueAt(0.0, 1.0)
        opacity_anim.setKeyValueAt(0.7, 1.0)
        opacity_anim.setKeyValueAt(1.0, 0.0)

        def on_heart_finished() -> None:
            heart.deleteLater()
            self._resume_normal_animation(self.anim_speed_slider.value())
            if on_complete is not None:
                on_complete()

        self._heart_ref = heart  # GC防止
        opacity_anim.finished.connect(on_heart_finished)
        pos_anim.start()
        opacity_anim.start()

    def _play_overfed_motion(self, on_complete: Callable[[], None] | None = None) -> None:
        """あげすぎ時の「困る/嫌がる」モーション（絵文字表示＋画像の左右シェイク）。

        on_completはシェイク終了時に呼ばれる。
        """
        pet_size = self._pet_size()
        icon_size = max(18, int(28 * self._scale))
        icon_font_px = max(12, int(24 * self._scale))
        center_x = self.label.x() + pet_size // 2 - icon_size // 2
        top_y = self.label.y() - max(2, int(4 * self._scale))

        annoyed_icon = QLabel("💢", self)
        annoyed_icon.setStyleSheet(f"font-size: {icon_font_px}px;")
        annoyed_icon.setFixedSize(icon_size, icon_size)
        annoyed_icon.move(center_x, top_y)
        annoyed_icon.show()
        self._annoyed_icon_ref = annoyed_icon  # GC防止

        # 画像をX軸方向に小刻みに揺らすシェイク。
        # labelはQVBoxLayout管理下にあるため、QPropertyAnimationでposを直接動かすと
        # レイアウト再計算時に競合するおそれがある。そのためQTimerで手動に
        # インデント(左マージン)を切り替え、見た目上の左右シェイクを表現する。
        offsets = [int(v * self._scale) for v in (-8, 8, -6, 6, -3, 3, 0)]  # 振幅をスケールに比例させる
        step_ms = max(1, SHAKE_DURATION_MS // len(offsets))

        def shake_step(index: int = 0) -> None:
            if index >= len(offsets):
                self.label.setContentsMargins(0, 0, 0, 0)
                annoyed_icon.deleteLater()
                # あげすぎ時はハートが出ないため180ms加速は行わず、
                # シェイク終了で通常速度のまま再開する
                self._resume_normal_animation(self.anim_speed_slider.value())
                if on_complete is not None:
                    on_complete()
                return
            dx = offsets[index]
            left = max(0, dx)
            right = max(0, -dx)
            self.label.setContentsMargins(left, 0, right, 0)
            QTimer.singleShot(step_ms, lambda: shake_step(index + 1))

        shake_step()

    # --- なでるモーション ---
    def _end_pet_motion(self) -> None:
        """なでるモーション（ハート演出含め）の完全終了時に進行中フラグとボタンを戻す。"""
        self._petting_in_progress = False
        self._set_buttons_enabled(True)

    def _start_pet_motion(self) -> None:
        """なでるモーションを開始する。

        ステータス反映（機嫌上昇）は演出が短いこともあり、餌やりのように
        「終了まで確定を待つ」厳密さは求めず、開始と同時にcontroller.pet()を
        確定させる（実装の単純さを優先）。
        """
        self._petting_in_progress = True
        self._set_buttons_enabled(False)
        self._pause_normal_animation()  # バウンド＋キラキラ中はフレーム固定表示にする
        self.controller.pet()

        # 画像をY軸方向に軽くバウンドさせる。
        # labelはQVBoxLayout管理下のため、posを直接動かすとレイアウト再計算と
        # 競合するおそれがある（あげすぎシェイクと同じ理由）。
        # そのためcontentsMarginsの上下を切り替えて見た目上の上下バウンドを表現する。
        offsets = [int(v * self._scale) for v in (-10, -16, -8, -2, 0)]  # 振幅をスケールに比例させる
        step_ms = max(1, PET_BOUNCE_DURATION_MS // len(offsets))

        def bounce_step(index: int = 0) -> None:
            if index >= len(offsets):
                self.label.setContentsMargins(0, 0, 0, 0)
                # ボタン再有効化・フラグ解除はハート消滅時まで持ち越す
                # バウンド終了後にハート演出（表示開始で180msへ加速、消滅で通常速度に復帰）
                self._play_full_heart(on_complete=self._end_pet_motion)
                return
            dy = offsets[index]
            top = max(0, -dy)
            bottom = max(0, dy)
            self.label.setContentsMargins(0, top, 0, bottom)
            QTimer.singleShot(step_ms, lambda: bounce_step(index + 1))

        bounce_step()

        # キラキラパーティクル（画像中央を起点に周囲へ浮かび上がらせる）
        pet_size = self._pet_size()
        center_x = self.label.x() + pet_size // 2
        center_y = self.label.y() + pet_size // 2
        sparkle_area = max(60, int(120 * self._scale))
        sparkle_widget = ParticleEffectWidget(
            self, make_sparkle_config(self._scale), on_finished=lambda: None
        )
        sparkle_widget.setGeometry(
            QRect(center_x - sparkle_area // 2, center_y - sparkle_area // 2, sparkle_area, sparkle_area)
        )
        sparkle_widget.show()

    # --- リサイズ処理（_ResizeGripから呼ばれる） ---
    def begin_resize(self, global_pos: QPoint, corner: str) -> None:
        # メニュー(button_bar)が開いたままリサイズすると、QVBoxLayoutの余白配分の
        # 影響でlabel位置がズレ、button_barの絶対配置と整合が取れなくなる。
        # そのため、リサイズ開始時にメニューが開いていれば即座に（アニメーション
        # なしで）閉じる。
        if self._menu_open:
            self._close_menu_immediately()
        self._resizing = True
        self._resize_start_pos = global_pos
        self._resize_start_scale = self._scale
        self._resize_corner = corner
        # ドラッグする角と対角にあたる「固定点」の画面座標を記録する。
        # リサイズ中はこの点が画面上で動かないよう、サイズ変化に合わせて
        # ウィンドウ位置を調整する（例: 左上角をドラッグする場合は右下を固定する）。
        geo = self.geometry()
        anchor_by_corner = {
            "bottom_right": geo.topLeft(),
            "top_left": geo.bottomRight(),
            "top_right": geo.bottomLeft(),
            "bottom_left": geo.topRight(),
        }
        self._resize_anchor = anchor_by_corner[corner]

    def update_resize(self, global_pos: QPoint) -> None:
        if not self._resizing or self._resize_start_pos is None or self._resize_corner is None:
            return
        delta = global_pos - self._resize_start_pos
        # 角によって「外側に広げる」ドラッグ方向が異なるため、
        # 左上系の角では符号を反転してから拡大/縮小量を揃える。
        sign_x = 1 if self._resize_corner in ("bottom_right", "top_right") else -1
        sign_y = 1 if self._resize_corner in ("bottom_right", "bottom_left") else -1
        dx = delta.x() * sign_x
        dy = delta.y() * sign_y
        # 対角線方向のドラッグ量が大きい方の軸を基準にスケールを決める
        # （アスペクト比を保つため、幅・高さに同じ係数を掛ける）
        diff = dx if abs(dx) >= abs(dy) else dy
        scale_delta = diff / PET_SIZE
        self._apply_scale(self._resize_start_scale + scale_delta)
        self._reposition_after_resize()

    def _reposition_after_resize(self) -> None:
        """リサイズ中、ドラッグしていない対角の角が画面上で固定されるようウィンドウ位置を調整する。"""
        w, h = self.width(), self.height()
        anchor = self._resize_anchor
        if self._resize_corner == "bottom_right":
            new_pos = anchor  # 左上が固定点そのものなので位置は変わらない
        elif self._resize_corner == "top_left":
            new_pos = QPoint(anchor.x() - w, anchor.y() - h)
        elif self._resize_corner == "top_right":
            new_pos = QPoint(anchor.x(), anchor.y() - h)
        else:  # bottom_left
            new_pos = QPoint(anchor.x() - w, anchor.y())
        self.move(new_pos)
        # move()の前にグリップ位置を計算すると、ウィンドウ位置確定前の状態を
        # 基準にしてしまいズレることがあったため、move()の後に再配置する。
        self._reposition_overlay_widgets()

    def _reposition_overlay_widgets(self) -> None:
        """リサイズグリップ・メニュー/ステータストグルボタンを現在のウィンドウサイズに追従させる。"""
        w, h = self.width(), self.height()
        grip_positions = {
            "top_left": (0, 0),
            "top_right": (w - RESIZE_GRIP_SIZE, 0),
        }
        for corner, (gx, gy) in grip_positions.items():
            grip = self._resize_grips[corner]
            grip.move(gx, gy)
            grip.raise_()
        self._reposition_toggle_buttons()

    def _reposition_toggle_buttons(self) -> None:
        """state.toggle_button_orderの並び順に従い、トグルボタンを縦積みで配置する。

        リスト先頭(index 0)が最下段（ペット画像に最も近い）、末尾が最上段になる。
        ドラッグ中はドラッグ元のボタンだけ座標計算から除外する
        （カーソル追従させるため、この後update_toggle_button_dragが別途動かす）。
        """
        size = self._toggle_button_size()
        pet_right = self.label.x() + self.label.width()
        pet_bottom = self.label.y() + self.label.height()
        order = self.state.toggle_button_order
        for index, button_id in enumerate(order):
            button = self._toggle_button_by_id.get(button_id)
            if button is None or button_id == self._drag_button_id:
                continue
            button.move(
                pet_right - size - 4,
                pet_bottom - size - 4 - (size + 4) * index,
            )
            button.raise_()

    def _toggle_button_stack_rect_for_index(self, index: int) -> QRect:
        """縦積みのindex段目が占めるウィンドウ内矩形を返す（ドロップ判定・インジケータ表示用）。"""
        size = self._toggle_button_size()
        pet_right = self.label.x() + self.label.width()
        pet_bottom = self.label.y() + self.label.height()
        y = pet_bottom - size - 4 - (size + 4) * index
        return QRect(pet_right - size - 4, y, size, size)

    def begin_toggle_button_drag(self, button_id: str) -> None:
        """トグルボタンの並び替えドラッグを開始する（_DraggableToggleButtonから呼ばれる）。

        ドラッグ元ボタンを半透明にして「つかんでいる」状態を視覚的に示し、
        以後はupdate_toggle_button_dragがカーソルに追従させる。
        """
        self._drag_button_id = button_id
        button = self._toggle_button_by_id[button_id]
        opacity_effect = QGraphicsOpacityEffect(button)
        opacity_effect.setOpacity(0.45)
        button.setGraphicsEffect(opacity_effect)
        button.raise_()
        self._drop_indicator.setFixedSize(self._toggle_button_size(), 3)
        self._drop_indicator.show()
        self._drop_indicator.raise_()

    def update_toggle_button_drag(self, global_pos: QPoint) -> None:
        """ドラッグ中、カーソル位置にボタン本体を追従させ、挿入先インデックスを再計算する。"""
        if self._drag_button_id is None:
            return
        button = self._toggle_button_by_id[self._drag_button_id]
        size = self._toggle_button_size()
        local_pos = self.mapFromGlobal(global_pos)
        button.move(local_pos.x() - size // 2, local_pos.y() - size // 2)
        button.raise_()

        order = self.state.toggle_button_order
        drop_index = self._compute_drop_index(local_pos.y(), order)
        self._drag_drop_index = drop_index
        indicator_rect = self._toggle_button_stack_rect_for_index(drop_index)
        # 横線は段の下端（次の段との境目）に表示し、「ここに挟まる」ことを示す
        self._drop_indicator.move(indicator_rect.x(), indicator_rect.y() - 2)
        self._drop_indicator.raise_()

    def _compute_drop_index(self, cursor_y: int, order: list[str]) -> int:
        """カーソルのy座標から、最も近い段境界のインデックスを返す。

        ドラッグ元自身を除いた並びの中で、各段の中心y座標とカーソルを比較し、
        最も近い段の位置（0〜len(order)-1、ドラッグ元を除いた個数基準）を返す。
        """
        remaining = [bid for bid in order if bid != self._drag_button_id]
        if not remaining:
            return 0
        size = self._toggle_button_size()
        pet_bottom = self.label.y() + self.label.height()
        best_index = 0
        best_distance = None
        for index in range(len(remaining)):
            center_y = pet_bottom - size - 4 - (size + 4) * index + size // 2
            distance = abs(cursor_y - center_y)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = index
        return best_index

    def end_toggle_button_drag(self) -> None:
        """ドラッグを確定し、並び順を更新・保存して配置し直す。"""
        if self._drag_button_id is None:
            return
        button_id = self._drag_button_id
        drop_index = self._drag_drop_index
        button = self._toggle_button_by_id[button_id]
        button.setGraphicsEffect(None)
        self._drop_indicator.hide()
        self._drag_button_id = None
        self._drag_drop_index = -1

        order = [bid for bid in self.state.toggle_button_order if bid != button_id]
        drop_index = max(0, min(drop_index, len(order)))
        order.insert(drop_index, button_id)
        self.state.toggle_button_order = order
        self.state.save()
        self._reposition_toggle_buttons()

    def end_resize(self) -> None:
        self._resizing = False
        self._resize_start_pos = None
        self._resize_corner = None

    def showEvent(self, event: QShowEvent) -> None:
        """ウィンドウが実際に画面へ表示された直後、メニュートグルボタンを再配置する。

        __init__時点ではウィンドウがまだ表示されておらずレイアウトが未確定のため、
        labelのx()/y()が正しい値を返さず、ボタンが見えない位置に置かれてしまう。
        showEventはレイアウト確定後に発生するため、ここで再配置すれば確実に直る。
        """
        super().showEvent(event)
        self._reposition_overlay_widgets()

    # --- マウス操作: クリックでなでる / ドラッグで移動 ---
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            # ドラッグ移動が無かった（ほぼ同じ位置でのリリース）場合のみ「なでる」反応にする
            moved = self._drag_offset is not None and (
                event.globalPosition().toPoint() - (self.pos() + self._drag_offset)
            ).manhattanLength() > 3
            self._drag_offset = None
            if not moved and not self._petting_in_progress:
                self._start_pet_motion()
            # 位置が変わった場合は保存用に反映
            self.state.window_position = [self.pos().x(), self.pos().y()]
