"""PetStateのなつき度・レベル・なでAPまわりのロジックに対するテスト。"""
from __future__ import annotations

from datetime import timedelta

from desktop_pet.pet_state import (
    AFFECTION_GAIN_SMALL,
    ATTENTION_EVENT_BONUS_MULTIPLIER,
    NARRATION_LOG_MAX_LEN,
    PET_AP_COST_PER_PET,
    PetState,
    _level_down_border,
    _level_threshold_step,
)


def test_feed_in_sweet_spot_gains_affection_and_streak() -> None:
    state = PetState(hunger=40.0)
    state.feed()
    assert state.affection == AFFECTION_GAIN_SMALL
    assert state.affection_care_streak_count == 1
    assert state.affection_care_streak_days == 1


def test_feed_outside_sweet_spot_gains_no_affection() -> None:
    state = PetState(hunger=90.0)
    state.feed()
    assert state.affection == 0.0
    assert state.affection_care_streak_count == 0


def test_overfeed_penalty_lowers_mood_and_affection_and_resets_streak() -> None:
    state = PetState(mood=50.0, affection=5.0)
    state.affection_care_streak_count = 3
    state.affection_care_streak_days = 2
    state.overfeed_penalty()
    assert state.mood == 45.0
    assert state.affection < 5.0
    assert state.affection_care_streak_count == 0
    assert state.affection_care_streak_days == 0


def test_pet_consumes_ap_and_reduces_gain_as_ap_depletes() -> None:
    state = PetState(mood=50.0, pet_ap=100.0)
    state.pet(amount=10.0)
    first_gain = state.mood - 50.0
    assert first_gain > 0
    assert state.pet_ap == 100.0 - PET_AP_COST_PER_PET

    mood_before_second = state.mood
    state.pet(amount=10.0)
    second_gain = state.mood - mood_before_second
    # pet_apが減った分、2回目の回復量は1回目より少なくなるはず
    assert second_gain < first_gain


def test_pet_with_zero_ap_gives_no_mood_and_lowers_affection() -> None:
    state = PetState(mood=50.0, pet_ap=0.0, affection=5.0)
    overpetted = state.pet(amount=10.0)
    assert overpetted is True
    assert state.mood == 50.0
    assert state.affection < 5.0


def test_pet_with_ap_returns_false() -> None:
    state = PetState(mood=50.0, pet_ap=100.0)
    overpetted = state.pet(amount=10.0)
    assert overpetted is False


def test_affection_gain_levels_up_and_resets_level_down_border() -> None:
    state = PetState(level=1, affection=0.0)
    threshold = _level_threshold_step(1)
    state._apply_affection_delta(threshold, reason="テスト")
    assert state.level == 2
    assert state.affection == 0.0
    assert state.level_down_remaining == _level_down_border(2)


def test_level_down_requires_border_to_be_exhausted() -> None:
    state = PetState(level=2, affection=0.0)
    border = _level_down_border(2)
    state.level_down_remaining = border
    # ボーダー未満の減少ではレベルは下がらない
    state._apply_affection_delta(-(border - 1), reason="テスト")
    assert state.level == 2
    # 残りを使い切るとレベルが下がる
    state._apply_affection_delta(-1, reason="テスト")
    assert state.level == 1


def test_level_up_does_not_carry_over_previous_level_down_remaining() -> None:
    state = PetState(level=1, affection=0.0)
    state.level_down_remaining = 1.0  # 直前レベルでほぼ使い切っていた状態
    threshold = _level_threshold_step(1)
    state._apply_affection_delta(threshold, reason="テスト")
    assert state.level == 2
    assert state.level_down_remaining == _level_down_border(2)


def test_stamina_decays_while_overfed() -> None:
    state = PetState(hunger=90.0, stamina=100.0)
    future = state.virtual_now() + timedelta(minutes=1)
    state.apply_time_decay(now=future)
    assert state.stamina < 100.0


def test_stamina_does_not_decay_when_not_overfed() -> None:
    state = PetState(hunger=50.0, stamina=100.0)
    future = state.virtual_now() + timedelta(minutes=60)
    state.apply_time_decay(now=future)
    assert state.stamina == 100.0


def test_attention_event_not_active_by_default() -> None:
    state = PetState()
    assert state.is_attention_event_active() is False


def test_attention_event_active_until_deadline() -> None:
    state = PetState()
    state.attention_event_until = (state.virtual_now() + timedelta(minutes=5)).isoformat()
    assert state.is_attention_event_active() is True


def test_attention_event_expired_is_inactive() -> None:
    state = PetState()
    state.attention_event_until = (state.virtual_now() - timedelta(minutes=1)).isoformat()
    assert state.is_attention_event_active() is False


def test_feed_during_attention_event_gives_bonus_and_consumes_event() -> None:
    state = PetState(hunger=40.0)
    state.attention_event_until = (state.virtual_now() + timedelta(minutes=5)).isoformat()
    state.feed()
    assert state.affection == AFFECTION_GAIN_SMALL * ATTENTION_EVENT_BONUS_MULTIPLIER
    assert state.is_attention_event_active() is False


def test_feed_appends_narration() -> None:
    state = PetState(hunger=40.0)
    state.feed()
    assert state.narration_log
    assert any("満腹度" in entry.text for entry in state.narration_log)


def test_narration_log_is_capped_at_max_len() -> None:
    state = PetState()
    for i in range(NARRATION_LOG_MAX_LEN + 10):
        state.push_narration(f"entry {i}")
    assert len(state.narration_log) == NARRATION_LOG_MAX_LEN
    assert state.narration_log[-1].text == f"entry {NARRATION_LOG_MAX_LEN + 9}"


def test_narration_entry_has_timestamp() -> None:
    state = PetState()
    state.push_narration("test entry")
    assert state.narration_log[-1].timestamp


def test_narration_seq_keeps_increasing_after_log_is_capped() -> None:
    """件数が上限に達した後も、seqは単調増加し続ける（UI側の新規検知の前提）。"""
    state = PetState()
    for i in range(NARRATION_LOG_MAX_LEN + 10):
        state.push_narration(f"entry {i}")
    assert len(state.narration_log) == NARRATION_LOG_MAX_LEN
    seqs = [entry.seq for entry in state.narration_log]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    assert state.narration_log[-1].seq == NARRATION_LOG_MAX_LEN + 10


def test_level_up_appends_narration() -> None:
    state = PetState(level=1, affection=0.0)
    threshold = _level_threshold_step(1)
    state._apply_affection_delta(threshold, reason="テスト")
    assert any("レベル" in entry.text for entry in state.narration_log)


def test_overpet_appends_narration() -> None:
    state = PetState(mood=50.0, pet_ap=0.0)
    state.pet()
    assert any("うんざり" in entry.text for entry in state.narration_log)
