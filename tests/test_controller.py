"""Adapter normalization (ENGINE_SPEC §1 input mapping, rule 1.8)."""

from __future__ import annotations

from homeassistant.core import State

from custom_components.grow_conductor.controller import normalize_light, normalize_signal


def test_unknown_and_unavailable_are_none() -> None:
    assert normalize_signal(None) is None
    assert normalize_signal(State("binary_sensor.x", "unavailable")) is None
    assert normalize_signal(State("binary_sensor.x", "unknown")) is None
    assert normalize_light(None) is None
    assert normalize_light(State("switch.x", "unavailable")) is None


def test_binary_domains() -> None:
    assert normalize_signal(State("binary_sensor.x", "on")) is True
    assert normalize_signal(State("input_boolean.x", "off")) is False
    assert normalize_signal(State("switch.x", "on")) is True


def test_zone_counts_occupants() -> None:
    assert normalize_signal(State("zone.home", "0")) is False
    assert normalize_signal(State("zone.home", "2")) is True


def test_person_and_tracker_are_home_truthy() -> None:
    assert normalize_signal(State("person.leik", "home")) is True
    assert normalize_signal(State("person.leik", "not_home")) is False
    assert normalize_signal(State("device_tracker.phone", "home")) is True
    assert normalize_signal(State("device_tracker.phone", "work")) is False


def test_media_player_active_states() -> None:
    """A playing/paused TV is a watcher; off/standby/idle is not."""
    for active in ("playing", "paused", "buffering", "on"):
        assert normalize_signal(State("media_player.tv", active)) is True
    for inactive in ("off", "standby", "idle"):
        assert normalize_signal(State("media_player.tv", inactive)) is False


def test_unparseable_states_are_none() -> None:
    assert normalize_signal(State("sensor.weird", "banana")) is None


def test_light_state() -> None:
    assert normalize_light(State("switch.x", "on")) is True
    assert normalize_light(State("switch.x", "off")) is False
