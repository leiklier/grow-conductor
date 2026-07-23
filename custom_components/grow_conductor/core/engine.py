"""The event-driven scheduling engine (ENGINE_SPEC §1-§5).

The adapter feeds events stamped with aware datetimes; the engine never
reads clocks (deterministic and directly testable). Every mutation
returns the fresh :class:`Decision`; between events the decision is
stable until ``next_review`` (rule 3.2).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .budget import PlantDayLedger
from .model import Decision, InputSnapshot, LightState, Reason
from .tunables import DEFAULT_TARGET_HOURS, Tunables, clamp_target_hours
from .visibility import RefugeView, Verdict, ViewerMemory, assess


class Engine:
    def __init__(
        self,
        tunables: Tunables | None = None,
        target_hours: float = DEFAULT_TARGET_HOURS,
    ) -> None:
        self._tunables = tunables or Tunables()
        self._target_s = clamp_target_hours(target_hours) * 3600.0
        self._ledger = PlantDayLedger(self._tunables)
        self._snapshot = InputSnapshot()
        # Viewer memory (rules 1.3/1.3b/1.3c).
        self._viewer_active_since: datetime | None = None
        self._viewer_last_end: datetime | None = None
        self._viewer_sustained_end: datetime | None = None
        # Refuge memory (rule 1.7).
        self._refuge_since: datetime | None = None
        self._refuge_last_active: datetime | None = None
        self._refuge_confirmed = False
        self._enabled = True
        self._light_on: bool | None = None
        self._decision: Decision | None = None

    # -- read surface ---------------------------------------------------------

    @property
    def tunables(self) -> Tunables:
        return self._tunables

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def target_hours(self) -> float:
        return self._target_s / 3600.0

    @property
    def snapshot(self) -> InputSnapshot:
        return self._snapshot

    @property
    def light_on(self) -> bool | None:
        return self._light_on

    @property
    def decision(self) -> Decision | None:
        """The most recent decision (None before the first event)."""
        return self._decision

    def spent_s(self, now: datetime) -> float:
        return self._ledger.spent_s(now)

    def day_start(self, now: datetime) -> datetime:
        self._ledger.roll(now)
        assert self._ledger.day_start is not None
        return self._ledger.day_start

    # -- events -----------------------------------------------------------------

    def handle_snapshot(self, snapshot: InputSnapshot, now: datetime) -> Decision:
        """Fold a normalized input snapshot into the engine."""
        previous = self._snapshot
        # Rule 1.3: track viewer episodes edge-to-edge, so holds count
        # from the end of activity and 1.3c can measure episode length.
        if snapshot.viewer_active and not previous.viewer_active:
            self._viewer_active_since = now
        elif not snapshot.viewer_active and previous.viewer_active:
            self._viewer_last_end = now
            started = self._viewer_active_since
            if (
                started is not None
                and (now - started).total_seconds() >= self._tunables.exposure_grace_s
            ):
                self._viewer_sustained_end = now
            self._viewer_active_since = None
        # Rule 1.7: an unconfirmed engagement restarts its confirmation
        # clock on every rising edge (continuity requirement); a stale
        # confirmed engagement (gap > refuge_hold) starts over entirely.
        if snapshot.refuge_active and not previous.refuge_active:
            lapsed = (
                self._refuge_last_active is None
                or (now - self._refuge_last_active).total_seconds() >= self._tunables.refuge_hold_s
            )
            if lapsed or not self._refuge_confirmed:
                self._refuge_since = now
                self._refuge_confirmed = False
        elif not snapshot.refuge_active and previous.refuge_active:
            # Falling edge: the evidence was present up to this instant —
            # the rule-1.7 hold counts from here.
            self._refuge_last_active = now
        self._snapshot = snapshot
        return self._decide(now)

    def activity_pulse(self, now: datetime) -> Decision:
        """Instantaneous viewer activity from a trigger entity (rule 1.3b).

        Stamps rule 1.3's activity clock — cutting the light and starting
        the clear-hold — without sustaining activity; the trigger's level
        is never part of the snapshot. During confirmed refuge, rule 1.3c
        ignores pulses entirely (they are by definition transient).
        """
        self._viewer_last_end = now
        return self._decide(now)

    def light_reported(self, on: bool | None, now: datetime) -> Decision:
        """Fold the physical light state into the ledger (rule 2.2)."""
        self._light_on = on
        self._ledger.light_reported(on, now)
        return self._decide(now)

    def set_target(self, hours: float, now: datetime) -> Decision:
        self._target_s = clamp_target_hours(hours) * 3600.0
        return self._decide(now)

    def set_enabled(self, enabled: bool, now: datetime) -> Decision:
        self._enabled = enabled
        return self._decide(now)

    def tick(self, now: datetime) -> Decision:
        """Re-evaluate with no input change (the ``next_review`` timer, 3.2)."""
        return self._decide(now)

    def seed_budget(self, day_start: datetime, spent_s: float, now: datetime) -> bool:
        """Adopt persisted budget state if still current (rule 5.1)."""
        return self._ledger.seed(day_start, spent_s, now)

    # -- decision (rule 3.1) ------------------------------------------------------

    def _refuge_view(self, now: datetime) -> RefugeView:
        """Advance the rule-1.7 confirm latch / hold expiry, then report."""
        if self._snapshot.refuge_active:
            self._refuge_last_active = now
            if (
                self._refuge_since is not None
                and (now - self._refuge_since).total_seconds() >= self._tunables.refuge_confirm_s
            ):
                self._refuge_confirmed = True
        elif (
            self._refuge_last_active is None
            or (now - self._refuge_last_active).total_seconds() >= self._tunables.refuge_hold_s
        ):
            self._refuge_since = None
            self._refuge_confirmed = False

        ready_at = None
        if self._snapshot.refuge_active and not self._refuge_confirmed:
            assert self._refuge_since is not None
            ready_at = self._refuge_since + timedelta(seconds=self._tunables.refuge_confirm_s)
        held_until = None
        if self._refuge_confirmed and not self._snapshot.refuge_active:
            assert self._refuge_last_active is not None
            held_until = self._refuge_last_active + timedelta(seconds=self._tunables.refuge_hold_s)
        return RefugeView(engaged=self._refuge_confirmed, ready_at=ready_at, held_until=held_until)

    def _decide(self, now: datetime) -> Decision:
        self._ledger.roll(now)
        verdict = assess(
            self._snapshot,
            now,
            ViewerMemory(
                active_since=self._viewer_active_since,
                last_end=self._viewer_last_end,
                sustained_end=self._viewer_sustained_end,
            ),
            self._refuge_view(now),
            self._tunables,
        )
        reviews = [self._ledger.next_anchor(now)]

        if not self._enabled:
            decision = Decision(False, LightState.STANDBY, None, min(reviews))
        elif not verdict.may_light:
            decision = self._decide_dark(verdict, reviews)
        else:
            decision = self._decide_light(verdict, now, reviews)

        self._decision = decision
        return decision

    def _decide_dark(self, verdict: Verdict, reviews: list[datetime]) -> Decision:
        if verdict.review_at is not None:
            reviews.append(verdict.review_at)
        if verdict.cooldown_until is not None:
            reviews.append(verdict.cooldown_until)
            return Decision(False, LightState.COOLDOWN, None, min(reviews))
        return Decision(False, LightState.OBSERVED, verdict.reason, min(reviews))

    def _decide_light(self, verdict: Verdict, now: datetime, reviews: list[datetime]) -> Decision:
        spent = self._ledger.spent_s(now)
        if spent >= self._target_s:  # rule 2.3
            return Decision(False, LightState.SATED, Reason.TARGET_REACHED, min(reviews))
        headroom = self._target_s - spent
        if self._light_on is not True and headroom < self._tunables.min_block_s:  # rule 2.5
            return Decision(False, LightState.SATED, Reason.LOW_HEADROOM, min(reviews))
        if verdict.review_at is not None:  # a tolerated exposure may mature (1.3c)
            reviews.append(verdict.review_at)
        reviews.append(self._ledger.cap_instant(now, self._target_s))
        return Decision(True, LightState.LIT, verdict.reason, min(reviews))
