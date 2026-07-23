"""Engine scenarios — ENGINE_SPEC §2-§5 through realistic days."""

from __future__ import annotations

from datetime import datetime

from custom_components.grow_conductor.core.engine import Engine
from custom_components.grow_conductor.core.model import Decision, LightState, Reason
from custom_components.grow_conductor.core.tunables import Tunables

from .helpers import at, snap

H = 3600.0


def follow(engine: Engine, decision: Decision, now: datetime) -> Decision:
    """Play the adapter: make the physical light match ``want_on`` (rule 4.1)."""
    if decision.want_on != (engine.light_on is True):
        return engine.light_reported(decision.want_on, now)
    return decision


def test_workday_end_to_end() -> None:
    """A full nominal workday: sleep block, morning routine, away block, cap."""
    engine = Engine(target_hours=12.0)

    # Evening at home, TV-free, someone in the living room recently.
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True, viewer_active=True), at(5, 21))
    assert d.state is LightState.OBSERVED and d.reason is Reason.VIEWERS

    # Living room clears, still awake at home: plain OBSERVED (no hold shown).
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True), at(5, 22, 50))
    assert d.state is LightState.OBSERVED and d.reason is Reason.AWAKE_HOME

    # Sleep mode on at 23:00 — viewer fell at 22:50, so cooldown until 23:00.
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), at(5, 22, 55))
    assert d.state is LightState.COOLDOWN
    assert d.next_review == at(5, 23, 0)

    # Hold expires: prime time.
    d = engine.tick(at(5, 23, 0))
    assert d.want_on and d.state is LightState.LIT and d.reason is Reason.ASLEEP
    d = follow(engine, d, at(5, 23, 0))

    # Wake at 07:00: observed immediately, light cut (morning routine covered).
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True), at(6, 7, 0))
    assert not d.want_on and d.state is LightState.OBSERVED and d.reason is Reason.AWAKE_HOME
    d = follow(engine, d, at(6, 7, 0))
    assert engine.spent_s(at(6, 7, 0)) == 8 * H

    # Leaving for work at 08:00: away block starts immediately (no viewer
    # activity was recorded on the way out in this scenario).
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=False), at(6, 8, 0))
    assert d.want_on and d.reason is Reason.AWAY
    # Remaining budget is 4 h: the decision schedules its own cap review.
    d = follow(engine, d, at(6, 8, 0))
    assert d.next_review == at(6, 12, 0)

    # Cap hits while away: sated until the next anchor.
    d = engine.tick(at(6, 12, 0))
    assert not d.want_on and d.state is LightState.SATED and d.reason is Reason.TARGET_REACHED
    assert d.next_review == at(6, 22, 0)
    d = follow(engine, d, at(6, 12, 0))

    # Anchor crossing resets the budget; still away, lights again.
    d = engine.tick(at(6, 22, 0))
    assert d.want_on and d.reason is Reason.AWAY
    assert engine.spent_s(at(6, 22, 0)) == 0.0


def test_night_movement_cuts_and_recovers() -> None:
    """Rules 1.3 + 3.3: bathroom trip cuts the light; it returns after the hold."""
    engine = Engine(target_hours=12.0)
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), at(5, 23))
    d = follow(engine, d, at(5, 23))
    assert d.want_on

    # Movement through a viewer zone at 03:00.
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True, viewer_active=True), at(6, 3, 0))
    assert not d.want_on and d.state is LightState.OBSERVED and d.reason is Reason.VIEWERS
    d = follow(engine, d, at(6, 3, 0))

    # Movement stops at 03:04 — hold runs from the falling edge.
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), at(6, 3, 4))
    assert d.state is LightState.COOLDOWN
    assert d.next_review == at(6, 3, 14)

    d = engine.tick(at(6, 3, 14))
    assert d.want_on and d.reason is Reason.ASLEEP


def test_viewer_hold_counts_from_end_of_sustained_activity() -> None:
    """Rule 1.3: activity spanning several snapshots holds from its end."""
    engine = Engine()
    engine.handle_snapshot(snap(asleep=True, viewer_active=True), at(6, 3, 0))
    # Unrelated churn while still active bumps the activity stamp.
    engine.handle_snapshot(snap(asleep=True, viewer_active=True), at(6, 3, 20))
    d = engine.handle_snapshot(snap(asleep=True), at(6, 3, 30))
    assert d.state is LightState.COOLDOWN
    assert d.next_review == at(6, 3, 40)


