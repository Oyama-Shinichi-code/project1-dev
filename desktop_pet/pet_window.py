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

from pathlib import Path
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPaintEvent, QPen, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.controller import TIME_CONTROLS, PetController
from desktop_pet.effects import ParticleEffectWidget, make_crumb_config, make_sparkle_config

ASSETS_DIR = Path(__file__).parent / "assets" / "pet"
NORMAL_ANIM_DIR = ASSETS_DIR / "normal"
NORMAL_ANIM_FRAMES = ["normal_flame1.png", "normal_flame2.png", "normal_flame3.png"]
NORMAL_ANIM_INTERVAL_MS = 400  # フレーム切り替え間隔(ms)
PET_SIZE = 200  # 表示サイズ（元画像は512x512なので縮小表示）
BUTTON_SIZE = 36  # ボタン列の1つあたりのサイズ(px)

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

        self._build_status_bars()
        self._build_anim_speed_panel()
        self._build_button_bar()
        self._build_menu_toggle_button()
        self._build_status_toggle_button()
        self._build_grip_design_toggle_button()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.status_panel)
        layout.addWidget(self.anim_speed_panel)
        layout.addWidget(self.label)
        layout.addWidget(self.button_bar)

        # メニュー・ステータスパネルは初期状態で閉じておく（maximumHeight=0で高さ0に折りたたむ）
        self.button_bar.setMaximumHeight(0)
        self.status_panel.setMaximumHeight(0)

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
        self.menu_toggle_button.show()
        self.menu_toggle_button.raise_()
        self.status_toggle_button.show()
        self.status_toggle_button.raise_()
        self.grip_design_toggle_button.show()
        self.grip_design_toggle_button.raise_()

        # 速度確認作業は完了したため非表示化（ロジック・スライダー自体は残す）
        self.anim_speed_panel.setVisible(False)

        x, y = self.state.window_position
        self.move(x, y)

        self.refresh_appearance()
        self.refresh_status_bars()
        self._apply_scale(1.0)  # 各ウィジェットのサイズ・フォントを基準スケールで確定させる

    # --- スケール管理 ---
    def _pet_size(self) -> int:
        """現在のスケールを反映したペット画像の表示サイズ(px)。"""
        return int(PET_SIZE * self._scale)

    def _button_size(self) -> int:
        return int(BUTTON_SIZE * self._scale)

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
        # 折りたたみメニューの高さはボタンサイズに応じて変わるため、
        # 開いている時はスケールに応じた新しい高さに更新する。
        # 閉じている時はmaximumHeight=0を維持し（折りたたみ状態を壊さない）、
        # 「必要な高さ」だけを_menu_open_height()用に記録しておく。
        self._button_bar_open_height = self.button_bar.sizeHint().height()
        if self._menu_open:
            self.button_bar.setMaximumHeight(self._button_bar_open_height)

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
        # ウィンドウサイズが確定した後、グリップ・トグルボタン類を追従させる
        self._reposition_overlay_widgets()

    # --- ステータスゲージの構築 ---
    def _build_status_bars(self) -> None:
        """満腹度/機嫌/体力を小さいQProgressBarで常時表示するパネル。"""
        self.status_panel = QWidget(self)
        self.status_panel.setStyleSheet(
            "background-color: rgba(0, 0, 0, 110); border-radius: 8px;"
        )
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

        self.quit_button = QPushButton("❌", self.button_bar)
        self.quit_button.setToolTip("終了")
        self.quit_button.clicked.connect(self._on_quit_clicked)

        self._all_buttons = (
            self.feed_button,
            self.pet_button,
            self.time_button,
            self.quit_button,
        )
        for button in self._all_buttons:
            button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            button.setStyleSheet(button_style)
            bar_layout.addWidget(button)

    # --- メニュートグルボタンの構築・開閉制御 ---
    def _build_menu_toggle_button(self) -> None:
        """常時表示する小さな開閉ボタン（☰）。クリックでbutton_barの開閉をトグルする。"""
        self.menu_toggle_button = QPushButton("☰", self)
        self.menu_toggle_button.setToolTip("メニュー")
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
        self.status_toggle_button = QPushButton("📊", self)
        self.status_toggle_button.setToolTip("ステータス")
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

    def _reposition_menu_toggle_button(self) -> None:
        """メニュートグルボタンをペット画像(label)の右下隅を基準に配置する。

        以前はウィンドウ全体の右下を基準にしていたため、メニュー開閉で
        ウィンドウの高さが変わるとボタン列の位置まで降りてきてしまい、
        さらにgeometryアニメーション中は再配置されず古い位置に取り残されていた。
        labelの位置・サイズはメニュー開閉の影響を受けないため、これを基準にすれば
        どちらの問題も解消する（アニメーション中も追従処理が不要になる）。
        """
        pet_right = self.label.x() + self.label.width()
        pet_bottom = self.label.y() + self.label.height()
        self.menu_toggle_button.move(
            pet_right - MENU_TOGGLE_SIZE - 4, pet_bottom - MENU_TOGGLE_SIZE - 4
        )
        self.menu_toggle_button.raise_()

    def _reposition_status_toggle_button(self) -> None:
        """ステータストグルボタンをmenu_toggle_buttonの真上に縦積みで配置する。

        今後ボタンが増える方針のため、右下を起点にy座標をMENU_TOGGLE_SIZE+4ずつ
        積み上げていく想定（このボタンはmenu_toggle_buttonの1段上）。
        """
        pet_right = self.label.x() + self.label.width()
        pet_bottom = self.label.y() + self.label.height()
        self.status_toggle_button.move(
            pet_right - MENU_TOGGLE_SIZE - 4,
            pet_bottom - MENU_TOGGLE_SIZE - 4 - (MENU_TOGGLE_SIZE + 4),
        )
        self.status_toggle_button.raise_()

    def _build_grip_design_toggle_button(self) -> None:
        """リサイズグリップのL字デザインの表示/非表示を切り替えるボタン（👁）。

        OFFにしてもリサイズ機能自体（クリック判定）は常に動作する。
        見た目はmenu_toggle_button/status_toggle_buttonと統一し、縦積みの3段目に置く。
        """
        self.grip_design_toggle_button = QPushButton("👁", self)
        self.grip_design_toggle_button.setToolTip("リサイズハンドルの表示切り替え")
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

    def _reposition_grip_design_toggle_button(self) -> None:
        """グリップデザイン切り替えボタンをstatus_toggle_buttonのさらに1段上に配置する。"""
        pet_right = self.label.x() + self.label.width()
        pet_bottom = self.label.y() + self.label.height()
        self.grip_design_toggle_button.move(
            pet_right - MENU_TOGGLE_SIZE - 4,
            pet_bottom - MENU_TOGGLE_SIZE - 4 - (MENU_TOGGLE_SIZE + 4) * 2,
        )
        self.grip_design_toggle_button.raise_()

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

    def _raise_resize_grips(self) -> None:
        """リサイズグリップを最前面に上げ直す。

        status_panel/button_barの開閉アニメーションに伴うレイアウト再計算で、
        グリップが他のウィジェットの下に隠れてクリックを受け付けなくなることが
        あったため、開閉操作のたびに明示的に呼び直して確実に最前面を維持する。
        """
        for grip in self._resize_grips.values():
            grip.raise_()

    def _toggle_menu(self) -> None:
        """button_barの開閉状態をアニメーション付きで切り替える。

        開閉中にbutton_barの高さとウィンドウ全体の高さを同時にアニメーションさせるため、
        QParallelAnimationGroupで2本のQPropertyAnimationを束ねて実行する。
        """
        self._raise_resize_grips()
        self._menu_open = not self._menu_open
        target_bar_height = self._button_bar_open_height if self._menu_open else 0

        current_geo = self.geometry()
        height_diff = target_bar_height - self.button_bar.maximumHeight()
        target_geo = QRect(current_geo.x(), current_geo.y(), current_geo.width(), current_geo.height() + height_diff)

        # 既存のアニメーションが進行中なら打ち切ってから新しいものを開始する
        # （連打された場合に古いアニメーションの終了処理と競合しないようにする）
        if self._menu_animation_group is not None:
            self._menu_animation_group.stop()

        bar_anim = QPropertyAnimation(self.button_bar, b"maximumHeight", self)
        bar_anim.setDuration(MENU_ANIM_DURATION_MS)
        bar_anim.setStartValue(self.button_bar.maximumHeight())
        bar_anim.setEndValue(target_bar_height)
        bar_anim.setEasingCurve(QEasingCurve.InOutCubic)

        geo_anim = QPropertyAnimation(self, b"geometry", self)
        geo_anim.setDuration(MENU_ANIM_DURATION_MS)
        geo_anim.setStartValue(current_geo)
        geo_anim.setEndValue(target_geo)
        geo_anim.setEasingCurve(QEasingCurve.InOutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(bar_anim)
        group.addAnimation(geo_anim)
        group.finished.connect(self._on_menu_animation_finished)
        self._menu_animation_group = group
        group.start()

    def _on_menu_animation_finished(self) -> None:
        """メニュー開閉アニメーション終了時、サイズ制約の後始末とグリップ再配置を行う。

        geometryアニメーション中はsetMaximumSizeの制約を外していないため、
        adjustSize()は使わずジオメトリをそのまま確定値とする。グリップ・
        トグルボタンの位置だけ最新のウィンドウサイズに追従させる。
        """
        self._menu_animation_group = None
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

        if expression == "normal":
            self._normal_frame_index = 0
            self._normal_frame_direction = 1
            self._set_pixmap_from_path(NORMAL_ANIM_DIR / NORMAL_ANIM_FRAMES[0])
            # モーション側が一時停止/加速を制御している間は、ここでタイマーを
            # 起動しない（モーション終了時の意図したタイミングで再開させる）
            if not self._motion_controls_animation:
                self._normal_anim_timer.start()
        else:
            if not self._motion_controls_animation:
                self._normal_anim_timer.stop()
            self._set_pixmap_from_path(ASSETS_DIR / f"{expression}.png")
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
        """通常状態の往復(ピンポン)アニメーションを1フレーム進める。

        1→2→3→2→1→2→...のように端で折り返し、重複なく往復する。
        """
        last_index = len(NORMAL_ANIM_FRAMES) - 1
        self._normal_frame_index += self._normal_frame_direction
        if self._normal_frame_index >= last_index:
            self._normal_frame_index = last_index
            self._normal_frame_direction = -1
        elif self._normal_frame_index <= 0:
            self._normal_frame_index = 0
            self._normal_frame_direction = 1
        self._set_pixmap_from_path(NORMAL_ANIM_DIR / NORMAL_ANIM_FRAMES[self._normal_frame_index])

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
        if self._current_expression == "normal":
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
        self._reposition_menu_toggle_button()
        self._reposition_status_toggle_button()
        self._reposition_grip_design_toggle_button()

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
