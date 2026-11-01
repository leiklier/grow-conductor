"""Visibility verdict (ENGINE_SPEC §1)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .model import InputSnapshot, Reason
from .tunables import Tunables


@dataclass(frozen=True)
class ViewerMemory:
    """What the engine remembers about viewer activity (rules 1.3/1.3b/1.3c).

    ``active_since`` — start of the ongoing episode (None when quiet).
    ``last_end`` — falling edge of the most recent episode or pulse; the
    hold reference for the asleep/away contexts.
    ``sustained_end`` — falling edge of the most recent episode that
    reached ``exposure_grace``, or the most recent trigger pulse; the
    hold reference inside refuge (1.3b, 1.3c).
    """

    active_since: datetime | None = None
    last_end: datetime | None = None
    sustained_end: datetime | None = None


@dataclass(frozen=True)
class RefugeView:
    """The engine's rule-1.7 refuge status at one instant.

    ``engaged`` — confirmed and not lapsed (active or within refuge_hold).
    ``ready_at`` — set while an unconfirmed engagement is confirming.
    ``held_until`` — set while engaged on held (inactive) evidence: the
    instant the hold lapses if no refuge zone reactivates.
    """

    engaged: bool = False
    ready_at: datetime | None = None
    held_until: datetime | None = None


@dataclass(frozen=True)
class Verdict:
    """Outcome of the §1 priority chain at one instant.

    ``reason`` is the lit-reason when ``may_light`` and the observed-reason
    otherwise. ``cooldown_until`` is set when the household is UNOBSERVED
    but a clear-hold is still running. ``review_at`` is a future instant
    at which the verdict may flip with no input change (refuge
    confirmation, or a tolerated exposure reaching ``exposure_grace``).
    ``context`` is the rule-1.9 context, independent of vetoes, viewers
    and holds. ``tolerated`` marks a ``may_light`` that rests only on
    rule 1.3c's tolerance of an ongoing short episode: it may keep a
    burning block alive but never start one (rule 3.1).
    """

    may_light: bool
    reason: Reason
    cooldown_until: datetime | None = None
    review_at: datetime | None = None
    context: Reason = Reason.AWAKE_HOME
    tolerated: bool = False


def assess(
    snapshot: InputSnapshot,
    now: datetime,
    viewers: ViewerMemory,
    refuge: RefugeView,
    tunables: Tunables,
) -> Verdict:
    """Evaluate rules 1.2-1.8 in priority order; tag the 1.9 context."""
    context = classify_context(snapshot, refuge)
    return replace(_assess(snapshot, now, viewers, refuge, tunables, context), context=context)


def classify_context(snapshot: InputSnapshot, refuge: RefugeView) -> Reason:
    """Rule 1.9: the underlying situation of rules 1.4-1.7 (unknowns per 1.8)."""
    if snapshot.asleep is True:  # 1.4
        return Reason.ASLEEP
    if snapshot.anyone_home is False:  # 1.5
        return Reason.AWAY
    if refuge.engaged:  # 1.6 + 1.7
        return Reason.REFUGE
    return Reason.AWAKE_HOME  # 1.6, no (confirmed) refuge evidence


def _assess(
    snapshot: InputSnapshot,
    now: datetime,
    viewers: ViewerMemory,
    refuge: RefugeView,
    tunables: Tunables,
    underlying: Reason,
) -> Verdict:
    if snapshot.veto_active:  # 1.2
        # Still review the instants the context may change at (refuge
        # confirm/lapse), so a rule-4.4 override releases on time.
        if underlying is Reason.AWAKE_HOME:
            return Verdict(False, Reason.VETO, review_at=refuge.ready_at)
        if underlying is Reason.REFUGE:
            return Verdict(False, Reason.VETO, review_at=refuge.held_until)
        return Verdict(False, Reason.VETO)

    if underlying is Reason.AWAKE_HOME:
        reason = Reason.VIEWERS if snapshot.viewer_active else Reason.AWAKE_HOME
        return Verdict(False, reason, review_at=refuge.ready_at)

    if underlying is Reason.REFUGE:
        return _assess_refuge(snapshot, now, viewers, refuge, tunables)

    # Asleep/away: every blip cuts instantly (1.3, 1.3b).
    if snapshot.viewer_active:
        return Verdict(False, Reason.VIEWERS)
    if viewers.last_end is not None:
        hold_until = viewers.last_end + timedelta(seconds=tunables.clear_hold_s)
        if now < hold_until:
            return Verdict(False, underlying, cooldown_until=hold_until)
    return Verdict(True, underlying)


def _assess_refuge(
    snapshot: InputSnapshot,
    now: datetime,
    viewers: ViewerMemory,
    refuge: RefugeView,
    tunables: Tunables,
) -> Verdict:
    """Rule 1.3c: transient viewer exposure is tolerated during confirmed
    refuge; trigger pulses (1.3b) and sustained episodes still impose the
    clear_hold via ``sustained_end`` — and a running hold is never
    bypassed by a new, still-tolerated episode."""
    reviews = [t for t in (refuge.held_until,) if t is not None]
    if snapshot.viewer_active and viewers.active_since is not None:
        exposed_at = viewers.active_since + timedelta(seconds=tunables.exposure_grace_s)
        if now >= exposed_at:
            return Verdict(False, Reason.VIEWERS, review_at=refuge.held_until)
        reviews.append(exposed_at)
    review_at = min(reviews) if reviews else None
    if viewers.sustained_end is not None:
        hold_until = viewers.sustained_end + timedelta(seconds=tunables.clear_hold_s)
        if now < hold_until:
            return Verdict(False, Reason.REFUGE, cooldown_until=hold_until, review_at=review_at)
    return Verdict(True, Reason.REFUGE, review_at=review_at, tolerated=snapshot.viewer_active)
