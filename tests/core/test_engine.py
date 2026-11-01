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

    # Office still occupied just before the coffee run (in reality the
    # publish tick and sensor churn keep bumping refuge evidence).
    d = engine.tick(at(6, 11, 58))
    assert d.want_on

    # Coffee run at 12:00 (rule 1.3c): kitchen viewer lights up AND the
    # office sensor decays — the light STAYS ON, exposure review at 12:05.
    d = engine.handle_snapshot(
        snap(asleep=False, anyone_home=True, viewer_active=True), at(6, 12, 0)
    )
    assert d.want_on and d.reason is Reason.REFUGE
    assert d.next_review == at(6, 12, 5)

    # Back toward the desk at 12:03: episode stayed under exposure_grace,
    # so no cut ever happened and no hold applies (still on refuge hold).
    d = engine.handle_snapshot(base, at(6, 12, 3))
    assert d.want_on and d.reason is Reason.REFUGE
    d = engine.handle_snapshot(refuge, at(6, 12, 4))
    assert d.want_on and d.reason is Reason.REFUGE
    assert engine.light_on is True  # never toggled through the whole trip


def test_sustained_exposure_in_refuge_cuts_at_grace() -> None:
    """Rule 1.3c: settling within sight still cuts, with the normal hold."""
    engine = Engine()
    both = snap(asleep=False, anyone_home=True, refuge_active=True, viewer_active=True)
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    engine.handle_snapshot(refuge, at(6, 9, 0))
    d = engine.tick(at(6, 9, 3))
    d = follow(engine, d, at(6, 9, 3))
    assert d.want_on

    # Someone settles in the living room at 12:00 while the office stays
    # occupied: tolerated until 12:05, then OBSERVED.
    d = engine.handle_snapshot(both, at(6, 12, 0))
    assert d.want_on and d.next_review == at(6, 12, 5)
    d = engine.tick(at(6, 12, 5))
    assert not d.want_on and d.state is LightState.OBSERVED and d.reason is Reason.VIEWERS
    d = follow(engine, d, at(6, 12, 5))

    # They leave at 12:20: sustained episode imposes the clear_hold.
    d = engine.handle_snapshot(refuge, at(6, 12, 20))
    assert d.state is LightState.COOLDOWN
    assert d.next_review == at(6, 12, 30)
    d = engine.tick(at(6, 12, 30))
    assert d.want_on and d.reason is Reason.REFUGE


def test_refuge_holds_across_gaps_and_releases_after_hold() -> None:
    """Rule 1.7: confirmed refuge survives dropouts up to refuge_hold."""
    engine = Engine()
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    base = snap(asleep=False, anyone_home=True)
    engine.handle_snapshot(refuge, at(6, 9, 0))
    d = engine.tick(at(6, 9, 3))
    d = follow(engine, d, at(6, 9, 3))
    assert d.want_on

    # Sensor decays at 10:00: held, with the lapse instant as the review.
    d = engine.handle_snapshot(base, at(6, 10, 0))
    assert d.want_on and d.reason is Reason.REFUGE
    assert d.next_review == at(6, 10, 10)

    # Reactivation within the hold: no re-confirmation needed.
    d = engine.handle_snapshot(refuge, at(6, 10, 5))
    assert d.want_on and d.reason is Reason.REFUGE

    # A gap that outlives the hold releases refuge.
    d = engine.handle_snapshot(base, at(6, 10, 6))
    d = engine.tick(at(6, 10, 16))
    assert not d.want_on and d.state is LightState.OBSERVED and d.reason is Reason.AWAKE_HOME

    # Re-engagement afterwards must re-confirm from zero (rule 1.7).
    d = engine.handle_snapshot(refuge, at(6, 10, 20))
    assert not d.want_on and d.next_review == at(6, 10, 23)


def test_unconfirmed_refuge_dropout_resets_confirmation() -> None:
    """Rule 1.7: while unconfirmed, any gap restarts the clock."""
    engine = Engine()
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    base = snap(asleep=False, anyone_home=True)
    engine.handle_snapshot(refuge, at(6, 9, 0))
    engine.handle_snapshot(base, at(6, 9, 1))
    d = engine.handle_snapshot(refuge, at(6, 9, 2))
    assert not d.want_on
    assert d.next_review == at(6, 9, 5)  # confirmation restarted at 9:02


