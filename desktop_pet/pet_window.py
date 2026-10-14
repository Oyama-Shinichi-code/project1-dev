"""常駐の透過ウィンドウ（ペット本体表示）。

- フレームレス・最前面・背景透過
- クリックでなでるアクション
- ドラッグで移動
- 画像下のボタン列（餌やり/なでる/時間操作/終了）
- ステータスゲージ（満腹度/機嫌/体力）
- 餌やりモーション（餌アイコン表示＋食べかすパーティクル＋完食ハート/あげすぎシェイク）
- なでるモーション（画像バウンド＋キラキラパーティクル）
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QMouseEvent, QPixmap
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


class PetWindow(QWidget):
    def __init__(self, controller: PetController) -> None:
        super().__init__()
        self.controller = controller
        self.state = controller.state
        self._drag_offset: QPoint | None = None
        self._feeding_in_progress = False  # 餌やりモーション中の多重実行防止フラグ
        self._petting_in_progress = False  # なでるモーション中の多重実行防止フラグ
        self._current_expression: str | None = None  # 直前に表示した表情（再起動判定用）
        self._normal_frame_index = 0
        self._normal_frame_direction = 1  # 往復(ピンポン)の進行方向: +1 or -1
        # モーション（餌やり/なでる）がアニメーションの一時停止・加速を制御している間は
        # refresh_appearance側の表情変化によるタイマー起動/停止を無視する。
        # これにより「カス散布中に満腹度が変わって表情が切り替わる」等のケースでも
        # モーション側の制御（停止させたい/加速させたい）が優先され、意図しない
        # タイマー再起動（速度リセットや二重起動）が起きない。
        self._motion_controls_animation = False

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.status_panel)
        layout.addWidget(self.anim_speed_panel)
        layout.addWidget(self.label)
        layout.addWidget(self.button_bar)

        # 速度確認作業は完了したため非表示化（ロジック・スライダー自体は残す）
        self.anim_speed_panel.setVisible(False)

        x, y = self.state.window_position
        self.move(x, y)

        self.refresh_appearance()
        self.refresh_status_bars()

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
            # KeepAspectRatio + SmoothTransformationでもアルファチャンネルは保持される
            pixmap = pixmap.scaled(
                PET_SIZE, PET_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
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
        mouth_x = self.label.x() + PET_SIZE // 2
        mouth_y = self.label.y() + int(PET_SIZE * 0.6)

        # 餌アイコン（フェードイン→表示→フェードアウト）
        feed_icon = QLabel("🍖", self)
        feed_icon.setStyleSheet("font-size: 28px;")
        feed_icon.setFixedSize(36, 36)
        feed_icon.setAlignment(Qt.AlignCenter)
        feed_icon.move(mouth_x - 18, mouth_y - 18)
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
        particle_widget = ParticleEffectWidget(self, make_crumb_config(), on_finished=lambda: None)
        particle_widget.setGeometry(QRect(mouth_x - 40, mouth_y - 40, 80, 80))
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

        start_x = self.label.x() + PET_SIZE // 2 - 12
        start_y = self.label.y() + 10

        heart = QLabel("❤️", self)
        heart.setStyleSheet("font-size: 20px;")
        heart.setFixedSize(24, 24)
        heart.move(start_x, start_y)
        opacity_effect = QGraphicsOpacityEffect(heart)
        heart.setGraphicsEffect(opacity_effect)
        heart.show()

        # 位置アニメーション: 上方向に移動しつつ左右にわずかに揺れる（フワフワ感）
        pos_anim = QPropertyAnimation(heart, b"pos", self)
        pos_anim.setDuration(HEART_DURATION_MS)
        pos_anim.setKeyValueAt(0.0, QPoint(start_x, start_y))
        pos_anim.setKeyValueAt(0.33, QPoint(start_x - 6, start_y - 20))
        pos_anim.setKeyValueAt(0.66, QPoint(start_x + 6, start_y - 40))
        pos_anim.setKeyValueAt(1.0, QPoint(start_x, start_y - 60))
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
        center_x = self.label.x() + PET_SIZE // 2 - 14
        top_y = self.label.y() - 4

        annoyed_icon = QLabel("💢", self)
        annoyed_icon.setStyleSheet("font-size: 24px;")
        annoyed_icon.setFixedSize(28, 28)
        annoyed_icon.move(center_x, top_y)
        annoyed_icon.show()
        self._annoyed_icon_ref = annoyed_icon  # GC防止

        # 画像をX軸方向に小刻みに揺らすシェイク。
        # labelはQVBoxLayout管理下にあるため、QPropertyAnimationでposを直接動かすと
        # レイアウト再計算時に競合するおそれがある。そのためQTimerで手動に
        # インデント(左マージン)を切り替え、見た目上の左右シェイクを表現する。
        offsets = [-8, 8, -6, 6, -3, 3, 0]
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
        offsets = [-10, -16, -8, -2, 0]
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
        center_x = self.label.x() + PET_SIZE // 2
        center_y = self.label.y() + PET_SIZE // 2
        sparkle_widget = ParticleEffectWidget(self, make_sparkle_config(), on_finished=lambda: None)
        sparkle_widget.setGeometry(QRect(center_x - 60, center_y - 60, 120, 120))
        sparkle_widget.show()

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
