"""Areas and floors.

The auto-generated Overview dashboard, what a user sees before they build
their own, groups entities by area. An instance with bad area data has a bad
default dashboard, and no amount of dashboard work fixes the cause.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..context import AuditContext
from ..model import Finding, Severity, rule

AREAS = "ha://knowledge/areas"

# Names that describe a grouping rather than a room.
NOT_A_ROOM = re.compile(
    r"^(all|whole|everything|integrations?|intergrations?|misc|other|general|test|"
    r"default|system|security|batteries|sensors?|devices?|home|house|unassigned)\b",
    re.IGNORECASE,
)


def _title_case(value: str) -> str:
    return " ".join(word[:1].upper() + word[1:].lower() for word in value.split())


@rule(
    "area/not-a-room",
    Severity.INFO,
    "Area is not a physical room",
    AREAS,
    why="Areas drive room-based voice commands and the default dashboard's grouping. "
        "A non-room area produces a dashboard section nobody wants and a room name "
        "voice control cannot resolve.",
    tags=("areas", "dashboard"),
)
def not_a_room(ctx: AuditContext) -> Iterator[Finding]:
    for area in ctx.area_list:
        if NOT_A_ROOM.match(area.name):
            yield Finding(
                subject=area.name,
                detail=f'"{area.name}" is a grouping, not a room',
                fix="Make it a label instead, and move its devices to real rooms",
            )


@rule(
    "area/naming",
    Severity.INFO,
    "Area name is not consistently capitalised",
    AREAS,
    why="Area names are shown verbatim on the dashboard and spoken by voice assistants.",
    tags=("areas", "naming"),
)
def area_naming(ctx: AuditContext) -> Iterator[Finding]:
    for area in ctx.area_list:
        if area.name != _title_case(area.name):
            yield Finding(
                subject=area.name,
                detail=f'"{area.name}" should be "{_title_case(area.name)}"',
                fix=f'Rename the area to "{_title_case(area.name)}"',
            )


@rule(
    "area/no-floors",
    Severity.INFO,
    "No floors defined",
    AREAS,
    why="Without floors, nothing can resolve a request scoped to a level, and the "
        "dashboard cannot group areas by storey.",
    tags=("areas",),
)
def no_floors(ctx: AuditContext) -> Iterator[Finding]:
    if not ctx.floor_list and len(ctx.area_list) > 3:
        yield Finding(
            detail=f"{len(ctx.area_list)} areas and no floors",
            fix="Create floors and assign each area to one",
        )


@rule(
    "area/empty",
    Severity.INFO,
    "Area contains nothing",
    AREAS,
    why="An empty area still renders as a heading on the default dashboard.",
    tags=("areas", "dashboard"),
)
def empty_area(ctx: AuditContext) -> Iterator[Finding]:
    occupied = {d.area_id for d in ctx.all_devices if d.area_id}
    occupied |= {ctx.area_id_of(e) for e in ctx.live_entities}
    for area in ctx.area_list:
        if area.id not in occupied:
            yield Finding(
                subject=area.name,
                detail=f'"{area.name}" has no devices or entities',
                fix="Assign something to it, or delete the area",
            )


@rule(
    "device/no-area",
    Severity.WARNING,
    "Physical device has no area",
    AREAS,
    why="Its entities inherit no room, so they fall into the default dashboard's "
        "ungrouped section and cannot be reached by room-based voice commands.",
    tags=("areas", "dashboard", "voice"),
)
def device_no_area(ctx: AuditContext) -> Iterator[Finding]:
    for device in ctx.physical_devices:
        if not device.area_id:
            yield Finding(
                device=ctx.device_name(device),
                detail=f"{device.manufacturer or 'unknown'} {device.model or ''}".strip(),
                fix="Assign the device to the room it is installed in",
            )


@rule(
    "entity/no-area",
    Severity.WARNING,
    "Entity has no area",
    AREAS,
    why="Same as a device with no area: invisible to room-based voice control and "
        "ungrouped on the default dashboard.",
    tags=("areas", "dashboard", "voice"),
)
def entity_no_area(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        if not ctx.is_primary(entry) or ctx.area_id_of(entry):
            continue
        device = ctx.device_of(entry)
        # Only an entity attached to a real device can sit in a room; helpers,
        # people and to-do lists have no physical location.
        if device is None or ctx.is_service_entity(entry):
            continue
        yield Finding(
            entity_id=entry.entity_id,
            detail=f'on device "{ctx.device_name(device)}"',
            fix="Assign an area, or assign one to its device",
        )


@rule(
    "entity/wrong-area",
    Severity.WARNING,
    "Entity names an area it is not assigned to",
    AREAS,
    why="A multi-gang switch's entities all inherit the room the hardware sits in. A "
        "gang driving a porch light then stays filed under the hallway, so turning off "
        "the porch misses it and the light appears on the wrong dashboard card.",
    tags=("areas", "dashboard", "voice"),
)
def wrong_area(ctx: AuditContext) -> Iterator[Finding]:
    from ..context import CONTROLLABLE

    for entry in ctx.live_entities:
        if not ctx.is_primary(entry) or entry.domain not in CONTROLLABLE:
            continue
        name = ctx.display_name(entry)
        if not name:
            continue

        area_id = ctx.area_id_of(entry)
        mentioned = [area for area in ctx.area_list if ctx.mentions_area(name, area.name)]
        if any(area.id == area_id for area in mentioned):
            # The name includes its own room; a shorter area name inside it,
            # like "Bedroom" within "Main Bedroom", is not a different room.
            continue
        # Of overlapping matches keep the longest, so "Main Bedroom" wins over "Bedroom".
        elsewhere = [
            area for area in mentioned
            if not any(
                other is not area and area.name.lower() in other.name.lower()
                for other in mentioned
            )
        ]
        if elsewhere:
            here = ctx.area_name(area_id) or "no area"
            named = ", ".join(f'"{a.name}"' for a in elsewhere)
            yield Finding(
                entity_id=entry.entity_id,
                area=here,
                detail=f'"{name}" names {named} but sits in {here}',
                fix=f'Override this entity\'s area to "{elsewhere[0].name}" if that is '
                    f"the room it affects",
            )
