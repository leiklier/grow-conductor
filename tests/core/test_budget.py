"""PlantDayLedger — ENGINE_SPEC §2 and rule 5.1."""

from __future__ import annotations

from custom_components.grow_conductor.core.budget import PlantDayLedger
from custom_components.grow_conductor.core.tunables import Tunables

from .helpers import at, timedelta

H = 3600.0


def make_ledger() -> PlantDayLedger:
    return PlantDayLedger(Tunables())


def test_anchor_geometry() -> None:
    """Rule 2.1: the plant day pivots at the anchor (22:00)."""
    ledger = make_ledger()
    assert ledger.anchor_before(at(5, 23, 30)) == at(5, 22)
    assert ledger.anchor_before(at(5, 21, 59)) == at(4, 22)
    assert ledger.anchor_before(at(5, 22, 0)) == at(5, 22)
    assert ledger.next_anchor(at(5, 23, 30)) == at(6, 22)


def test_midnight_anchor() -> None:
    ledger = PlantDayLedger(Tunables(anchor_minutes=0))
    assert ledger.anchor_before(at(5, 0, 0)) == at(5, 0)
    assert ledger.anchor_before(at(5, 23, 59)) == at(5, 0)


def test_accrual_open_and_closed_blocks() -> None:
    """Rule 2.2: spent includes the open block up to 'now'."""
    ledger = make_ledger()
    ledger.light_reported(True, at(5, 23, 0))
    assert ledger.spent_s(at(5, 23, 30)) == 30 * 60
    ledger.light_reported(False, at(6, 1, 0))
    assert ledger.spent_s(at(6, 5, 0)) == 2 * H
    # A second block adds on top.
    ledger.light_reported(True, at(6, 6, 0))
    assert ledger.spent_s(at(6, 7, 0)) == 3 * H


def test_redundant_reports_are_idempotent() -> None:
    """Rule 4.2: repeating the same report changes nothing."""
    ledger = make_ledger()
    ledger.light_reported(True, at(5, 23, 0))
    ledger.light_reported(True, at(5, 23, 40))  # still counts from 23:00
    assert ledger.spent_s(at(6, 0, 0)) == H
    ledger.light_reported(False, at(6, 0, 0))
    ledger.light_reported(False, at(6, 0, 30))
    assert ledger.spent_s(at(6, 1, 0)) == H


def test_unknown_light_state_accrues_nothing() -> None:
    """Rule 2.2: unknown closes the open block."""
    ledger = make_ledger()
    ledger.light_reported(True, at(5, 23, 0))
    ledger.light_reported(None, at(6, 0, 0))
    assert ledger.spent_s(at(6, 3, 0)) == H
    ledger.light_reported(True, at(6, 4, 0))
    assert ledger.spent_s(at(6, 5, 0)) == 2 * H


def test_open_block_splits_at_anchor() -> None:
    """Rule 2.4: pre-anchor time to the old day, post-anchor to the new."""
    ledger = make_ledger()
    ledger.light_reported(True, at(5, 21, 0))
    assert ledger.spent_s(at(5, 21, 59)) == 59 * 60  # old day
    assert ledger.spent_s(at(5, 23, 0)) == H  # new day: 22:00-23:00 only
    assert ledger.day_start == at(5, 22)
    assert ledger.lit  # the block itself keeps burning


def test_multi_day_gap_rolls_to_current_day() -> None:
    ledger = make_ledger()
    ledger.light_reported(True, at(5, 23, 0))
    ledger.light_reported(False, at(5, 23, 30))
    # Nothing happens for two days; spent resets to the current plant day.
    assert ledger.spent_s(at(8, 10, 0)) == 0.0
    assert ledger.day_start == at(7, 22)


def test_headroom_and_cap_instant() -> None:
    ledger = make_ledger()
    ledger.light_reported(True, at(5, 23, 0))
    now = at(6, 0, 0)
    assert ledger.headroom_s(now, 12 * H) == 11 * H
    assert ledger.cap_instant(now, 12 * H) == now + timedelta(hours=11)
    assert ledger.headroom_s(now, 0.5 * H) == 0.0


def test_seed_adopted_when_same_plant_day() -> None:
    """Rule 5.1: a seed from the current plant day restores spent."""
    ledger = make_ledger()
    assert ledger.seed(at(5, 22), 3 * H, now=at(6, 8, 0))
    assert ledger.spent_s(at(6, 8, 0)) == 3 * H


def test_seed_discarded_when_stale() -> None:
    """Rule 5.1: a seed from another plant day starts fresh."""
    ledger = make_ledger()
    assert not ledger.seed(at(4, 22), 3 * H, now=at(6, 8, 0))
    assert ledger.spent_s(at(6, 8, 0)) == 0.0
    assert ledger.day_start == at(5, 22)