def test_veto_cuts_immediately_and_releases_without_hold() -> None:
    """Rule 1.2 during prime time."""
    engine = Engine()
    d = engine.handle_snapshot(snap(asleep=True), at(5, 23))
    d = follow(engine, d, at(5, 23))
    d = engine.handle_snapshot(snap(asleep=True, veto_active=True), at(6, 0))
    assert not d.want_on and d.reason is Reason.VETO
    d = follow(engine, d, at(6, 0))
    d = engine.handle_snapshot(snap(asleep=True), at(6, 0, 30))
    assert d.want_on and d.reason is Reason.ASLEEP


def test_work_from_home_via_refuge() -> None:
    """Rules 1.6 + 1.7: office presence lights the plants while awake at home."""
    engine = Engine(target_hours=12.0)
    base = snap(asleep=False, anyone_home=True)

    d = engine.handle_snapshot(base, at(6, 9, 0))
    assert d.state is LightState.OBSERVED and d.reason is Reason.AWAKE_HOME

    # Settling into the office: confirmation clock starts, review scheduled.
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    d = engine.handle_snapshot(refuge, at(6, 9, 5))
    assert not d.want_on and d.reason is Reason.AWAKE_HOME
    assert d.next_review == at(6, 9, 8)

    # Unrelated churn must not reset the confirmation clock (rule 1.7).
    d = engine.handle_snapshot(refuge, at(6, 9, 6))
    assert d.next_review == at(6, 9, 8)

    d = engine.tick(at(6, 9, 8))
    assert d.want_on and d.state is LightState.LIT and d.reason is Reason.REFUGE
    d = follow(engine, d, at(6, 9, 8))

    # Lunch: walking through a viewer zone cuts instantly...
    d = engine.handle_snapshot(
        snap(asleep=False, anyone_home=True, viewer_active=True), at(6, 12, 0)
    )
    assert not d.want_on and d.reason is Reason.VIEWERS
    d = follow(engine, d, at(6, 12, 0))
    # ...and refuge dropped with it, so back to square one when it clears.
    d = engine.handle_snapshot(base, at(6, 12, 28))
    assert d.state is LightState.OBSERVED and d.reason is Reason.AWAKE_HOME

    # Back at the desk: confirm again, then wait out the viewer hold
    # (viewer fell at 12:28, so the hold outlives the refuge confirmation).
    d = engine.handle_snapshot(refuge, at(6, 12, 30))
    d = engine.tick(at(6, 12, 33))
    assert d.state is LightState.COOLDOWN
    assert d.next_review == at(6, 12, 38)
    d = engine.tick(at(6, 12, 38))
    assert d.want_on and d.reason is Reason.REFUGE


def test_refuge_release_is_immediate() -> None:
    """Rule 1.7: losing refuge evidence goes straight to OBSERVED."""
    engine = Engine()
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    engine.handle_snapshot(refuge, at(6, 9, 0))
    d = engine.tick(at(6, 9, 3))
    d = follow(engine, d, at(6, 9, 3))
    assert d.want_on
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True), at(6, 10, 0))
    assert not d.want_on and d.state is LightState.OBSERVED


def test_cap_is_exact_and_min_block_guards_restarts() -> None:
    """Rules 2.3 + 2.5."""
    engine = Engine(target_hours=1.0, tunables=Tunables(min_block_s=900))
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=False), at(5, 23, 0))
    d = follow(engine, d, at(5, 23, 0))
    assert d.next_review == at(6, 0, 0)  # cap after exactly 1 h

    # A burning block runs exactly to the cap, even past min_block.
    d = engine.tick(at(6, 0, 0))
    assert not d.want_on and d.state is LightState.SATED and d.reason is Reason.TARGET_REACHED
    d = follow(engine, d, at(6, 0, 0))

    # Manual light later in the day eats into nothing — already sated.
    assert engine.spent_s(at(6, 1, 0)) == H

    # Next day with target lowered so headroom < min_block from the start:
    # 10 minutes of manual burn leaves 5 < 15 min headroom.
    engine.set_target(0.25, at(6, 23, 0))
    engine.light_reported(True, at(6, 23, 0))
    engine.light_reported(False, at(6, 23, 10))
    d = engine.tick(at(6, 23, 10))
    assert not d.want_on and d.state is LightState.SATED and d.reason is Reason.LOW_HEADROOM


