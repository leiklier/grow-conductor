"""Visibility verdict — ENGINE_SPEC §1 priority chain."""

from __future__ import annotations

from custom_components.grow_conductor.core.model import Reason
from custom_components.grow_conductor.core.tunables import Tunables
from custom_components.grow_conductor.core.visibility import assess

from .helpers import at, snap, timedelta

TUNABLES = Tunables()
NOW = at(5, 23, 0)


def test_veto_wins_over_everything() -> None:
    """Rule 1.2: veto beats asleep, away, refuge — and has no release hold."""
    verdict = assess(
        snap(asleep=True, anyone_home=False, refuge_active=True, veto_active=True),
        NOW,
        last_viewer_activity=None,
        refuge_since=at(5, 20, 0),
        tunables=TUNABLES,
    )
    assert not verdict.may_light
    assert verdict.reason is Reason.VETO
    # Veto released, nothing else observed: light may return immediately.
    verdict = assess(snap(asleep=True), NOW, None, None, TUNABLES)
    assert verdict.may_light
    assert verdict.reason is Reason.ASLEEP


def test_viewer_activity_observes() -> None:
    """Rule 1.3 (active half): any viewer activity means OBSERVED."""
    verdict = assess(snap(asleep=True, viewer_active=True), NOW, NOW, None, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.VIEWERS


def test_clear_hold_after_viewer_activity() -> None:
    """Rule 1.3 (hold half): UNOBSERVED waits out clear_hold, with expiry."""
    last_active = NOW - timedelta(seconds=300)
    verdict = assess(snap(asleep=True), NOW, last_active, None, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.ASLEEP  # the underlying lit-reason
    assert verdict.cooldown_until == last_active + timedelta(seconds=600)
    # Hold expired.
    verdict = assess(snap(asleep=True), NOW, NOW - timedelta(seconds=600), None, TUNABLES)
    assert verdict.may_light


def test_hold_does_not_apply_while_observed() -> None:
    """The hold only delays UNOBSERVED verdicts; OBSERVED stays plain OBSERVED."""
    verdict = assess(snap(asleep=False, anyone_home=True), NOW, NOW, None, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.AWAKE_HOME
    assert verdict.cooldown_until is None


def test_asleep_is_prime_time() -> None:
    """Rule 1.4."""
    verdict = assess(snap(asleep=True, anyone_home=True), NOW, None, None, TUNABLES)
    assert verdict.may_light
    assert verdict.reason is Reason.ASLEEP


def test_away_lights() -> None:
    """Rule 1.5."""
    verdict = assess(snap(asleep=False, anyone_home=False), NOW, None, None, TUNABLES)
    assert verdict.may_light
    assert verdict.reason is Reason.AWAY


def test_awake_home_is_observed_without_refuge() -> None:
    """Rule 1.6: no weekend latch, no exceptions."""
    verdict = assess(snap(asleep=False, anyone_home=True), NOW, None, None, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.AWAKE_HOME


def test_refuge_requires_confirmation() -> None:
    """Rule 1.7: continuous refuge for refuge_confirm before lighting."""
    since = NOW - timedelta(seconds=60)
    verdict = assess(
        snap(asleep=False, anyone_home=True, refuge_active=True), NOW, None, since, TUNABLES
    )
    assert not verdict.may_light
    assert verdict.reason is Reason.AWAKE_HOME
    assert verdict.refuge_ready_at == since + timedelta(seconds=180)

    verdict = assess(
        snap(asleep=False, anyone_home=True, refuge_active=True),
        NOW,
        None,
        NOW - timedelta(seconds=180),
        TUNABLES,
    )
    assert verdict.may_light
    assert verdict.reason is Reason.REFUGE


def test_unknowns_fail_safe() -> None:
    """Rule 1.8: unknown sleep counts as awake, unknown home as home."""
    verdict = assess(snap(), NOW, None, None, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.AWAKE_HOME
    # Unknown sleep but definitively away still lights (1.5).
    verdict = assess(snap(anyone_home=False), NOW, None, None, TUNABLES)
    assert verdict.may_light
    assert verdict.reason is Reason.AWAY
