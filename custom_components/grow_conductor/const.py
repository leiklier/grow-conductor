"""Constants and the options contract.

Options contract (house convention: ``entry.data`` stays empty, every
setting lives in ``entry.options`` so the options flow can edit all of
it; ``entry.title`` is the device name):

- ``light_entity`` (str, required) — the switch/light to conduct.
- ``sleep_entity`` (str, optional) — household-asleep binary signal.
- ``home_entity`` (str, optional) — anyone-home signal (zone, person,
  device_tracker, binary sensor, or numeric count).
- ``viewer_entities`` (list[str]) — occupancy in rooms that can see the
  light (ENGINE_SPEC rule 1.3).
- ``refuge_entities`` (list[str]) — occupancy that proves everyone is
  settled out of sight (rule 1.7).
- ``veto_entities`` (list[str]) — hard "someone is watching" signals,
  e.g. the TV media_player (rule 1.2).
- ``trigger_entities`` (list[str]) — momentary movement signals whose
  state *transitions* pulse the viewer-activity clock (rule 1.3b),
  e.g. the bedroom door contact. Their level is never read.
- ``anchor`` (str "HH:MM:SS") — plant-day boundary (rule 2.1).
- ``clear_hold_seconds`` / ``refuge_confirm_seconds`` /
  ``refuge_hold_seconds`` / ``exposure_grace_seconds`` /
  ``min_block_seconds`` (number) — ENGINE_SPEC §6 tunables.

Runtime knobs (``number.target_hours``, ``switch.enabled``) are entity
state restored by HA, never options.
"""

from __future__ import annotations

DOMAIN = "grow_conductor"

CONF_LIGHT = "light_entity"
CONF_SLEEP = "sleep_entity"
CONF_HOME = "home_entity"
CONF_VIEWERS = "viewer_entities"
CONF_REFUGES = "refuge_entities"
CONF_VETOES = "veto_entities"
CONF_TRIGGERS = "trigger_entities"
CONF_ANCHOR = "anchor"
CONF_CLEAR_HOLD = "clear_hold_seconds"
CONF_REFUGE_CONFIRM = "refuge_confirm_seconds"
CONF_REFUGE_HOLD = "refuge_hold_seconds"
CONF_EXPOSURE_GRACE = "exposure_grace_seconds"
CONF_MIN_BLOCK = "min_block_seconds"

DEFAULT_ANCHOR = "22:00:00"

# While the light burns with no events due, re-publish the lit-hours
# sensor on this cadence (quantization keeps the recorder quiet).
PUBLISH_INTERVAL_S = 360.0

PLATFORMS = ["number", "sensor", "switch"]
