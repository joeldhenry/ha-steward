"""Bridged and duplicated devices.

Matter, Matterbridge, HomeKit bridges and Hue-style hubs all re-expose devices
that Home Assistant may already have natively. The result is two entities for
one physical thing: both work, both appear on dashboards and in voice pickers,
and only one of them reports the full feature set.

This is worth finding because nothing in Home Assistant flags it — each
integration is behaving correctly on its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..context import CONTROLLABLE, AuditContext
from ..model import Finding, Severity, rule

BRIDGES = "ha://knowledge/bridges"
TYPES = "ha://knowledge/device-types"

# Integrations whose devices are usually re-exposures of something else.
BRIDGE_PLATFORMS = frozenset({"matter", "homekit_controller", "homekit", "mqtt"})

_NOISE = re.compile(r"\b(matter|bridge|bridged|hub|gateway|zigbee|hue|homekit)\b", re.I)


def _normalise(name: str) -> str:
    """Reduce a name to something comparable across integrations."""
    cleaned = _NOISE.sub(" ", name.lower())
    return re.sub(r"[^a-z0-9]+", "", cleaned)


@rule(
    "bridge/duplicate-device",
    Severity.WARNING,
    "One physical device appears under two integrations",
    BRIDGES,
    why="A device bridged through Matter or HomeKit while also integrated natively "
        "shows up twice in every picker and on every dashboard. Voice control cannot "
        "tell them apart, and the bridged copy usually supports fewer features.",
    tags=("matter", "bridges", "voice", "dashboard"),
)
def duplicate_device(ctx: AuditContext) -> Iterator[Finding]:
    # Group physical devices by a normalised name, tracking which integration
    # each came from.
    platform_by_device: dict[str, set[str]] = {}
    for entry in ctx.live_entities:
        if entry.device_id:
            platform_by_device.setdefault(entry.device_id, set()).add(entry.platform)

    by_name: dict[str, list[tuple[str, frozenset[str]]]] = {}
    for device in ctx.physical_devices:
        name = ctx.device_name(device)
        key = _normalise(name)
        if len(key) < 4:
            continue
        platforms = frozenset(platform_by_device.get(device.id, set()))
        if not platforms:
            continue
        by_name.setdefault(key, []).append((name, platforms))

    for candidates in by_name.values():
        if len(candidates) < 2:
            continue
        platforms = {p for _, group in candidates for p in group}
        if len(platforms) < 2:
            continue
        # Only interesting when at least one side is a bridge; two devices from
        # the same integration sharing a name is a naming problem, not a bridge.
        if not platforms & BRIDGE_PLATFORMS:
            continue
        names = ", ".join(sorted({name for name, _ in candidates}))
        yield Finding(
            subject=names,
            detail=f"exposed by {', '.join(sorted(platforms))}",
            fix="Keep the integration with the richer feature set and disable the "
                "other device, rather than hiding entities one at a time",
        )


@rule(
    "entity/duplicate-function",
    Severity.WARNING,
    "One function is exposed as two entities",
    TYPES,
    why="A relay offered as both a switch and a light gives a person and a model two "
        "ways to do one thing, with no way to tell which is correct.",
    tags=("types", "voice", "dashboard"),
)
def duplicate_function(ctx: AuditContext) -> Iterator[Finding]:
    by_device_name: dict[tuple[str, str], list[str]] = {}
    for entry in ctx.live_entities:
        if entry.hidden_by or not entry.device_id:
            continue
        name = ctx.display_name(entry)
        if name:
            by_device_name.setdefault((entry.device_id, name.lower()), []).append(
                entry.entity_id
            )

    for members in by_device_name.values():
        domains = {m.split(".")[0] for m in members}
        if len(members) > 1 and len(domains) > 1 and domains & CONTROLLABLE:
            yield Finding(
                detail=" and ".join(sorted(members)) + " share a name",
                fix="Keep the entity that best describes the function and hide the other",
            )
