"""Adapter between Home Assistant and the pure engine.

Responsibilities (ENGINE_SPEC §1 normalization, §4 enforcement):

- Normalize the configured input entities into an
  :class:`~.core.model.InputSnapshot` on every relevant state change.
- Feed physical light-state reports into the budget ledger (rule 2.2).
- Reconcile the physical switch to the engine's ``want_on`` (rule 4.1),
  as a single writer, idempotently (rule 4.2).
- Keep exactly one timer armed for the decision's ``next_review``
  (rule 3.2), tightened to a publish cadence while the light burns so
  the lit-hours sensor keeps moving between events.
- Fan out updates to entities over a per-entry dispatcher signal.

The controller stamps every event with ``dt_util.now()`` (local time —
the plant-day anchor is a local-clock concept) on arrival, which keeps
the engine's monotonic-time requirement satisfied.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

from .config import Config
from .const import DOMAIN, PUBLISH_INTERVAL_S
from .core.engine import Engine
from .core.model import Decision, InputSnapshot

# media_player states that mean "someone is actively watching/listening".
_ACTIVE_MEDIA_STATES = {"playing", "paused", "buffering", "on"}
_UNKNOWN_STATES = {"unknown", "unavailable"}


def normalize_signal(state: State | None) -> bool | None:
    """Map an entity state onto a tri-state signal (rule 1.8 leaves the
    fail-safe interpretation of ``None`` to the core).

    Domain-aware: zones and numeric sensors count occupants, person and
    device_tracker entities are truthy at home, media players are truthy
    while actively playing, everything else follows on/off.
    """
    if state is None or state.state in _UNKNOWN_STATES:
        return None
    domain = state.entity_id.split(".", 1)[0]
    value = state.state
    if domain in ("person", "device_tracker"):
        return value == "home"
    if domain == "media_player":
        return value in _ACTIVE_MEDIA_STATES
    if value in ("on", "off"):
        return value == "on"
    try:
        return float(value) > 0  # zone.home occupant count, numeric sensors
    except ValueError:
        return None


def normalize_light(state: State | None) -> bool | None:
    """The physical light state; None while unknown (rule 2.2 accrues nothing)."""
    if state is None or state.state in _UNKNOWN_STATES:
        return None
    return state.state == "on"


class GrowConductorController:
    """Single writer for one grow light (one config entry)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, config: Config) -> None:
        self.hass = hass
        self.entry = entry
        self.config = config
        self.engine = Engine(config.tunables)
        self.signal = f"{DOMAIN}_{entry.entry_id}"
        self._armed = False  # no commands until restores have been applied
        self._unsubs: list[callback] = []
        self._timer_unsub: callback | None = None
        self._timer_at: datetime | None = None

    # -- lifecycle ------------------------------------------------------------

    async def async_start(self) -> None:
        """Subscribe and take the first (command-less) decision."""
        if self.config.input_entities:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, self.config.input_entities, self._on_input_event
                )
            )
        if self.config.trigger_entities:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, self.config.trigger_entities, self._on_trigger_event
                )
            )
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, [self.config.light_entity], self._on_light_event
            )
        )
        now = dt_util.now()
        self.engine.light_reported(self._read_light(), now)
        decision = self.engine.handle_snapshot(self._build_snapshot(), now)
        self._after_decision(decision, now)

    @callback
    def arm(self) -> None:
        """Start enforcing (rule 4.1) — called once entity restores are in.

        Restores (enabled flag, target hours, budget seed) are pushed into
        the engine while the platforms load; enforcing before they land
        could flash the light on stale defaults.
        """
        self._armed = True
        now = dt_util.now()
        self._after_decision(self.engine.tick(now), now)

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_timer()

    # -- entity-facing commands -------------------------------------------------

    @callback
    def set_enabled(self, enabled: bool) -> None:
        now = dt_util.now()
        self._after_decision(self.engine.set_enabled(enabled, now), now)

    @callback
    def set_target(self, hours: float) -> None:
        now = dt_util.now()
        self._after_decision(self.engine.set_target(hours, now), now)

    @callback
    def seed_budget(self, day_start: datetime, spent_s: float) -> bool:
        """Restore the persisted plant-day ledger (rule 5.1)."""
        now = dt_util.now()
        adopted = self.engine.seed_budget(day_start, spent_s, now)
        self._after_decision(self.engine.tick(now), now)
        return adopted

    # -- input plumbing ------------------------------------------------------------

    def _state(self, entity_id: str) -> State | None:
        return self.hass.states.get(entity_id)

    def _build_snapshot(self) -> InputSnapshot:
        def any_active(entities: tuple[str, ...]) -> bool:
            return any(normalize_signal(self._state(e)) is True for e in entities)

        return InputSnapshot(
            asleep=(
                normalize_signal(self._state(self.config.sleep_entity))
                if self.config.sleep_entity
                else None
            ),
            anyone_home=(
                normalize_signal(self._state(self.config.home_entity))
                if self.config.home_entity
                else None
            ),
            viewer_active=any_active(self.config.viewer_entities),
            refuge_active=any_active(self.config.refuge_entities),
            veto_active=any_active(self.config.veto_entities),
        )

    def _read_light(self) -> bool | None:
        return normalize_light(self._state(self.config.light_entity))

    @callback
    def _on_input_event(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.now()
        self._after_decision(self.engine.handle_snapshot(self._build_snapshot(), now), now)

    @callback
    def _on_trigger_event(self, event: Event[EventStateChangedData]) -> None:
        """Rule 1.3b: real transitions pulse the activity clock; the level,
        unknown flaps, and attribute-only writes never do."""
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if old is None or new is None:
            return
        if old.state in _UNKNOWN_STATES or new.state in _UNKNOWN_STATES:
            return
        if old.state == new.state:
            return
        now = dt_util.now()
        self._after_decision(self.engine.activity_pulse(now), now)

    @callback
    def _on_light_event(self, event: Event[EventStateChangedData]) -> None:
        now = dt_util.now()
        self._after_decision(self.engine.light_reported(self._read_light(), now), now)

    # -- decisions out ----------------------------------------------------------------

    @callback
    def _on_timer(self, when: datetime) -> None:
        self._timer_unsub = None
        self._timer_at = None
        now = dt_util.now()
        self._after_decision(self.engine.tick(now), now)

    @callback
    def _after_decision(self, decision: Decision, now: datetime) -> None:
        self._enforce(decision)
        self._schedule_review(decision, now)
        async_dispatcher_send(self.hass, self.signal)

    @callback
    def _enforce(self, decision: Decision) -> None:
        """Rule 4.1/4.2: command only while armed+enabled, only on a real delta."""
        if not self._armed or not self.engine.enabled:
            return
        actual = self.engine.light_on
        if actual is None or actual == decision.want_on:
            return
        self.hass.async_create_task(
            self.hass.services.async_call(
                "homeassistant",
                "turn_on" if decision.want_on else "turn_off",
                {"entity_id": self.config.light_entity},
            )
        )

    @callback
    def _schedule_review(self, decision: Decision, now: datetime) -> None:
        target = decision.next_review
        if self.engine.light_on is True:
            publish_at = now + timedelta(seconds=PUBLISH_INTERVAL_S)
            target = min(target, publish_at) if target else publish_at
        if target is None or target <= now:
            self._cancel_timer()
            return
        if self._timer_at == target:
            return
        self._cancel_timer()
        self._timer_at = target
        self._timer_unsub = async_track_point_in_time(self.hass, self._on_timer, target)

    @callback
    def _cancel_timer(self) -> None:
        if self._timer_unsub is not None:
            self._timer_unsub()
            self._timer_unsub = None
        self._timer_at = None
