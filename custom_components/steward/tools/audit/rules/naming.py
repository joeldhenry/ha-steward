"""Naming conventions.

The composed name is what a dashboard card, a voice assistant, CarPlay and the
Watch all display and match against. Redundant or absent names degrade every
one of those surfaces at once.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..context import CONTROLLABLE, HEX_BLOB, AuditContext
from ..model import Finding, Severity, rule

NAMING = "ha://knowledge/naming"


@rule(
    "entity/no-name",
    Severity.WARNING,
    "Entity has no friendly name",
    NAMING,
    why="Dashboards and voice assistants fall back to the raw entity_id, so the user "
        "sees 'sensor.0x00158d0004a1b2c3' on their Overview.",
    tags=("naming", "dashboard", "voice"),
)
def no_name(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        if not ctx.is_primary(entry) or entry.hidden_by:
            continue
        if not ctx.display_name(entry):
            yield Finding(
                entity_id=entry.entity_id,
                detail="no friendly name; the entity ID is shown instead",
                fix="Give the entity a name describing what it is",
            )


@rule(
    "entity/name-repeats-area",
    Severity.INFO,
    "Entity name repeats its own area",
    NAMING,
    why="The area already carries the room, so the dashboard shows 'Kitchen' above "
        "'Kitchen Ceiling Light', and voice control hears the room twice.",
    tags=("naming", "dashboard", "voice"),
)
def name_repeats_area(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        if not ctx.is_primary(entry) or entry.domain not in CONTROLLABLE:
            continue
        name = ctx.display_name(entry)
        area_id = ctx.area_id_of(entry)
        area_name = ctx.area_name(area_id)
        if not name or not area_name:
            continue
        # A name mentioning a different area is entity/wrong-area, not this.
        if any(
            a.id != area_id and ctx.mentions_area(name, a.name) for a in ctx.area_list
        ):
            continue
        if ctx.mentions_area(name, area_name):
            yield Finding(
                entity_id=entry.entity_id,
                area=area_name,
                detail=f'"{name}" repeats its own area',
                fix=f'Drop "{area_name}" from the name; the area already carries it',
            )


@rule(
    "entity/name-repeats-device",
    Severity.INFO,
    "Entity name repeats its device name",
    NAMING,
    why="Home Assistant composes the display name from both, so the device name "
        "appears twice.",
    tags=("naming",),
)
def name_repeats_device(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        device_name = ctx.device_name(ctx.device_of(entry))
        if not entry.name or not device_name:
            continue
        if entry.name.lower().startswith(device_name.lower()):
            yield Finding(
                entity_id=entry.entity_id,
                detail=f'name "{entry.name}" starts with device name "{device_name}"',
                fix="Name the entity after the data point alone",
            )


@rule(
    "entity/raw-identifier",
    Severity.WARNING,
    "Name or ID contains a hardware identifier",
    NAMING,
    why="A MAC address or serial is unreadable on a dashboard and unusable by voice.",
    tags=("naming", "dashboard", "voice"),
)
def raw_identifier(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        if not ctx.is_primary(entry):
            continue
        name = ctx.display_name(entry)
        in_id = HEX_BLOB.search(entry.entity_id)
        in_name = HEX_BLOB.search(name) if name else None
        if not in_id and not in_name:
            continue
        where = "entity ID" if in_id else "name"
        yield Finding(
            entity_id=entry.entity_id,
            detail=f"{where} contains a hardware identifier"
                   + (f': "{name}"' if in_name else ""),
            fix="Rename it to describe what the device does. Check for references to "
                "the old entity ID first.",
        )