def test_trigger_pulse_cuts_during_refuge() -> None:
    """Rule 1.3b: the bedroom door cuts even inside confirmed refuge.

    Regression for the 2026-10-31 23:04 incident: the door opened while
    the light burned for refuge (office occupied) and nothing happened.
    """
    engine = Engine()
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    engine.handle_snapshot(refuge, at(6, 9, 0))
    d = engine.tick(at(6, 9, 3))
    d = follow(engine, d, at(6, 9, 3))
    assert d.want_on

    d = engine.activity_pulse(at(6, 11, 0))
    assert not d.want_on and d.state is LightState.COOLDOWN
    assert d.next_review == at(6, 11, 10)
    d = follow(engine, d, at(6, 11, 0))

    # Refuge is still confirmed: the light returns after the clear_hold.
    d = engine.tick(at(6, 11, 10))
    assert d.want_on and d.reason is Reason.REFUGE


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


# -- rule 4.4: manual override ------------------------------------------------


def lit_asleep(engine: Engine, now: datetime) -> Decision:
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), now)
    d = follow(engine, d, now)
    assert d.want_on and d.reason is Reason.ASLEEP
    return d


def test_manual_off_sticks_until_the_household_wakes() -> None:
    """The 2026-11-01 morning: someone is up while sleep mode is still on.

    Under the strict single writer every HomeKit tap was reverted within
    ~260 ms; now the tap holds through viewer blips and cooldowns, and
    only waking (a context change) hands control back.
    """
    engine = Engine(target_hours=12.0)
    lit_asleep(engine, at(5, 23))

    d = engine.light_reported(False, at(6, 8, 18), manual=True)
    assert not d.want_on and d.state is LightState.MANUAL and d.reason is Reason.MANUAL_OFF
    assert engine.override is not None and engine.override.context is Reason.ASLEEP

    # Sofa sighting, then quiet: without the override this relit at 08:31.
    d = engine.handle_snapshot(
        snap(asleep=True, anyone_home=True, viewer_active=True), at(6, 8, 19)
    )
    assert d.state is LightState.MANUAL
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), at(6, 8, 21))
    d = engine.tick(at(6, 8, 31))
    assert not d.want_on and d.state is LightState.MANUAL
    d = engine.activity_pulse(at(6, 8, 32))
    d = engine.tick(at(6, 9, 30))
    assert not d.want_on and d.state is LightState.MANUAL

    # Sleep mode turns off at 09:45: released; awake at home is OBSERVED anyway.
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True), at(6, 9, 45))
    assert engine.override is None
    assert not d.want_on and d.state is LightState.OBSERVED and d.reason is Reason.AWAKE_HOME

    # Leaving later: the conductor is fully back in charge.
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=False), at(6, 11, 0))
    assert d.want_on and d.reason is Reason.AWAY


def test_flipping_back_hands_control_back() -> None:
    """A manual flip that agrees with the verdict releases the override."""
    engine = Engine(target_hours=12.0)
    lit_asleep(engine, at(5, 23))
    engine.light_reported(False, at(6, 2, 0), manual=True)
    assert engine.override is not None

    d = engine.light_reported(True, at(6, 2, 5), manual=True)
    assert engine.override is None
    assert d.want_on and d.state is LightState.LIT and d.reason is Reason.ASLEEP


