"""ペットのステータス管理クラス (PetState)。

- mood / hunger / stamina の3ステータス（0〜100）
- virtual_time_offset_minutes による仮想時刻オフセット（時間操作機能）
- JSON永続化（読み込み/保存）
- 時間経過に応じたステータス自動減少
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ステータスの減少速度（1分あたりの減少量）。MVPなので固定値。
HUNGER_DECAY_PER_MINUTE = 100 / (60 * 8)  # 満腹100→0を約8時間で消費
MOOD_DECAY_PER_MINUTE = 100 / (60 * 12)  # 機嫌100→0を約12時間で消費

STATUS_MIN = 0
STATUS_MAX = 100

DEFAULT_DATA_PATH = Path(__file__).parent / "data" / "pet_state.json"


def _clamp(value: float) -> float:
    return max(STATUS_MIN, min(STATUS_MAX, value))


@dataclass
class PetState:
    pet_id: str = "pet_001"
    name: str = "ぽちこ"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    virtual_time_offset_minutes: float = 0.0
    level: int = 1
    mood: float = 80.0
    hunger: float = 80.0
    stamina: float = 100.0
    evolution_stage: str = "child"
    notifications_enabled: bool = True
    window_position: list[int] = field(default_factory=lambda: [1200, 650])

    # --- 現在時刻（仮想オフセット込み） ---
    def virtual_now(self) -> datetime:
        """実時刻 + 仮想オフセットを「現在時刻」として扱う（要件3.3）。"""
        return datetime.now() + timedelta(minutes=self.virtual_time_offset_minutes)

    # --- ステータス減少（時間経過の反映） ---
    def apply_time_decay(self, now: datetime | None = None) -> None:
        """last_updated から現在（仮想時刻）までの経過分だけステータスを減少させる。

        アプリ非起動中の時間経過も、次回起動時にこの関数で一括反映される。
        """
        now = now or self.virtual_now()
        last = datetime.fromisoformat(self.last_updated)
        elapsed_minutes = (now - last).total_seconds() / 60
        if elapsed_minutes <= 0:
            # 時間を戻した直後などで経過がマイナスになる場合は何もしない
            self.last_updated = now.isoformat()
            return
        self.hunger = _clamp(self.hunger - elapsed_minutes * HUNGER_DECAY_PER_MINUTE)
        self.mood = _clamp(self.mood - elapsed_minutes * MOOD_DECAY_PER_MINUTE)
        self.last_updated = now.isoformat()

    # --- 時間操作機能（要件3.3） ---
    def advance_time(self, minutes: float) -> None:
        """時間を進める。オフセットを加算し、その分のステータス変化を即時反映する。"""
        self.virtual_time_offset_minutes += minutes
        self.apply_time_decay()

    def rewind_time(self, minutes: float) -> None:
        """時間を戻す。オフセットのみ減算し、既に適用済みのステータス変化は巻き戻さない。"""
        self.virtual_time_offset_minutes -= minutes
        # last_updated は更新しない（過去のステータス変化・イベント履行を取り消さない）。

    # --- 基本アクション ---
    def feed(self, amount: float = 25.0) -> None:
        self.apply_time_decay()
        self.hunger = _clamp(self.hunger + amount)

    def pet(self, amount: float = 15.0) -> None:
        self.apply_time_decay()
        self.mood = _clamp(self.mood + amount)

    # --- 見た目切り替え用の表情判定 ---
    def current_expression(self, hungry_threshold: float = 30.0, angry_threshold: float = 30.0) -> str:
        """優先順位: hungry > angry > normal。"""
        if self.hunger < hungry_threshold:
            return "hungry"
        if self.mood < angry_threshold:
            return "angry"
        return "normal"

    # --- シリアライズ ---
    def to_dict(self) -> dict[str, Any]:
        return {
            "pet_id": self.pet_id,
            "name": self.name,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "virtual_time_offset_minutes": self.virtual_time_offset_minutes,
            "level": self.level,
            "status": {
                "mood": self.mood,
                "hunger": self.hunger,
                "stamina": self.stamina,
            },
            "evolution_stage": self.evolution_stage,
            "settings": {
                "notifications_enabled": self.notifications_enabled,
                "window_position": self.window_position,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PetState":
        status = data.get("status", {})
        settings = data.get("settings", {})
        return cls(
            pet_id=data.get("pet_id", "pet_001"),
            name=data.get("name", "ぽちこ"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_updated=data.get("last_updated", datetime.now().isoformat()),
            virtual_time_offset_minutes=data.get("virtual_time_offset_minutes", 0.0),
            level=data.get("level", 1),
            mood=status.get("mood", 80.0),
            hunger=status.get("hunger", 80.0),
            stamina=status.get("stamina", 100.0),
            evolution_stage=data.get("evolution_stage", "child"),
            notifications_enabled=settings.get("notifications_enabled", True),
            window_position=settings.get("window_position", [1200, 650]),
        )

    # --- 永続化 ---
    def save(self, path: Path = DEFAULT_DATA_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load_or_create(cls, path: Path = DEFAULT_DATA_PATH) -> "PetState":
        """JSONが存在すれば読み込み、無ければ初期状態で作成する。"""
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            state = cls.from_dict(data)
        else:
            state = cls()
        # 読み込み直後に非起動中の時間経過を反映する
        state.apply_time_decay()
        return state
