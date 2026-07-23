# Migrating the live instance from the template automations

This replaces, per grow light, the legacy stack of: a "… Plantelys
Required State" template binary sensor, an "… Plantelys - Enforce State"
automation, and an "… Plantelys On Last 24 Hours" history_stats helper.
The night-movement plumbing (`input_boolean.night_movement` and its
automation) **stays** — path lighting still uses it; Grow Conductor
simply doesn't need it: viewer occupancy covers night movement directly
(rule 1.3), and the bedroom door as a movement trigger (rule 1.3b)
reproduces the legacy instant cut on door-open — without an open door
ever blocking the schedule.

## 1. Create the devices

**Sofakrok plantelys**

| Field | Value |
| --- | --- |
| Grow light switch | `switch.sofakrok_plantelys` |
| Household asleep | `binary_sensor.household_sleep_mode` |
| Anyone home | `zone.home` |
| Rooms with a view | `binary_sensor.sofakrok_occupancy`, `binary_sensor.spisebord_occupancy`, `binary_sensor.kjokken_occupancy` |
| Out-of-sight rooms | `binary_sensor.kontor_occupancy` |
| Hard vetoes | — (viewer occupancy already covers TV watchers in sofakrok) |
| Movement triggers | `binary_sensor.soverom_dor` |
| Target hours | 14 (legacy: 16 weekdays / 12 weekends) |

**Spisebord plantelys**

| Field | Value |
| --- | --- |
| Grow light switch | `switch.spisebord_plantelys` |
| Household asleep | `binary_sensor.household_sleep_mode` |
| Anyone home | `zone.home` |
| Rooms with a view | `binary_sensor.spisebord_occupancy`, `binary_sensor.sofakrok_occupancy`, `binary_sensor.kjokken_occupancy` |
| Out-of-sight rooms | `binary_sensor.kontor_occupancy` |
| Hard vetoes | `media_player.sofakrok_tv` (legacy behavior: TV on ⇒ off) |
| Movement triggers | `binary_sensor.soverom_dor` |
| Target hours | 13 (legacy: 14 weekdays / 12 weekends) |

Presence Conductor room occupancy entities are the intended viewer/
refuge inputs once the cutover to them happens; the template occupancy
helpers above work identically in the meantime.

Behavior changes to be aware of (deliberate, see DECISION.md): no
weekend "stay on after waking" latch, and the away schedule follows the
anchor + budget instead of the fixed 22:00–14:00 window. The workday and
vacation inputs are gone — WFH is detected via the office, and vacation
is just "away".

## 2. Shadow period (recommended)

Add both devices but leave each `switch.…_enabled` **off**. The state
sensor shows what the conductor *would* do (`lit` vs the legacy template
state) without touching the lights. Compare for a few days.

## 3. Cutover, per light

1. Disable the legacy automation "… Plantelys - Enforce State".
2. Turn `switch.…_enabled` on.
3. After a week of good behavior, delete the legacy template sensor and
   (optionally) the history_stats helper — `sensor.…_lit_today` replaces
   it. Keeping the history_stats a while longer is harmless and gives an
   independent cross-check of delivered hours.

## 4. Rollback

Turn `switch.…_enabled` off and re-enable the legacy automation. Nothing
in the legacy stack is modified by this integration.