def test_manual_on_while_observed_holds_until_context_changes() -> None:
    """Manual control works both ways; budget still accrues (rule 2.2)."""
    engine = Engine(target_hours=12.0)
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True, veto_active=True), at(5, 20))
    d = follow(engine, engine.light_reported(False, at(5, 20)), at(5, 20))
    assert not d.want_on

    d = engine.light_reported(True, at(5, 20, 0), manual=True)
    assert d.want_on and d.state is LightState.MANUAL and d.reason is Reason.MANUAL_ON

    # The veto clearing and returning is not a context change.
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True), at(5, 20, 30))
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True, veto_active=True), at(5, 21))
    assert d.want_on and d.state is LightState.MANUAL
    assert engine.spent_s(at(5, 21)) == 1 * H

    # Bedtime: context asleep → released, and the engine wants it on anyway.
    d = engine.handle_snapshot(snap(asleep=True, anyone_home=True), at(5, 21, 30))
    assert engine.override is None
    assert d.want_on and d.state is LightState.LIT


def test_manual_flip_that_agrees_latches_nothing() -> None:
    engine = Engine(target_hours=12.0)
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True), at(5, 20))
    engine.light_reported(True, at(5, 20), manual=False)  # some earlier state
    d = engine.light_reported(False, at(5, 20, 1), manual=True)
    assert engine.override is None
    assert not d.want_on and d.state is LightState.OBSERVED


def test_non_flips_never_latch() -> None:
    """Only a known→known change can be manual (rule 4.5)."""
    engine = Engine(target_hours=12.0)
    lit_asleep(engine, at(5, 23))
    engine.light_reported(True, at(5, 23, 1), manual=True)  # redundant report
    assert engine.override is None
    engine.light_reported(None, at(5, 23, 2), manual=True)  # unavailable
    engine.light_reported(False, at(5, 23, 3), manual=True)  # recovery, not a flip
    assert engine.override is None


def test_enabled_switch_releases_and_standby_ignores_flips() -> None:
    engine = Engine(target_hours=12.0)
    lit_asleep(engine, at(5, 23))
    engine.light_reported(False, at(6, 1, 0), manual=True)
    assert engine.override is not None

    d = engine.set_enabled(False, at(6, 1, 1))
    assert engine.override is None and d.state is LightState.STANDBY
    d = engine.light_reported(True, at(6, 1, 2), manual=True)
    assert engine.override is None and d.state is LightState.STANDBY

    # Re-enabled: plain engine control, no stale latch.
    d = engine.set_enabled(True, at(6, 1, 3))
    assert d.want_on and d.state is LightState.LIT


def test_override_keeps_reviewing_context_changes() -> None:
    """A refuge lapse is a timed context change; the override must see it."""
    engine = Engine(target_hours=12.0)
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    engine.handle_snapshot(refuge, at(6, 9, 0))
    d = follow(engine, engine.tick(at(6, 9, 3)), at(6, 9, 3))
    assert d.want_on and d.reason is Reason.REFUGE

    d = engine.light_reported(False, at(6, 10, 0), manual=True)
    assert d.state is LightState.MANUAL
    # Office empties at 10:30; refuge lapses at 10:40 (refuge_hold).
    d = engine.handle_snapshot(snap(asleep=False, anyone_home=True), at(6, 10, 30))
    assert d.state is LightState.MANUAL and d.next_review == at(6, 10, 40)
    d = engine.tick(at(6, 10, 40))
    assert engine.override is None and d.state is LightState.OBSERVED

    # A fresh refuge later is a new occasion: it lights again.
    engine.handle_snapshot(refuge, at(6, 13, 0))
    d = engine.tick(at(6, 13, 3))
    assert d.want_on and d.reason is Reason.REFUGE


