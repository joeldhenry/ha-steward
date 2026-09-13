"""Device and state classes.

These decide whether a sensor is graphable, whether it appears on the Energy
dashboard, and whether long-term statistics are kept at all.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..context import AuditContext
from ..model import Finding, Severity, rule

TYPES = "ha://knowledge/device-types"

ENERGY_UNITS = frozenset({"Wh", "kWh", "MWh", "GJ"})
POWER_UNITS = frozenset({"W", "kW", "MW"})
TEMPERATURE_UNITS = frozenset({"°C", "°F", "K"})


@rule(
    "sensor/missing-state-class",
    Severity.ERROR,
    "Energy sensor records no statistics",
    TYPES,
    why="Without a state_class the recorder keeps no long-term statistics, so the "
        "sensor cannot appear on the Energy dashboard and its history is purged with "
        "everything else. The data is lost, not merely unshown.",
    tags=("classes", "energy"),
)
def missing_state_class(ctx: AuditContext) -> Iterator[Finding]:
    for state in ctx.hass.states.async_all("sensor"):
        unit = state.attributes.get("unit_of_measurement")
        if unit not in ENERGY_UNITS:
            continue
        if state.attributes.get("state_class") in ("total_increasing", "total"):
            continue
        yield Finding(
            entity_id=state.entity_id,
            detail=f"unit {unit}, state_class "
                   f"{state.attributes.get('state_class') or 'none'}",
            fix="Set state_class to total_increasing for a meter that only rises, or "
                "total if it can decrease",
        )


@rule(
    "sensor/missing-device-class",
    Severity.WARNING,
    "Sensor has a recognisable unit but no device class",
    TYPES,
    why="The device class drives the icon, colour and unit conversion, and the Energy "
        "dashboard will not offer a power sensor without one.",
    tags=("classes",),
)
def missing_device_class(ctx: AuditContext) -> Iterator[Finding]:
    expected = [(POWER_UNITS, "power"), (ENERGY_UNITS, "energy"),
                (TEMPERATURE_UNITS, "temperature")]
    for state in ctx.hass.states.async_all("sensor"):
        unit = state.attributes.get("unit_of_measurement")
        if not unit:
            continue
        for units, device_class in expected:
            if unit in units and state.attributes.get("device_class") != device_class:
                yield Finding(
                    entity_id=state.entity_id,
                    detail=f"unit {unit}, device_class "
                           f"{state.attributes.get('device_class') or 'none'}",
                    fix=f"Set device_class to {device_class}",
                )
                break


@rule(
    "entity/switch-as-x",
    Severity.INFO,
    "Switch appears to drive a light, fan, cover or valve",
    TYPES,
    why="A relay reported as a switch is missed by 'turn off all the lights', gets a "
        "toggle instead of a light card, and is invisible to anything targeting the "
        "light domain, including CarPlay's lights section.",
    tags=("types", "dashboard", "voice"),
)
def switch_as_x(ctx: AuditContext) -> Iterator[Finding]:
    import re

    hints = (
        ("light", re.compile(r"\b(light|lamp|globe|downlight|sconce|chandelier)\b", re.I)),
        ("fan", re.compile(r"\b(fan|extractor|exhaust)\b", re.I)),
        ("cover", re.compile(r"\b(blind|curtain|shutter|garage door|gate|awning)\b", re.I)),
        ("valve", re.compile(r"\b(valve|sprinkler|irrigation|tap)\b", re.I)),
    )
    for entry in ctx.live_entities:
        if entry.domain != "switch" or not ctx.is_primary(entry) or entry.hidden_by:
            continue
        name = ctx.display_name(entry)
        for target, pattern in hints:
            if pattern.search(name):
                yield Finding(
                    entity_id=entry.entity_id,
                    detail=f'"{name}" looks like a {target}',
                    fix=f"Create a Switch as X helper presenting it as a {target}, or "
                        f"set the device type in the integration if it offers one",
                )
                break
