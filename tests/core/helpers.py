"""Shared helpers for core tests: fixed-timezone clocks and snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.grow_conductor.core.model import InputSnapshot

__all__ = ["at", "snap", "timedelta"]


def at(day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """An aware instant in January 2026; anchors resolve in this same tz."""
    return datetime(2026, 1, day, hour, minute, second, tzinfo=UTC)


def snap(
    *,
    asleep: bool | None = None,
    anyone_home: bool | None = None,
    viewer_active: bool = False,
    refuge_active: bool = False,
    veto_active: bool = False,
) -> InputSnapshot:
    return InputSnapshot(
        asleep=asleep,
        anyone_home=anyone_home,
        viewer_active=viewer_active,
        refuge_active=refuge_active,
        veto_active=veto_active,
    )
