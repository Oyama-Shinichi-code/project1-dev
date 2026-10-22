"""ペットのステータス管理クラス (PetState)。

- mood / hunger / stamina / affection / pet_ap の5ステータス（0〜100）
- virtual_time_offset_minutes による仮想時刻オフセット（時間操作機能）
- JSON永続化（読み込み/保存）
- 時間経過に応じたステータス自動減少（相互作用込み。詳細は
  requirements_drafts/affection_and_balance_spec.md 参照）
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ステータスの減少速度（1分あたりの減少量）。MVPなので固定値。
HUNGER_DECAY_PER_MINUTE = 100 / (60 * 8)  # 満腹100→0を約8時間で消費
MOOD_DECAY_PER_MINUTE = 100 / (60 * 12)  # 機嫌100→0を約12時間で消費

# 満腹度が高すぎる間（食べすぎ）に体力が減る速度。満腹100→0を約10時間で消費する想定。
STAMINA_OVERFED_DECAY_PER_MINUTE = 100 / (60 * 10)
STAMINA_OVERFED_THRESHOLD = 80.0  # この満腹度以上で体力減少が発生する

# 体力不足（閾値未満）の間、機嫌にさらに追加でのしかかる減少速度。
MOOD_LOW_STAMINA_DECAY_PER_MINUTE = 100 / (60 * 10)
MOOD_LOW_STAMINA_THRESHOLD = 80.0  # この体力未満で追加減少が発生する

# なでAP（pet_ap）: なでる効果の減衰・回復を司る内部数値。
PET_AP_COST_PER_PET = 20.0  # なでる1回あたりの消費（100/20=5回で枯渇）
PET_AP_RECOVERY_PER_MINUTE = 100 / 30  # 30分でフル回復

# なつき度（affection）の増減幅。基本は小さい値でこつこつ積み上げる想定。
AFFECTION_GAIN_SMALL = 2.0  # 適切なタイミングでの世話1回あたりの上昇量
AFFECTION_LOSS_SMALL = 2.0  # 不適切な世話1回あたりの下降量
FEED_AFFECTION_HUNGER_MIN = 30.0  # 餌やりでなつき度が上がる空腹度の下限
FEED_AFFECTION_HUNGER_MAX = 60.0  # 餌やりでなつき度が上がる空腹度の上限

# レベルシステム: なつき度到達でレベルアップ、ヒステリシス方式でレベルダウン。
# 10レベルごとに閾値幅・減少ボーダー幅が一段大きくなる階段状。
LEVEL_THRESHOLD_STEP_BY_TIER = [20.0, 35.0, 50.0]  # tier0=Lv1-10, tier1=Lv11-20, tier2=Lv21-30以降
LEVEL_DOWN_BORDER_STEP_BY_TIER = [12.0, 18.0, 24.0]  # 各tierのレベル減少ボーダー幅（約6回の不適切な世話でダウン）

# 構ってほしいイベント（ボーナス型）: 発生中になでる/餌やりをするとボーナス倍率がかかる。
ATTENTION_EVENT_PROBABILITY_PER_CHECK = 0.05  # refresh呼び出し毎の発生確率
ATTENTION_EVENT_DURATION_MINUTES = 10.0  # 表示が続く時間（仮想時刻ベース）
ATTENTION_EVENT_BONUS_MULTIPLIER = 2.0  # 発生中に反応した場合のなつき度ボーナス倍率

# 睡眠機能: 詳細は requirements_drafts/sleep_feature_spec.md 参照。
SLEEP_DEFAULT_DURATION_MINUTES = 60.0  # 睡眠1回あたりの持続時間(デフォルト)
SLEEP_FULL_HUNGER_DURATION_MINUTES = 30.0  # 満腹満タンボーナス時の短縮後の持続時間
SLEEP_STAMINA_FULL_RECOVERY_MINUTES = 60.0  # 睡眠中、体力が0→100までフル回復するのにかかる時間(通常時)
SLEEP_HUNGER_DECAY_MULTIPLIER = 0.25  # 睡眠中の満腹度減少倍率(通常の1/4)
SLEEP_RANDOM_CHECK_INTERVAL_MINUTES = 60.0  # 自動入眠のランダム判定を行う間隔
SLEEP_RANDOM_PROBABILITY_AT_LV1 = 0.30  # Lv1での自動入眠判定確率
SLEEP_RANDOM_PROBABILITY_AT_LV20 = 0.03  # Lv20での自動入眠判定確率
SLEEP_RANDOM_PROBABILITY_ZERO_LEVEL = 30  # この値以降は自動入眠確率が0になるレベル
SLEEP_BEDTIME_MIN_LEVEL = 10  # お休み時間設定機能が解放されるレベル
SLEEP_WAKE_UP_MOOD_PENALTY = 20.0  # 強制的に起こされた時の機嫌減少量
SLEEP_WAKE_UP_AFFECTION_PENALTY = 5.0  # 強制的に起こされた時のなつき度減少量
SLEEP_FULL_HUNGER_AFFECTION_BONUS = 2.0  # 満腹満タンボーナス: なつき度上昇量
SLEEP_FULL_HUNGER_MOOD_BONUS = 10.0  # 満腹満タンボーナス: 機嫌上昇量
SLEEP_NARRATION_TEXT = "睡眠中のようだ。静かにしてあげよう"


def _level_threshold_step(level: int) -> float:
    """指定レベルからレベルアップするために必要ななつき度の増加幅。"""
    tier = min((level - 1) // 10, len(LEVEL_THRESHOLD_STEP_BY_TIER) - 1)
    return LEVEL_THRESHOLD_STEP_BY_TIER[tier]


def _level_down_border(level: int) -> float:
    """指定レベルを維持するために許容できる、なつき度低下の累積量（ボーダー）。"""
    tier = min((level - 1) // 10, len(LEVEL_DOWN_BORDER_STEP_BY_TIER) - 1)
    return LEVEL_DOWN_BORDER_STEP_BY_TIER[tier]


def _random_sleep_probability(level: int) -> float:
    """指定レベルでの自動入眠（ランダム判定）の発生確率。

    Lv1で30%、Lv20で3%の間を線形補間し、Lv30以降は0%にする。
    """
    if level >= SLEEP_RANDOM_PROBABILITY_ZERO_LEVEL:
        return 0.0
    if level <= 1:
        return SLEEP_RANDOM_PROBABILITY_AT_LV1
    if level >= 20:
        # Lv20〜Lv29は3%から0%へさらに線形に減衰させる
        ratio = (level - 20) / (SLEEP_RANDOM_PROBABILITY_ZERO_LEVEL - 20)
        return SLEEP_RANDOM_PROBABILITY_AT_LV20 * (1.0 - ratio)
    ratio = (level - 1) / (20 - 1)
    return SLEEP_RANDOM_PROBABILITY_AT_LV1 + (SLEEP_RANDOM_PROBABILITY_AT_LV20 - SLEEP_RANDOM_PROBABILITY_AT_LV1) * ratio


STATUS_MIN = 0
STATUS_MAX = 100

DEFAULT_DATA_PATH = Path(__file__).parent / "data" / "pet_state.json"
DEFAULT_TOGGLE_BUTTON_ORDER = [
    "quit",
    "menu",
    "status",
    "grip_design",
    "always_on_top",
    "chat",
    "bedtime",
    "debug_sleep",
]

CHAT_HISTORY_MAX_LEN = 20  # 保存する会話履歴の上限件数（将来の繰り返し検出ロジック等が参照する範囲）

NARRATION_LOG_MAX_LEN = 50  # 操作ナレーションログの保存件数上限

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
class NarrationEntry:
    """操作・状態変化の定型文ナレーション1件の記録（文言＋記録時刻＋通し番号）。

    seqは記録順に単調増加する通し番号。narration_logは最大
    NARRATION_LOG_MAX_LEN件しか保持せず古いものから削られるため、
    「件数の増減」ではなく「このseqより新しいか」でUI側は新規分を検知する。
    """

    text: str
    timestamp: str  # isoformat（実時刻基準）
    seq: int


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
    affection: float = 0.0  # なつき度（0〜100）。レベルアップの閾値を超えるとレベルが上がる
    pet_ap: float = 100.0  # なでAP。なでる効果の減衰・回復を司る
    # なつき度の連続ケアストリーク。なつき度が下がった時点でどちらも0にリセットする。
    affection_care_streak_count: int = 0  # 「適切な世話」が連続成功した回数
    affection_care_streak_days: int = 0  # 「適切な世話ができた日」が連続した日数
    last_care_date: str = ""  # 直近で「適切な世話」が成立した日付(YYYY-MM-DD、仮想時刻基準)
    # 現在のレベルを維持できる、なつき度低下の残り許容量（レベルアップ時にそのレベルの
    # ボーダー値へリセットされ、なつき度が下がるたびに消費される。0でレベルダウン）。
    level_down_remaining: float = field(default_factory=lambda: _level_down_border(1))
    # 構ってほしいイベントの表示終了時刻（isoformat、仮想時刻基準）。空文字列は非発生中を表す。
    attention_event_until: str = ""
    # 操作・状態変化の定型文ナレーション履歴（直近NARRATION_LOG_MAX_LEN件、古い順）。
    # 末尾が最新。UIの常時表示欄・ログ一覧パネルの両方がここを参照する。
    narration_log: list[NarrationEntry] = field(default_factory=list)
    # NarrationEntry.seqに使う通し番号（次に発行する値）。古いログが削られても
    # 単調増加し続けるため、UI側はこれで「見たことのある最新seq」を基準に
    # 新規分を検知できる（narration_logの件数比較だと上限到達後に壊れるため）。
    narration_seq_counter: int = 0
    # --- 睡眠機能 ---
    is_sleeping: bool = False
    sleep_started_at: str = ""  # isoformat（仮想時刻基準）。is_sleeping=Falseの間は無意味
    sleep_duration_minutes: float = SLEEP_DEFAULT_DURATION_MINUTES  # 今回の睡眠の持続時間（満タンボーナスで短縮される場合あり）
    sleep_stamina_recovery_multiplier: float = 1.0  # 満タンボーナスで2.0になる
    sleep_hunger_decay_multiplier: float = SLEEP_HUNGER_DECAY_MULTIPLIER  # 満タンボーナスで1.0(軽減なし)になる
    bedtime_hour: int | None = None  # お休み時間設定（時）。未設定はNone
    bedtime_minute: int | None = None  # お休み時間設定（分）
    # 1時間ごとの自動入眠ランダム判定を最後に行った時刻（isoformat、仮想時刻基準）。
    # 非起動中の経過をこの時刻からの差分で1時間区間に区切ってシミュレートする。
    last_random_sleep_check_at: str = ""
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

    # --- なつき度（レベル）によるフィードバック係数 ---
    # affectionは「次のレベルまでの累積値（経験値）」のため0〜100の固定ゲージではなく、
    # フィードバック係数にはレベルそのものを使う（Lv30で頭打ち）。
    _AFFECTION_FEEDBACK_MAX_LEVEL = 30

    def _affection_feedback_ratio(self) -> float:
        """なつき度の習熟度合いを0.0〜1.0で表す（Lv1で0.0、Lv30以降で1.0）。"""
        return min(1.0, (self.level - 1) / (self._AFFECTION_FEEDBACK_MAX_LEVEL - 1))

    def mood_decay_multiplier(self) -> float:
        """レベルが低いほど機嫌の自然減衰を速める係数（Lv1で1.5倍、Lv30以降で0.6倍）。"""
        return 1.5 - self._affection_feedback_ratio() * 0.9

    def pet_mood_gain_multiplier(self) -> float:
        """レベルが低いほどなでる効果（機嫌回復量）を弱める係数（Lv1で0.8倍、Lv30以降で1.5倍）。"""
        return 0.8 + self._affection_feedback_ratio() * 0.7

    # --- ステータス減少（時間経過の反映） ---
    def apply_time_decay(self, now: datetime | None = None) -> None:
        """last_updated から現在（仮想時刻）までの経過分だけステータスを減少させる。

        アプリ非起動中の時間経過も、次回起動時にこの関数で一括反映される。
        満腹度過多による体力減少・体力不足による追加の機嫌減少・なでAPの回復も
        ここでまとめて反映する（詳細は affection_and_balance_spec.md 参照）。

        睡眠機能（詳細はrequirements_drafts/sleep_feature_spec.md参照）により、
        経過時間を「1時間ごとの区間」＋「端数区間」に分割し、区間ごとに
        自動入眠判定・睡眠中/覚醒中の処理を切り替えながら順に適用していく。
        最後の区間（現在時刻に到達する区間）で新規に入眠が成立した場合は、
        その区間の睡眠ボーナス（体力回復等）は適用せず「入眠した事実」のみ反映する
        （半端な時間分の先取り回復をしないようにするため）。
        """
        now = now or self.virtual_now()
        last = datetime.fromisoformat(self.last_updated)
        if (now - last).total_seconds() <= 0:
            # 時間を戻した直後などで経過がマイナスになる場合は何もしない
            self.last_updated = now.isoformat()
            return

        if not self.last_random_sleep_check_at:
            self.last_random_sleep_check_at = last.isoformat()

        cursor = last
        while cursor < now:
            next_random_check = datetime.fromisoformat(self.last_random_sleep_check_at) + timedelta(
                minutes=SLEEP_RANDOM_CHECK_INTERVAL_MINUTES
            )
            next_bedtime = self._next_bedtime_after(cursor)
            # この区間の終端: 次の1時間境界・次のお休み時刻・現在時刻（最後の端数区間）のうち最も早いもの
            candidates = [next_random_check, now]
            if next_bedtime is not None:
                candidates.append(next_bedtime)
            segment_end = min(candidates)
            is_final_segment = segment_end >= now
            segment_minutes = (segment_end - cursor).total_seconds() / 60

            newly_started_sleep = False
            if segment_end >= next_random_check:
                # 1時間境界に到達した区間: 判定基準時刻を進め、必要なら自動入眠判定を行う
                self.last_random_sleep_check_at = next_random_check.isoformat()
                if not self.is_sleeping and self._should_check_random_sleep():
                    if random.random() < _random_sleep_probability(self.level):
                        self._start_sleep(reason="自分勝手に", started_at=cursor)
                        newly_started_sleep = True
            if (
                not newly_started_sleep
                and next_bedtime is not None
                and segment_end >= next_bedtime
                and not self.is_sleeping
                and self._should_check_random_sleep()
            ):
                self._start_sleep(reason="お休み時間になって", started_at=cursor)
                newly_started_sleep = True

            if segment_minutes > 0:
                if is_final_segment and newly_started_sleep:
                    # 最後の端数区間で新規入眠した場合は、その区間分の睡眠ボーナスは
                    # シミュレートしない（入眠した事実のみ反映する）。
                    pass
                elif self.is_sleeping:
                    self._apply_sleep_decay_step(segment_minutes, segment_end=segment_end)
                else:
                    self._apply_awake_decay_step(segment_minutes)

            cursor = segment_end

        self.last_updated = now.isoformat()

    def _next_bedtime_after(self, after: datetime) -> datetime | None:
        """指定時刻より後で、最も近い「お休み時間」の日時を返す（機能無効なら常にNone）。"""
        if self.level < SLEEP_BEDTIME_MIN_LEVEL or self.bedtime_hour is None or self.bedtime_minute is None:
            return None
        candidate = after.replace(hour=self.bedtime_hour, minute=self.bedtime_minute, second=0, microsecond=0)
        if candidate <= after:
            candidate += timedelta(days=1)
        return candidate

    def _should_check_random_sleep(self) -> bool:
        """自動入眠のランダム判定を行ってよい状態か（満腹度0では入眠しない）。"""
        return self.hunger > 0

    def _apply_awake_decay_step(self, elapsed_minutes: float) -> None:
        """覚醒中の時間経過1区間分の通常のステータス減衰（既存ロジック）。"""
        self.hunger = _clamp(self.hunger - elapsed_minutes * HUNGER_DECAY_PER_MINUTE)

        if self.hunger >= STAMINA_OVERFED_THRESHOLD:
            self.stamina = _clamp(self.stamina - elapsed_minutes * STAMINA_OVERFED_DECAY_PER_MINUTE)

        mood_decay = elapsed_minutes * MOOD_DECAY_PER_MINUTE * self.mood_decay_multiplier()
        if self.stamina < MOOD_LOW_STAMINA_THRESHOLD:
            mood_decay += elapsed_minutes * MOOD_LOW_STAMINA_DECAY_PER_MINUTE
        self.mood = _clamp(self.mood - mood_decay)

        self.pet_ap = _clamp(self.pet_ap + elapsed_minutes * PET_AP_RECOVERY_PER_MINUTE)

    def _apply_sleep_decay_step(self, elapsed_minutes: float, segment_end: datetime) -> None:
        """睡眠中の時間経過1区間分のステータス変化。機嫌は変化させない。

        segment_end: この区間が終わる時刻（シミュレート上の時刻。実時刻の
        self.virtual_now()ではなく、apply_time_decay側が計算した時刻を使う必要がある）。
        """
        stamina_recovery_per_minute = (
            100 / SLEEP_STAMINA_FULL_RECOVERY_MINUTES
        ) * self.sleep_stamina_recovery_multiplier
        self.stamina = _clamp(self.stamina + elapsed_minutes * stamina_recovery_per_minute)
        self.hunger = _clamp(
            self.hunger - elapsed_minutes * HUNGER_DECAY_PER_MINUTE * self.sleep_hunger_decay_multiplier
        )
        self.pet_ap = _clamp(self.pet_ap + elapsed_minutes * PET_AP_RECOVERY_PER_MINUTE)

        if self.hunger <= 0:
            self._force_wake_up(reason="お腹が空きすぎて")
            return

        sleep_started = datetime.fromisoformat(self.sleep_started_at)
        elapsed_since_sleep = (segment_end - sleep_started).total_seconds() / 60
        if elapsed_since_sleep >= self.sleep_duration_minutes:
            self._wake_up_naturally()

    # --- 睡眠機能 ---
    def _start_sleep(self, reason: str, started_at: datetime | None = None) -> None:
        """入眠する。満腹度が満タン(100)なら入眠ボーナスを同時に適用する。

        started_at: 入眠時刻として扱う時刻。apply_time_decay内のシミュレート中は
        区間の開始時刻（cursor）を明示的に渡す必要がある（virtual_now()だと
        シミュレート対象の時刻ではなく「実際の呼び出し時点の時刻」になってしまうため）。
        未指定時（デバッグ入眠等）はvirtual_now()を使う。
        """
        self.is_sleeping = True
        self.sleep_started_at = (started_at or self.virtual_now()).isoformat()
        if self.hunger >= STATUS_MAX:
            self.sleep_duration_minutes = SLEEP_FULL_HUNGER_DURATION_MINUTES
            self.sleep_stamina_recovery_multiplier = 2.0
            self.sleep_hunger_decay_multiplier = 1.0  # 満腹軽減効果は無効化（通常通り減る）
            self.affection = _clamp(self.affection + SLEEP_FULL_HUNGER_AFFECTION_BONUS)
            self.mood = _clamp(self.mood + SLEEP_FULL_HUNGER_MOOD_BONUS)
            self.push_narration(
                f"お腹いっぱいで{reason}眠りについた。なつき度が{SLEEP_FULL_HUNGER_AFFECTION_BONUS:.0f}"
                f"上がり、機嫌が{SLEEP_FULL_HUNGER_MOOD_BONUS:.0f}回復した"
            )
        else:
            self.sleep_duration_minutes = SLEEP_DEFAULT_DURATION_MINUTES
            self.sleep_stamina_recovery_multiplier = 1.0
            self.sleep_hunger_decay_multiplier = SLEEP_HUNGER_DECAY_MULTIPLIER
            self.push_narration(f"{reason}眠りについた")

    def _wake_up_naturally(self) -> None:
        """睡眠時間を満了し、ペナルティなしで自然に起床する。"""
        self.is_sleeping = False
        self.push_narration("すっきりした様子で目を覚ました")

    def _force_wake_up(self, reason: str) -> None:
        """強制的に起こされる（ユーザー操作、または満腹度0）。機嫌・なつき度にペナルティ。"""
        self.is_sleeping = False
        self.mood = max(0.0, self.mood - SLEEP_WAKE_UP_MOOD_PENALTY)
        self.push_narration(f"{reason}起こされてしまい機嫌が{SLEEP_WAKE_UP_MOOD_PENALTY:.0f}下がった")
        self._apply_affection_delta(-SLEEP_WAKE_UP_AFFECTION_PENALTY, reason=f"{reason}安眠を妨げられて")

    def wake_up_by_action(self) -> bool:
        """なでる/餌やり操作による強制起床。睡眠中でなければ何もしない。

        戻り値は実際に起床させたかどうか（呼び出し元がモーション分岐に使う）。
        """
        if not self.is_sleeping:
            return False
        self._force_wake_up(reason="眠っているところを")
        return True

    def start_sleep_debug(self) -> None:
        """デバッグ用: 条件を無視して即座に入眠する。"""
        self._start_sleep(reason="（デバッグ）")

    def set_bedtime(self, hour: int | None, minute: int | None) -> None:
        """お休み時間を設定する（Noneで未設定に戻す）。"""
        self.bedtime_hour = hour
        self.bedtime_minute = minute

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
        """通常の餌やり（あげすぎでない場合）。空腹度30〜60%の時のみなつき度ボーナスが付く。"""
        hunger_before = self.hunger
        self.hunger = _clamp(self.hunger + amount)
        self.push_narration(f"おいしそうに食べて満腹度が{self.hunger - hunger_before:.0f}回復した")
        if FEED_AFFECTION_HUNGER_MIN <= hunger_before <= FEED_AFFECTION_HUNGER_MAX:
            self._apply_affection_delta(
                AFFECTION_GAIN_SMALL * self._consume_attention_event_bonus(),
                reason="ちょうどいいタイミングで餌をもらえて",
            )
            self._register_care_success()

    def overfeed_penalty(self) -> None:
        """あげすぎ時のペナルティ（機嫌減少＋なつき度減少）。controller.feed()から呼ばれる。"""
        self.mood = max(0.0, self.mood - 5.0)
        self.push_narration("お腹いっぱいなのに食べさせられて機嫌が5下がった")
        self._apply_affection_delta(-AFFECTION_LOSS_SMALL, reason="お腹いっぱいなのに無理やり食べさせられて")
        self._reset_care_streak()

    def pet(self, amount: float = 15.0) -> bool:
        """なでる。戻り値は「なですぎ」だったかどうか（True=なですぎ、機嫌回復なし）。

        pet_apが尽きている場合は機嫌回復せずなつき度が下がる（なですぎ）。
        """
        if self.pet_ap <= 0:
            self._apply_affection_delta(-AFFECTION_LOSS_SMALL, reason="なでられすぎてうんざりして")
            self._reset_care_streak()
            return True
        mood_before = self.mood
        gained_ratio = self.pet_ap / 100.0
        self.mood = _clamp(self.mood + amount * gained_ratio * self.pet_mood_gain_multiplier())
        self.push_narration(f"なでられて嬉しそうに機嫌が{self.mood - mood_before:.0f}回復した")
        self.pet_ap = _clamp(self.pet_ap - PET_AP_COST_PER_PET)
        self._apply_affection_delta(
            AFFECTION_GAIN_SMALL * self._consume_attention_event_bonus(), reason="なでられて喜んでいて"
        )
        self._register_care_success()
        return False

    def apply_chat_mood_delta(self, delta: float) -> None:
        """会話評価によるmood変化を反映する（mood_rules.compute_mood_deltaの結果を渡す）。"""
        self.mood = _clamp(self.mood + delta)

    # --- なつき度・レベル ---
    def affection_to_next_level(self) -> float:
        """次のレベルまでに必要ななつき度の残り量（UI表示用）。"""
        return _level_threshold_step(self.level) - self.affection

    def _apply_affection_delta(self, delta: float, reason: str) -> None:
        """なつき度を増減し、レベルアップ/レベルダウン判定を行う。

        reason: なつき度変化の原因を表す文（例: 「なでられて喜んでいて」）。
        「{reason}なつき度が{値}上がった/下がった」という文でユーザーに
        「何をしたから」「なぜ」変化したのかが伝わるようにする。
        """
        self.affection = _clamp(self.affection + delta)
        if delta < 0:
            self.push_narration(f"{reason}なつき度が{-delta:.0f}下がった")
            self.level_down_remaining -= -delta
            while self.level_down_remaining <= 0 and self.level > 1:
                self.level -= 1
                self.level_down_remaining += _level_down_border(self.level)
                self.push_narration(f"なつき度が下がり続けてレベルが{self.level}に下がってしまった")
        elif delta > 0:
            self.push_narration(f"{reason}なつき度が{delta:.0f}上がった")
            while self.affection >= _level_threshold_step(self.level):
                self.affection -= _level_threshold_step(self.level)
                self.level += 1
                self.level_down_remaining = _level_down_border(self.level)
                self.push_narration(f"なつき度が十分たまってレベルが{self.level}に上がった！")

    def _register_care_success(self) -> None:
        """「適切な世話」が成立した時のストリーク更新（回数・日数の両方）。"""
        self.affection_care_streak_count += 1
        today = self.virtual_now().date().isoformat()
        if self.last_care_date != today:
            yesterday = (self.virtual_now() - timedelta(days=1)).date().isoformat()
            if self.last_care_date == yesterday:
                self.affection_care_streak_days += 1
            else:
                self.affection_care_streak_days = 1
            self.last_care_date = today

    def _reset_care_streak(self) -> None:
        """なつき度が下がるイベントが起きた時点で両方のストリークをリセットする。"""
        self.affection_care_streak_count = 0
        self.affection_care_streak_days = 0

    # --- ナレーションログ ---
    def push_narration(self, text: str) -> None:
        """操作・状態変化の定型文ナレーションを記録する（直近NARRATION_LOG_MAX_LEN件を保持）。

        時刻は実時刻（datetime.now()）を使う。virtual_now()（仮想時刻）だと
        時間操作機能で進めた/戻した分だけログの日時がズレて分かりにくくなるため、
        ログは常に「実際に操作した時刻」を記録する。
        """
        self.narration_seq_counter += 1
        self.narration_log.append(
            NarrationEntry(text=text, timestamp=datetime.now().isoformat(), seq=self.narration_seq_counter)
        )
        if len(self.narration_log) > NARRATION_LOG_MAX_LEN:
            self.narration_log = self.narration_log[-NARRATION_LOG_MAX_LEN:]

    # --- 構ってほしいイベント（ボーナス型） ---
    def is_attention_event_active(self) -> bool:
        """現在「構ってほしい」表示中かどうか（仮想時刻ベース）。"""
        if not self.attention_event_until:
            return False
        return self.virtual_now() < datetime.fromisoformat(self.attention_event_until)

    def maybe_trigger_attention_event(self) -> bool:
        """低確率で構ってほしいイベントを発生させる。refresh（定期タイマー）から呼ばれる想定。

        既に発生中の場合は何もしない。戻り値は新規に発生させたかどうか（UI側の通知用）。
        """
        if self.is_attention_event_active():
            return False
        if random.random() >= ATTENTION_EVENT_PROBABILITY_PER_CHECK:
            return False
        until = self.virtual_now() + timedelta(minutes=ATTENTION_EVENT_DURATION_MINUTES)
        self.attention_event_until = until.isoformat()
        self.push_narration("構ってほしそうにこちらを見ている")
        return True

    def _consume_attention_event_bonus(self) -> float:
        """発生中であればボーナス倍率を返し、イベントを消費（終了）する。非発生中は1.0倍。"""
        if not self.is_attention_event_active():
            return 1.0
        self.attention_event_until = ""
        return ATTENTION_EVENT_BONUS_MULTIPLIER

    # --- 見た目切り替え用の表情判定 ---
    def current_expression(self, hungry_threshold: float = 30.0, angry_threshold: float = 30.0) -> str:
        """優先順位: sleeping > hungry > angry > normal。"""
        if self.is_sleeping:
            return "sleeping"
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
                "affection": self.affection,
                "pet_ap": self.pet_ap,
            },
            "affection_care": {
                "streak_count": self.affection_care_streak_count,
                "streak_days": self.affection_care_streak_days,
                "last_care_date": self.last_care_date,
                "level_down_remaining": self.level_down_remaining,
            },
            "attention_event_until": self.attention_event_until,
            "narration_log": [
                {"text": entry.text, "timestamp": entry.timestamp, "seq": entry.seq}
                for entry in self.narration_log[-NARRATION_LOG_MAX_LEN:]
            ],
            "narration_seq_counter": self.narration_seq_counter,
            "sleep": {
                "is_sleeping": self.is_sleeping,
                "sleep_started_at": self.sleep_started_at,
                "sleep_duration_minutes": self.sleep_duration_minutes,
                "sleep_stamina_recovery_multiplier": self.sleep_stamina_recovery_multiplier,
                "sleep_hunger_decay_multiplier": self.sleep_hunger_decay_multiplier,
                "bedtime_hour": self.bedtime_hour,
                "bedtime_minute": self.bedtime_minute,
                "last_random_sleep_check_at": self.last_random_sleep_check_at,
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

        fallback_timestamp = data.get("last_updated", datetime.now().isoformat())
        raw_narration_log = data.get("narration_log")
        narration_log: list[NarrationEntry] = []
        if isinstance(raw_narration_log, list):
            for index, raw_entry in enumerate(raw_narration_log):
                if isinstance(raw_entry, str):
                    # 旧形式（文字列のみ、seqも無い）との後方互換。
                    # 時刻不明のため保存時刻で、seqは出現順の連番で代用する。
                    narration_log.append(
                        NarrationEntry(text=raw_entry, timestamp=fallback_timestamp, seq=index + 1)
                    )
                elif isinstance(raw_entry, dict):
                    try:
                        narration_log.append(
                            NarrationEntry(
                                text=raw_entry["text"],
                                timestamp=raw_entry["timestamp"],
                                seq=raw_entry.get("seq", index + 1),
                            )
                        )
                    except KeyError:
                        continue
        narration_seq_counter = data.get(
            "narration_seq_counter", narration_log[-1].seq if narration_log else 0
        )

        level = data.get("level", 1)
        affection_care = data.get("affection_care", {})
        sleep = data.get("sleep", {})

        return cls(
            pet_id=data.get("pet_id", "pet_001"),
            name=data.get("name", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_updated=data.get("last_updated", datetime.now().isoformat()),
            virtual_time_offset_minutes=data.get("virtual_time_offset_minutes", 0.0),
            level=level,
            mood=status.get("mood", 80.0),
            hunger=status.get("hunger", 80.0),
            stamina=status.get("stamina", 100.0),
            affection=status.get("affection", 0.0),
            pet_ap=status.get("pet_ap", 100.0),
            affection_care_streak_count=affection_care.get("streak_count", 0),
            affection_care_streak_days=affection_care.get("streak_days", 0),
            last_care_date=affection_care.get("last_care_date", ""),
            level_down_remaining=affection_care.get("level_down_remaining", _level_down_border(level)),
            attention_event_until=data.get("attention_event_until", ""),
            narration_log=narration_log,
            narration_seq_counter=narration_seq_counter,
            is_sleeping=sleep.get("is_sleeping", False),
            sleep_started_at=sleep.get("sleep_started_at", ""),
            sleep_duration_minutes=sleep.get("sleep_duration_minutes", SLEEP_DEFAULT_DURATION_MINUTES),
            sleep_stamina_recovery_multiplier=sleep.get("sleep_stamina_recovery_multiplier", 1.0),
            sleep_hunger_decay_multiplier=sleep.get(
                "sleep_hunger_decay_multiplier", SLEEP_HUNGER_DECAY_MULTIPLIER
            ),
            bedtime_hour=sleep.get("bedtime_hour"),
            bedtime_minute=sleep.get("bedtime_minute"),
            last_random_sleep_check_at=sleep.get("last_random_sleep_check_at", ""),
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
