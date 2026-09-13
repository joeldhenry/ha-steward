"""Automations, scripts and scenes.

Rules here read the stored YAML rather than entity state, because the problems
that matter (a reference to a deleted entity, a trigger bound to a device ID)
are invisible until the automation runs and does nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from ..context import AuditContext
from ..model import Finding, Severity, rule

AUTOMATIONS = "ha://knowledge/automations"
ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def _walk(node: Any) -> Iterator[tuple[str, Any]]:
    """Yield every (key, value) pair anywhere in a nested config."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _referenced_entities(config: Any) -> set[str]:
    found: set[str] = set()
    for key, value in _walk(config):
        if key not in ("entity_id", "entity"):
            continue
        values = value if isinstance(value, list) else [value]
        found.update(v for v in values if isinstance(v, str) and ENTITY_ID.match(v))
    return found


@rule(
    "automation/broken-reference",
    Severity.ERROR,
    "Automation references an entity that does not exist",
    AUTOMATIONS,
    why="The automation runs and the step silently does nothing. Nothing surfaces this "
        "until someone notices the lights did not come on.",
    tags=("automations", "health"),
)
def broken_reference(ctx: AuditContext) -> Iterator[Finding]:
    known = set(ctx.hass.states.async_entity_ids())
    known.update(e.entity_id for e in ctx.all_entities)

    for config in ctx.automation_configs:
        missing = sorted(_referenced_entities(config) - known)
        if missing:
            yield Finding(
                subject=config.get("alias") or config.get("id"),
                detail=f"references {', '.join(missing[:4])}"
                       + (f" and {len(missing) - 4} more" if len(missing) > 4 else ""),
                fix="Update the references or remove the steps that use them",
            )


@rule(
    "automation/device-trigger",
    Severity.WARNING,
    "Automation is bound to a device ID rather than an entity",
    AUTOMATIONS,
    why="Device IDs are internal and change when a device is removed and re-paired, "
        "which silently breaks the automation. Entity triggers survive re-pairing and "
        "are readable.",
    tags=("automations",),
)
def device_trigger(ctx: AuditContext) -> Iterator[Finding]:
    for config in ctx.automation_configs:
        device_ids = {
            value for key, value in _walk(config)
            if key == "device_id" and isinstance(value, str)
        }
        if not device_ids:
            continue
        names = []
        for device_id in list(device_ids)[:3]:
            device = ctx.devices.async_get(device_id)
            names.append(ctx.device_name(device) or device_id)
        yield Finding(
            subject=config.get("alias") or config.get("id"),
            detail=f"bound to {len(device_ids)} device ID(s): {', '.join(names)}",
            fix="Replace device triggers and actions with entity equivalents",
        )


@rule(
    "automation/never-triggered",
    Severity.INFO,
    "Automation has never run",
    AUTOMATIONS,
    why="Either its trigger never fires, or it is no longer wanted. Both are worth "
        "knowing before handing an instance over. Automations under a week old are "
        "given the benefit of the doubt.",
    tags=("automations",),
)
def never_triggered(ctx: AuditContext) -> Iterator[Finding]:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    grace = dt_util.utcnow() - timedelta(days=7)
    for state in ctx.hass.states.async_all("automation"):
        if state.state != "on" or state.attributes.get("last_triggered"):
            continue
        entry = ctx.entities.async_get(state.entity_id)
        if entry is not None and entry.created_at > grace:
            continue
        yield Finding(
            entity_id=state.entity_id,
            detail=f'"{state.attributes.get("friendly_name", state.entity_id)}" '
                   f"has no recorded run",
            fix="Verify the trigger, or disable the automation if it is obsolete",
        )


@rule(
    "automation/disabled",
    Severity.INFO,
    "Automation is turned off",
    AUTOMATIONS,
    why="A disabled automation is invisible until someone wonders why nothing happens.",
    tags=("automations",),
)
def disabled(ctx: AuditContext) -> Iterator[Finding]:
    for state in ctx.hass.states.async_all("automation"):
        if state.state == "off":
            yield Finding(
                entity_id=state.entity_id,
                detail=f'"{state.attributes.get("friendly_name", state.entity_id)}" '
                       f"is disabled",
                fix="Re-enable it, or delete it if it is no longer wanted",
            )
