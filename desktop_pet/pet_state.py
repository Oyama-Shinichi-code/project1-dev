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
DEFAULT_TOGGLE_BUTTON_ORDER = ["quit", "menu", "status", "grip_design", "always_on_top", "chat"]

CHAT_HISTORY_MAX_LEN = 20  # 保存する会話履歴の上限件数（将来の繰り返し検出ロジック等が参照する範囲）

PET_NAME_MAX_LEN = 15  # ペット名の最大文字数


def _clamp(value: float) -> float:
    return max(STATUS_MIN, min(STATUS_MAX, value))


def validate_pet_name(name: str) -> str | None:
    """ペット名として使える文字列かを検証する。

    使えない場合はエラーメッセージを返し、問題なければNoneを返す
    （exeでの環境依存文字化け・表示崩れを避けるため、絵文字や制御文字は禁止する）。
    """
    stripped = name.strip()
    if not stripped:
        return "名前を入力してください。"
    if len(stripped) > PET_NAME_MAX_LEN:
        return f"名前は{PET_NAME_MAX_LEN}文字以内で入力してください。"
    for ch in stripped:
        codepoint = ord(ch)
        # 制御文字、およびサロゲートペア対象(絵文字等の多くが該当する0x1F000以降)を禁止する。
        # 基本多言語面（日本語・英数字・一般記号を含む）はそのまま許可する。
        if codepoint < 0x20 or codepoint == 0x7F or codepoint > 0xFFFF:
            return "絵文字や特殊な記号は名前に使用できません。"
    return None


@dataclass
class ChatHistoryEntry:
    """会話1往復分の記録（ユーザー発言・AIのナレーション・評価・mood変化量）。"""

    user_text: str
    narration: str
    level: str
    mood_delta: float
    timestamp: str  # isoformat
    is_inappropriate: bool = False


@dataclass
class PetState:
    pet_id: str = "pet_001"
    # 空文字列は「名前未設定」を表す（名前を付けるまで会話機能は使わせない）。
    # 既存セーブデータを持つユーザーは引き続き保存済みの名前（例: "ぽちこ"）が読み込まれる。
    name: str = ""
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
    # 右下に縦積みされるトグルボタンの並び順（下から上の順）。
    # ユーザーがドラッグ&ドロップで並び替えた結果を保存する。
    toggle_button_order: list[str] = field(
        default_factory=lambda: list(DEFAULT_TOGGLE_BUTTON_ORDER)
    )
    # 会話機能の履歴（直近CHAT_HISTORY_MAX_LEN件）。将来の評価ロジック高度化
    # （同一発言の繰り返し検出等）で参照する想定。
    chat_history: list[ChatHistoryEntry] = field(default_factory=list)

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
    # feed/pet はステータスの加算のみ行い、apply_time_decay()は呼ばない。
    # 時間経過による自然減少は定期タイマー側（main.pyのrefresh）だけの責務とし、
    # アクション実行のたびにそれまでの経過分がまとめて反映されて数値が動いて見える
    # （「なでた/餌をあげたのに満腹度が減った」ように見える）事態を避けるため。
    def feed(self, amount: float = 25.0) -> None:
        self.hunger = _clamp(self.hunger + amount)

    def pet(self, amount: float = 15.0) -> None:
        self.mood = _clamp(self.mood + amount)

    def apply_chat_mood_delta(self, delta: float) -> None:
        """会話評価によるmood変化を反映する（mood_rules.compute_mood_deltaの結果を渡す）。"""
        self.mood = _clamp(self.mood + delta)

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
                "toggle_button_order": self.toggle_button_order,
            },
            # 直近CHAT_HISTORY_MAX_LEN件のみ保存し、無限に肥大化しないようにする
            "chat_history": [
                {
                    "user_text": entry.user_text,
                    "narration": entry.narration,
                    "level": entry.level,
                    "mood_delta": entry.mood_delta,
                    "timestamp": entry.timestamp,
                    "is_inappropriate": entry.is_inappropriate,
                }
                for entry in self.chat_history[-CHAT_HISTORY_MAX_LEN:]
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PetState":
        status = data.get("status", {})
        settings = data.get("settings", {})
        toggle_button_order = settings.get("toggle_button_order")
        # 保存データの要素が現行のボタンID集合と完全一致しない場合
        # （手編集での破損、将来のボタン増減など）はデフォルト順にフォールバックする
        if (
            not isinstance(toggle_button_order, list)
            or set(toggle_button_order) != set(DEFAULT_TOGGLE_BUTTON_ORDER)
        ):
            toggle_button_order = list(DEFAULT_TOGGLE_BUTTON_ORDER)

        raw_chat_history = data.get("chat_history")
        chat_history: list[ChatHistoryEntry] = []
        if isinstance(raw_chat_history, list):
            for raw_entry in raw_chat_history:
                try:
                    chat_history.append(
                        ChatHistoryEntry(
                            user_text=raw_entry["user_text"],
                            narration=raw_entry["narration"],
                            level=raw_entry["level"],
                            mood_delta=raw_entry["mood_delta"],
                            timestamp=raw_entry["timestamp"],
                            is_inappropriate=raw_entry.get("is_inappropriate", False),
                        )
                    )
                except (KeyError, TypeError):
                    # 壊れたエントリは無視する（1件の破損で全体を失わないため）
                    continue

        return cls(
            pet_id=data.get("pet_id", "pet_001"),
            name=data.get("name", ""),
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
            toggle_button_order=toggle_button_order,
            chat_history=chat_history,
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
