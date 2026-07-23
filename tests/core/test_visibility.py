"""Visibility verdict — ENGINE_SPEC §1 priority chain."""

from __future__ import annotations

from custom_components.grow_conductor.core.model import Reason
from custom_components.grow_conductor.core.tunables import Tunables
from custom_components.grow_conductor.core.visibility import RefugeView, ViewerMemory, assess

from .helpers import at, snap, timedelta

TUNABLES = Tunables()
NOW = at(5, 23, 0)
QUIET = ViewerMemory()
NO_REFUGE = RefugeView()
ENGAGED = RefugeView(engaged=True)


def test_veto_wins_over_everything() -> None:
    """Rule 1.2: veto beats asleep, away, refuge — and has no release hold."""
    verdict = assess(
        snap(asleep=True, anyone_home=False, refuge_active=True, veto_active=True),
        NOW,
        QUIET,
        ENGAGED,
        TUNABLES,
    )
    assert not verdict.may_light
    assert verdict.reason is Reason.VETO
    # Veto released, nothing else observed: light may return immediately.
    verdict = assess(snap(asleep=True), NOW, QUIET, NO_REFUGE, TUNABLES)
    assert verdict.may_light
    assert verdict.reason is Reason.ASLEEP


def test_viewer_activity_observes_while_asleep() -> None:
    """Rule 1.3 (active half): any viewer activity means OBSERVED."""
    viewers = ViewerMemory(active_since=NOW)
    verdict = assess(snap(asleep=True, viewer_active=True), NOW, viewers, NO_REFUGE, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.VIEWERS


def test_clear_hold_after_viewer_activity() -> None:
    """Rule 1.3 (hold half): UNOBSERVED waits out clear_hold, with expiry."""
    last_end = NOW - timedelta(seconds=300)
    viewers = ViewerMemory(last_end=last_end)
    verdict = assess(snap(asleep=True), NOW, viewers, NO_REFUGE, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.ASLEEP  # the underlying lit-reason
    assert verdict.cooldown_until == last_end + timedelta(seconds=600)
    # Hold expired.
    viewers = ViewerMemory(last_end=NOW - timedelta(seconds=600))
    verdict = assess(snap(asleep=True), NOW, viewers, NO_REFUGE, TUNABLES)
    assert verdict.may_light


def test_hold_does_not_apply_while_observed() -> None:
    """The hold only delays UNOBSERVED verdicts; OBSERVED stays plain OBSERVED."""
    viewers = ViewerMemory(last_end=NOW)
    verdict = assess(snap(asleep=False, anyone_home=True), NOW, viewers, NO_REFUGE, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.AWAKE_HOME
    assert verdict.cooldown_until is None


def test_asleep_is_prime_time() -> None:
    """Rule 1.4."""
    verdict = assess(snap(asleep=True, anyone_home=True), NOW, QUIET, NO_REFUGE, TUNABLES)
    assert verdict.may_light
    assert verdict.reason is Reason.ASLEEP


def test_away_lights() -> None:
    """Rule 1.5."""
    verdict = assess(snap(asleep=False, anyone_home=False), NOW, QUIET, NO_REFUGE, TUNABLES)
    assert verdict.may_light
    assert verdict.reason is Reason.AWAY


def test_awake_home_is_observed_without_refuge() -> None:
    """Rule 1.6: no weekend latch, no exceptions."""
    verdict = assess(snap(asleep=False, anyone_home=True), NOW, QUIET, NO_REFUGE, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.AWAKE_HOME


def test_confirming_refuge_reports_ready_instant() -> None:
    """Rule 1.7: not engaged yet — observed, with the confirmation review."""
    ready = NOW + timedelta(seconds=120)
    verdict = assess(
        snap(asleep=False, anyone_home=True, refuge_active=True),
        NOW,
        QUIET,
        RefugeView(engaged=False, ready_at=ready),
        TUNABLES,
    )
    assert not verdict.may_light
    assert verdict.reason is Reason.AWAKE_HOME
    assert verdict.review_at == ready


def test_engaged_refuge_lights() -> None:
    """Rule 1.7."""
    verdict = assess(
        snap(asleep=False, anyone_home=True, refuge_active=True), NOW, QUIET, ENGAGED, TUNABLES
    )
    assert verdict.may_light
    assert verdict.reason is Reason.REFUGE


def test_refuge_tolerates_transient_exposure() -> None:
    """Rule 1.3c: viewer activity under exposure_grace keeps the light on."""
    viewers = ViewerMemory(active_since=NOW - timedelta(seconds=120))
    verdict = assess(
        snap(asleep=False, anyone_home=True, viewer_active=True), NOW, viewers, ENGAGED, TUNABLES
    )
    assert verdict.may_light
    assert verdict.reason is Reason.REFUGE
    assert verdict.review_at == viewers.active_since + timedelta(seconds=300)

    # Sustained exposure matures: OBSERVED.
    viewers = ViewerMemory(active_since=NOW - timedelta(seconds=300))
    verdict = assess(
        snap(asleep=False, anyone_home=True, viewer_active=True), NOW, viewers, ENGAGED, TUNABLES
    )
    assert not verdict.may_light
    assert verdict.reason is Reason.VIEWERS


def test_refuge_hold_uses_sustained_episodes_only() -> None:
    """Rule 1.3c: only grace-exceeding episodes impose a hold in refuge."""
    # A short episode ended recently: no hold inside refuge.
    viewers = ViewerMemory(last_end=NOW - timedelta(seconds=10))
    verdict = assess(snap(asleep=False, anyone_home=True), NOW, viewers, ENGAGED, TUNABLES)
    assert verdict.may_light

    # A sustained episode ended recently: normal clear_hold applies.
    viewers = ViewerMemory(
        last_end=NOW - timedelta(seconds=10), sustained_end=NOW - timedelta(seconds=10)
    )
    verdict = assess(snap(asleep=False, anyone_home=True), NOW, viewers, ENGAGED, TUNABLES)
    assert not verdict.may_light
    assert verdict.cooldown_until == viewers.sustained_end + timedelta(seconds=600)


def test_asleep_still_cuts_instantly_despite_refuge() -> None:
    """Rule 1.3c softens only the refuge context: asleep outranks refuge."""
    viewers = ViewerMemory(active_since=NOW - timedelta(seconds=5))
    verdict = assess(
        snap(asleep=True, anyone_home=True, viewer_active=True), NOW, viewers, ENGAGED, TUNABLES
    )
    assert not verdict.may_light
    assert verdict.reason is Reason.VIEWERS


def test_unknowns_fail_safe() -> None:
    """Rule 1.8: unknown sleep counts as awake, unknown home as home."""
    verdict = assess(snap(), NOW, QUIET, NO_REFUGE, TUNABLES)
    assert not verdict.may_light
    assert verdict.reason is Reason.AWAKE_HOME
    # Unknown sleep but definitively away still lights (1.5).
    verdict = assess(snap(anyone_home=False), NOW, QUIET, NO_REFUGE, TUNABLES)
    assert verdict.may_light
    assert verdict.reason is Reason.AWAY
