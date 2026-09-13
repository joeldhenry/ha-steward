"""Voice assistants and the companion apps.

Assist, Siri, CarPlay and the Apple Watch all consume the same registry data,
and all of them resolve entities by spoken or displayed name within an area. A
name that is merely untidy on a dashboard is unusable here: two entities called
"Front Door Light" give a voice assistant no way to choose, and an entity with
no area cannot be reached by "turn on the kitchen lights" at all.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..context import ACTIONABLE, CONTROLLABLE, AuditContext
from ..model import Finding, Severity, rule

COMPANION = "ha://knowledge/companion"
AREAS = "ha://knowledge/areas"

ASSISTANT = "conversation"


def _exposed(ctx: AuditContext, entity_id: str) -> bool:
    """Whether an entity is exposed to Assist, and so to Siri and CarPlay."""
    try:
        from homeassistant.components.homeassistant.exposed_entities import (
            async_should_expose,
        )
    except ImportError:
        return False
    return async_should_expose(ctx.hass, ASSISTANT, entity_id)


@rule(
    "voice/duplicate-name",
    Severity.WARNING,
    "Two exposed entities share a name",
    COMPANION,
    why="A voice assistant has no way to choose between them, so the request either "
        "fails or acts on the wrong one. The same ambiguity appears in CarPlay and on "
        "the Watch, where both entries look identical.",
    tags=("voice", "carplay", "watch", "naming"),
)
def duplicate_name(ctx: AuditContext) -> Iterator[Finding]:
    # Keyed case-insensitively, but the name is reported as the user wrote it.
    by_name: dict[tuple[str, str], tuple[str, list[str]]] = {}
    for entry in ctx.live_entities:
        if entry.domain not in ACTIONABLE or entry.hidden_by:
            continue
        name = ctx.display_name(entry)
        if not name or not _exposed(ctx, entry.entity_id):
            continue
        # Names only collide for voice within the same area.
        key = (ctx.area_id_of(entry) or "", name.casefold())
        _, members = by_name.setdefault(key, (name, []))
        members.append(entry.entity_id)

    for (area_id, _), (name, entity_ids) in by_name.items():
        if len(entity_ids) < 2:
            continue
        where = ctx.area_name(area_id) or "no area"
        yield Finding(
            subject=name,
            area=where,
            detail=f'{len(entity_ids)} entities named "{name}" in {where}: '
                   f"{', '.join(sorted(entity_ids)[:4])}",
            fix="Rename them so each says what it controls, or stop exposing the ones "
                "nobody asks for by voice",
        )


@rule(
    "voice/exposed-without-area",
    Severity.WARNING,
    "Entity is exposed to voice but has no area",
    AREAS,
    why="Room-scoped requests such as 'turn off the kitchen lights' cannot reach it, "
        "and CarPlay lists it outside any room.",
    tags=("voice", "carplay", "areas"),
)
def exposed_without_area(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        if entry.domain not in CONTROLLABLE or not ctx.is_primary(entry):
            continue
        if ctx.area_id_of(entry) or not _exposed(ctx, entry.entity_id):
            continue
        yield Finding(
            entity_id=entry.entity_id,
            detail=f'"{ctx.display_name(entry)}" is voice-controllable but in no room',
            fix="Assign it to the room it affects",
        )


@rule(
    "companion/no-icon",
    Severity.INFO,
    "Scene or script has no icon",
    COMPANION,
    why="CarPlay and the Watch render a tile per item. Without an icon they all show "
        "the same default glyph, which makes the list unusable at a glance.",
    tags=("carplay", "watch", "dashboard"),
)
def no_icon(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        if entry.domain not in ("scene", "script") or entry.hidden_by:
            continue
        state = ctx.state_of(entry.entity_id)
        has_icon = bool(entry.icon or entry.original_icon)
        if not has_icon and state is not None:
            has_icon = bool(state.attributes.get("icon"))
        if has_icon:
            continue
        yield Finding(
            entity_id=entry.entity_id,
            detail=f'"{ctx.display_name(entry)}" has no icon',
            fix="Set an icon so it is distinguishable in CarPlay and on the Watch",
        )


@rule(
    "voice/diagnostic-exposed",
    Severity.INFO,
    "Diagnostic entity is exposed to voice",
    COMPANION,
    why="Signal strength and firmware version are not things anyone asks an assistant "
        "about, and each one is another candidate for a misheard match.",
    tags=("voice",),
)
def diagnostic_exposed(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        if entry.entity_category is None:
            continue
        if not _exposed(ctx, entry.entity_id):
            continue
        yield Finding(
            entity_id=entry.entity_id,
            detail=f"{entry.entity_category} entity exposed to Assist",
            fix="Stop exposing it under Settings, Voice assistants, Expose",
        )


@rule(
    "voice/unqueryable-binary-sensor",
    Severity.INFO,
    "Binary sensor has no device class, so voice cannot be asked about it",
    COMPANION,
    why="Home Assistant exposes a binary sensor to Assist only when its device class "
        "says what the reading means — door, window, motion, moisture and a few others. "
        "Without one it is invisible to voice entirely, cannot answer 'is the back door "
        "open?', and shows a generic icon on dashboards.",
    tags=("voice", "classes", "dashboard"),
)
def unqueryable_binary_sensor(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        if entry.domain != "binary_sensor" or not ctx.is_primary(entry):
            continue
        state = ctx.state_of(entry.entity_id)
        declared = entry.device_class or entry.original_device_class or (
            state.attributes.get("device_class") if state else None
        )
        if declared:
            continue
        yield Finding(
            entity_id=entry.entity_id,
            detail=f'"{ctx.display_name(entry) or entry.entity_id}" has no device class, '
                   f"so it is not exposed to voice",
            fix="Set a device class such as door, window, motion or moisture so its "
                "states have meaning",
        )
