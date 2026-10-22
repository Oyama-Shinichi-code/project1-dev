"""モーション用の自作パーティクルエフェクト。

絵文字(QLabel)だけでは表現できない「粒が飛び散る/浮かび上がる」演出を
QPainterでの図形描画 + QTimerでの座標更新により実現する。

餌やりの「食べかす」となでるの「キラキラ」は見た目（色・形・動き・寿命）が異なるだけで
仕組みは共通のため、ParticleEffectConfigでパラメータ化した単一クラスで両方に対応する。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QWidget

# 食べかすらしい茶色系の色のバリエーション
CRUMB_COLORS = [
    QColor(139, 90, 43),
    QColor(160, 110, 60),
    QColor(120, 75, 35),
]

# キラキラらしい黄色系の色のバリエーション（旧仕様。現在は未使用だが念のため残置）
SPARKLE_COLORS = [
    QColor(255, 215, 0),
    QColor(255, 235, 120),
    QColor(255, 193, 7),
]

# 光の粒らしい白〜淡い水色系の色のバリエーション
GLOW_COLORS = [
    QColor(255, 255, 255),
    QColor(235, 245, 255),
    QColor(210, 235, 255),
]


@dataclass
class ParticleEffectConfig:
    """パーティクル演出の見た目・動きを決めるパラメータ一式。"""

    colors: list[QColor]
    count_range: tuple[int, int] = (5, 8)
    lifetime_ms: int = 1000
    interval_ms: int = 30
    speed_range: tuple[float, float] = (0.6, 1.8)
    size_range: tuple[float, float] = (3, 6)
    gravity: float = 0.05  # 下方向への加速（キラキラは0や負の値で「浮かび上がる」動きにできる）
    shape: str = "mixed"  # "mixed"(三角/円) or "star"(キラキラ用の星型)


class _Particle:
    """1粒の状態（位置・速度・形・色）を保持する。"""

    def __init__(self, config: ParticleEffectConfig) -> None:
        angle = random.uniform(0, 360)
        speed = random.uniform(*config.speed_range)
        self.dx = math.cos(math.radians(angle)) * speed
        self.dy = math.sin(math.radians(angle)) * speed
        self.x = 0.0
        self.y = 0.0
        self.size = random.uniform(*config.size_range)
        self.is_triangle = random.random() < 0.5
        self.color = random.choice(config.colors)
        self.gravity = config.gravity

    def step(self) -> None:
        self.x += self.dx
        self.y += self.dy
        self.dy += self.gravity


class ParticleEffectWidget(QWidget):
    """起点座標を中心に、粒を周囲へ飛び散らせる/浮かび上がらせる透明オーバーレイ。

    呼び出し側が位置・サイズを合わせて配置し、再生終了は on_finished で通知する。
    """

    def __init__(self, parent: QWidget, config: ParticleEffectConfig, on_finished) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._config = config
        self._on_finished = on_finished
        self._particles = [
            _Particle(config) for _ in range(random.randint(*config.count_range))
        ]
        self._elapsed_ms = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(config.interval_ms)

    def _tick(self) -> None:
        self._elapsed_ms += self._config.interval_ms
        for particle in self._particles:
            particle.step()
        self.update()
        if self._elapsed_ms >= self._config.lifetime_ms:
            # 自分で後始末する: タイマー停止→終了通知→自身の破棄予約（リーク防止）
            self._timer.stop()
            self._on_finished()
            self.deleteLater()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        progress = min(1.0, self._elapsed_ms / self._config.lifetime_ms)
        center_x = self.width() / 2
        center_y = self.height() / 2
        for particle in self._particles:
            color = QColor(particle.color)
            color.setAlphaF(max(0.0, 1.0 - progress))
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            px = center_x + particle.x
            py = center_y + particle.y
            size = particle.size
            if self._config.shape == "glow":
                # 加算合成で重なり合う粒が発光しているように明るく見せる
                painter.setCompositionMode(QPainter.CompositionMode_Plus)
                _draw_glow(painter, px, py, size, color)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            elif self._config.shape == "star":
                painter.drawPolygon(_star_polygon(px, py, size))
            elif particle.is_triangle:
                triangle = QPolygonF(
                    [
                        QPointF(px, py - size),
                        QPointF(px - size, py + size),
                        QPointF(px + size, py + size),
                    ]
                )
                painter.drawPolygon(triangle)
            else:
                painter.drawEllipse(int(px - size / 2), int(py - size / 2), int(size), int(size))
        painter.end()


def _draw_glow(painter: QPainter, cx: float, cy: float, size: float, color: QColor) -> None:
    """中心が明るく外側へじんわり滲む円形の光を描く（放射グラデーション）。"""
    radius = size * 2.2  # グラデーションの滲み分、粒のサイズより大きく広げる
    gradient = QRadialGradient(cx, cy, radius)
    center_color = QColor(color)
    gradient.setColorAt(0.0, center_color)
    mid_color = QColor(color)
    mid_color.setAlphaF(center_color.alphaF() * 0.4)
    gradient.setColorAt(0.4, mid_color)
    edge_color = QColor(color)
    edge_color.setAlphaF(0.0)
    gradient.setColorAt(1.0, edge_color)
    painter.setBrush(gradient)
    painter.drawEllipse(QPointF(cx, cy), radius, radius)


def _star_polygon(cx: float, cy: float, size: float) -> QPolygonF:
    """キラキラ表現用の四方星（菱形を十字に重ねた形）を作る。"""
    points = []
    for i in range(8):
        angle = math.radians(i * 45)
        radius = size if i % 2 == 0 else size * 0.4
        points.append(QPointF(cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return QPolygonF(points)


def make_crumb_config(scale: float = 1.0) -> ParticleEffectConfig:
    """餌やりモーション用: 食べかすが飛び散る設定。

    scale: ウィンドウの拡大縮小に合わせて粒のサイズ・速度を比例させる係数。
    """
    return ParticleEffectConfig(
        colors=CRUMB_COLORS,
        count_range=(5, 8),
        lifetime_ms=1000,
        interval_ms=30,
        speed_range=(0.6 * scale, 1.8 * scale),
        size_range=(3 * scale, 6 * scale),
        gravity=0.05 * scale,
        shape="mixed",
    )


def make_sparkle_config(scale: float = 1.0) -> ParticleEffectConfig:
    """なでるモーション用: 白い光の粒が軽やかに浮かび上がって消える設定。

    scale: ウィンドウの拡大縮小に合わせて粒のサイズ・速度を比例させる係数。
    """
    return ParticleEffectConfig(
        colors=GLOW_COLORS,
        count_range=(6, 10),
        lifetime_ms=600,
        interval_ms=30,
        speed_range=(0.3 * scale, 0.9 * scale),
        size_range=(1 * scale, 2.2 * scale),  # 小粒にして光の粒子感を出す
        gravity=-0.03 * scale,  # 負の重力でふわっと上に浮かぶ動きにする
        shape="glow",
    )