def test_trigger_pulse_cuts_during_a_tolerated_refuge_episode() -> None:
    """Replay of 2026-10-31 23:03-23:09: someone walks through the living
    room (short, tolerated episode) and opens the bedroom door mid-walk.
    The door must cut at once, and the next short pass must not relight
    the light while the door's hold runs."""
    engine = Engine()
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    passing = snap(asleep=False, anyone_home=True, refuge_active=True, viewer_active=True)
    engine.handle_snapshot(refuge, at(5, 22, 40))
    d = follow(engine, engine.tick(at(5, 22, 43)), at(5, 22, 43))
    assert d.want_on and d.reason is Reason.REFUGE

    d = engine.handle_snapshot(passing, at(5, 23, 3, 27))
    assert d.want_on  # short pass: tolerated (1.3c)
    d = engine.activity_pulse(at(5, 23, 4, 4))
    assert not d.want_on and d.state is LightState.COOLDOWN
    # Earliest review: the walk-through maturing at exposure_grace (23:08:27),
    # before the door's hold expires at 23:14:04.
    assert d.next_review == at(5, 23, 8, 27)
    d = follow(engine, d, at(5, 23, 4, 4))

    d = engine.handle_snapshot(refuge, at(5, 23, 4, 32))
    assert not d.want_on and d.state is LightState.COOLDOWN
    d = engine.handle_snapshot(passing, at(5, 23, 8, 31))  # another short pass
    assert not d.want_on, "a tolerated episode must not bypass a running hold"
    d = engine.handle_snapshot(refuge, at(5, 23, 9, 3))
    d = engine.tick(at(5, 23, 14, 4))
    assert d.want_on and d.reason is Reason.REFUGE


def test_short_episode_does_not_bypass_a_sustained_episodes_hold() -> None:
    """Rule 1.3c: after a sustained cut, a quick return stays dark."""
    engine = Engine()
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    both = snap(asleep=False, anyone_home=True, refuge_active=True, viewer_active=True)
    engine.handle_snapshot(refuge, at(6, 9, 0))
    follow(engine, engine.tick(at(6, 9, 3)), at(6, 9, 3))
    engine.handle_snapshot(both, at(6, 12, 0))
    d = follow(engine, engine.tick(at(6, 12, 5)), at(6, 12, 5))
    assert not d.want_on
    engine.handle_snapshot(refuge, at(6, 12, 20))  # hold until 12:30
    d = engine.handle_snapshot(both, at(6, 12, 25))
    assert not d.want_on and d.state is LightState.COOLDOWN
    assert d.next_review == at(6, 12, 30)


def test_refuge_never_starts_a_block_in_front_of_someone() -> None:
    """Rule 3.1: 1.3c tolerance keeps a burning block, never lights one.

    Replay of 2026-11-01 11:21: refuge confirmed while someone sat on the
    sofa — v0.1.0 switched the light on in view, then cut it at the grace.
    """
    engine = Engine()
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    both = snap(asleep=False, anyone_home=True, refuge_active=True, viewer_active=True)
    engine.handle_snapshot(both, at(6, 11, 0))
    engine.light_reported(False, at(6, 11, 0))
    d = engine.tick(at(6, 11, 3))  # refuge confirmed, viewer still active
    assert not d.want_on and d.state is LightState.OBSERVED and d.reason is Reason.VIEWERS

    # Sofa clears: no hold was imposed (the episode stayed short) → lights.
    d = engine.handle_snapshot(refuge, at(6, 11, 4))
    assert d.want_on and d.reason is Reason.REFUGE
    d = follow(engine, d, at(6, 11, 4))

    # Once burning, a short pass is tolerated as before (no toggle).
    d = engine.handle_snapshot(both, at(6, 11, 30))
    assert d.want_on and d.state is LightState.LIT


def test_manual_off_during_tolerated_exposure_still_latches() -> None:
    """Rule 4.4 judges the tap against the PRE-flip wish.

    WFH block burning, partner on the sofa (short, tolerated): tapping it
    off must latch. Judged after the flip, the never-start-in-view guard
    (3.1) would read the tap as agreement and relight when the sofa clears.
    """
    engine = Engine()
    refuge = snap(asleep=False, anyone_home=True, refuge_active=True)
    both = snap(asleep=False, anyone_home=True, refuge_active=True, viewer_active=True)
    engine.handle_snapshot(refuge, at(6, 9, 0))
    follow(engine, engine.tick(at(6, 9, 3)), at(6, 9, 3))
    d = engine.handle_snapshot(both, at(6, 11, 0))
    assert d.want_on  # tolerated

    d = engine.light_reported(False, at(6, 11, 1), manual=True)
    assert d.state is LightState.MANUAL and engine.override is not None
    d = engine.handle_snapshot(refuge, at(6, 11, 2))  # sofa clears
    assert not d.want_on and d.state is LightState.MANUAL