def test_manual_light_consumes_budget() -> None:
    """Rules 2.2 + 4.3: external on-time counts, even while disabled."""
    engine = Engine(target_hours=2.0)
    d = engine.set_enabled(False, at(5, 22, 30))
    assert d.state is LightState.STANDBY and not d.want_on

    # Someone shows the plants to guests for an hour, manually.
    engine.light_reported(True, at(5, 23, 0))
    d = engine.light_reported(False, at(6, 0, 0))
    assert d.state is LightState.STANDBY  # still no commands while disabled

    # Re-enable during sleep: only one hour of headroom remains.
    d = engine.set_enabled(True, at(6, 1, 0))
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), at(6, 1, 0))
    assert d.want_on
    d = follow(engine, d, at(6, 1, 0))
    assert d.next_review == at(6, 2, 0)  # cap: 1 h left of the 2 h target


def test_target_clamped_and_zero_target_is_sated() -> None:
    """§6 clamp; rule 2.3 with target 0."""
    engine = Engine()
    engine.set_target(30.0, at(5, 23))
    assert engine.target_hours == 20.0
    d = engine.set_target(0.0, at(5, 23))
    assert engine.target_hours == 0.0
    d = engine.handle_snapshot(snap(asleep=True), at(5, 23, 5))
    assert not d.want_on and d.state is LightState.SATED


def test_decisions_are_idempotent() -> None:
    """Rule 4.2: unchanged inputs produce equal decisions."""
    engine = Engine()
    s = snap(asleep=True, anyone_home=True)
    first = engine.handle_snapshot(s, at(5, 23, 0))
    again = engine.handle_snapshot(s, at(5, 23, 0))
    assert first == again
    assert engine.light_reported(None, at(5, 23, 0)) == first


def test_seed_budget_restores_current_day_only() -> None:
    """Rule 5.1 through the engine surface."""
    engine = Engine(target_hours=12.0)
    assert engine.seed_budget(at(5, 22), 11.9 * H, now=at(6, 8, 0))
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=False), at(6, 8, 0))
    # 6 min headroom < min_block: not worth a restart dribble.
    assert not d.want_on and d.reason is Reason.LOW_HEADROOM

    stale = Engine(target_hours=12.0)
    assert not stale.seed_budget(at(3, 22), 11.9 * H, now=at(6, 8, 0))
    d = stale.handle_snapshot(snap(asleep=False, anyone_home=False), at(6, 8, 0))
    assert d.want_on  # fresh day, full budget


def test_restart_during_sleep_lights_without_hold() -> None:
    """Rule 5.2: no viewer memory across restarts."""
    engine = Engine()
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), at(6, 2, 0))
    assert d.want_on


def test_next_review_defaults_to_next_anchor() -> None:
    """Rule 3.2: even a stable OBSERVED decision reviews at the anchor."""
    engine = Engine()
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True), at(6, 9, 0))
    assert d.next_review == at(6, 22, 0)


def test_anchor_split_keeps_burning_block() -> None:
    """Rule 2.4 through the engine: block spanning the anchor is split."""
    engine = Engine(target_hours=12.0)
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=False), at(5, 20, 0))
    d = follow(engine, d, at(5, 20, 0))
    assert d.want_on
    # At 21:59 the old day has 1:59 spent; at 22:01 the new day has 0:01.
    assert engine.spent_s(at(5, 21, 59)) == 119 * 60
    assert engine.spent_s(at(5, 22, 1)) == 60
    d = engine.tick(at(5, 22, 1))
    assert d.want_on  # still burning, fresh budget


def test_trigger_pulse_cuts_and_recovers() -> None:
    """Rule 1.3b: a door-open pulse cuts instantly, relights after the hold."""
    engine = Engine(target_hours=12.0)
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), at(5, 23))
    d = follow(engine, d, at(5, 23))
    assert d.want_on

    d = engine.activity_pulse(at(6, 3, 0))
    assert not d.want_on and d.state is LightState.COOLDOWN
    assert d.next_review == at(6, 3, 10)
    d = follow(engine, d, at(6, 3, 0))

    # Repeated pulses (door swings) extend the hold from the last one.
    d = engine.activity_pulse(at(6, 3, 5))
    assert d.state is LightState.COOLDOWN
    assert d.next_review == at(6, 3, 15)

    d = engine.tick(at(6, 3, 15))
    assert d.want_on and d.reason is Reason.ASLEEP


def test_trigger_pulse_while_observed_still_arms_the_hold() -> None:
    """Rule 1.3b: a pulse while awake matters once the household sleeps."""
    engine = Engine()
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True), at(5, 22, 50))
    assert d.state is LightState.OBSERVED
    d = engine.activity_pulse(at(5, 22, 55))
    assert d.state is LightState.OBSERVED  # still just observed, no change

    # Sleep three minutes later: the pulse's hold is still running.
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), at(5, 22, 58))
    assert d.state is LightState.COOLDOWN
    assert d.next_review == at(5, 23, 5)
