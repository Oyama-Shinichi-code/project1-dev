"""睡眠機能(PetState)のテスト。詳細仕様はrequirements_drafts/sleep_feature_spec.md参照。"""
from __future__ import annotations

from datetime import timedelta

from desktop_pet.pet_state import (
    SLEEP_DEFAULT_DURATION_MINUTES,
    SLEEP_FULL_HUNGER_DURATION_MINUTES,
    SLEEP_WAKE_UP_MOOD_PENALTY,
    PetState,
    _random_sleep_probability,
)


def test_random_sleep_probability_decreases_with_level() -> None:
    assert _random_sleep_probability(1) > _random_sleep_probability(10) > _random_sleep_probability(20)
    assert _random_sleep_probability(30) == 0.0
    assert _random_sleep_probability(40) == 0.0


def test_start_sleep_debug_sets_sleeping_flag() -> None:
    state = PetState(hunger=50.0)
    state.start_sleep_debug()
    assert state.is_sleeping is True
    assert state.sleep_duration_minutes == SLEEP_DEFAULT_DURATION_MINUTES


def test_start_sleep_with_full_hunger_gives_bonus() -> None:
    state = PetState(hunger=100.0, mood=50.0, affection=0.0)
    state.start_sleep_debug()
    assert state.sleep_duration_minutes == SLEEP_FULL_HUNGER_DURATION_MINUTES
    assert state.sleep_stamina_recovery_multiplier == 2.0
    assert state.sleep_hunger_decay_multiplier == 1.0
    assert state.mood == 60.0
    assert state.affection == 2.0


def test_sleep_recovers_stamina_over_time() -> None:
    state = PetState(stamina=0.0, hunger=50.0)
    state.start_sleep_debug()
    future = state.virtual_now() + timedelta(minutes=30)
    state.apply_time_decay(now=future)
    assert state.stamina > 0.0
    assert state.is_sleeping is True  # まだ60分経っていないので寝たまま


def test_sleep_wakes_up_naturally_after_duration() -> None:
    state = PetState(stamina=0.0, hunger=50.0)
    state.start_sleep_debug()
    future = state.virtual_now() + timedelta(minutes=SLEEP_DEFAULT_DURATION_MINUTES + 5)
    state.apply_time_decay(now=future)
    assert state.is_sleeping is False


def test_mood_does_not_change_while_sleeping() -> None:
    state = PetState(mood=50.0, hunger=50.0, stamina=50.0)
    state.start_sleep_debug()
    future = state.virtual_now() + timedelta(minutes=10)
    state.apply_time_decay(now=future)
    assert state.mood == 50.0


def test_hunger_decays_slower_while_sleeping() -> None:
    normal_state = PetState(hunger=80.0)
    sleeping_state = PetState(hunger=80.0)
    sleeping_state.start_sleep_debug()

    future = normal_state.virtual_now() + timedelta(minutes=60)
    normal_state.apply_time_decay(now=future)
    sleeping_state.apply_time_decay(now=future)

    normal_loss = 80.0 - normal_state.hunger
    sleeping_loss = 80.0 - sleeping_state.hunger
    assert sleeping_loss < normal_loss


def test_wake_up_by_action_applies_penalty() -> None:
    state = PetState(mood=50.0, affection=10.0)
    state.start_sleep_debug()
    woke = state.wake_up_by_action()
    assert woke is True
    assert state.is_sleeping is False
    assert state.mood == 50.0 - SLEEP_WAKE_UP_MOOD_PENALTY


def test_wake_up_by_action_does_nothing_when_not_sleeping() -> None:
    state = PetState()
    woke = state.wake_up_by_action()
    assert woke is False


def test_hunger_reaching_zero_forces_wake_up() -> None:
    state = PetState(hunger=0.1)
    state.start_sleep_debug()
    future = state.virtual_now() + timedelta(minutes=10)
    state.apply_time_decay(now=future)
    assert state.is_sleeping is False


def test_bedtime_disabled_below_min_level() -> None:
    state = PetState(level=5, hunger=50.0)
    state.set_bedtime(22, 0)
    assert state._next_bedtime_after(state.virtual_now()) is None


def test_bedtime_enabled_at_min_level() -> None:
    state = PetState(level=10, hunger=50.0)
    state.set_bedtime(22, 0)
    next_bedtime = state._next_bedtime_after(state.virtual_now())
    assert next_bedtime is not None
