"""Dead, broken and orphaned things."""

from __future__ import annotations

from collections.abc import Iterator

from homeassistant.config_entries import ConfigEntryState

from ..context import AuditContext
from ..model import Finding, Severity, rule

ONBOARDING = "ha://knowledge/onboarding"


@rule(
    "entity/unavailable",
    Severity.WARNING,
    "Entity is unavailable or unknown",
    ONBOARDING,
    why="It shows as unavailable on every dashboard card that includes it, and any "
        "automation acting on it silently does nothing.",
    tags=("health", "dashboard"),
)
def unavailable(ctx: AuditContext) -> Iterator[Finding]:
    for entry in ctx.live_entities:
        state = ctx.state_of(entry.entity_id)
        if state is None or state.state not in ("unavailable", "unknown"):
            continue
        yield Finding(
            entity_id=entry.entity_id,
            detail=f"state is {state.state}",
            fix="Remove the integration if the hardware is gone, or disable the entity",
        )


@rule(
    "entity/orphaned",
    Severity.ERROR,
    "Entity belongs to an integration that no longer exists",
    ONBOARDING,
    why="The registry entry survives after its integration is removed, holding the "
        "entity ID hostage so the replacement device gets a _2 suffix.",
    tags=("health",),
)
def orphaned(ctx: AuditContext) -> Iterator[Finding]:
    known = ctx.config_entry_ids
    for entry in ctx.all_entities:
        if entry.config_entry_id and entry.config_entry_id not in known:
            yield Finding(
                entity_id=entry.entity_id,
                detail=f"config entry {entry.config_entry_id} is gone",
                fix="Delete the registry entry to free the entity ID",
            )


@rule(
    "device/offline",
    Severity.WARNING,
    "Every entity on a device is unavailable",
    ONBOARDING,
    why="One unavailable entity can be normal; all of them means the device is off, "
        "unplugged, or off the network.",
    tags=("health",),
)
def device_offline(ctx: AuditContext) -> Iterator[Finding]:
    by_device: dict[str, list[str]] = {}
    for entry in ctx.live_entities:
        if entry.device_id:
            by_device.setdefault(entry.device_id, []).append(entry.entity_id)

    for device_id, entity_ids in by_device.items():
        states = [ctx.state_of(e) for e in entity_ids]
        present = [s for s in states if s is not None]
        if len(present) < 2:
            continue
        if all(s.state == "unavailable" for s in present):
            device = ctx.devices.async_get(device_id)
            yield Finding(
                device=ctx.device_name(device),
                detail=f"all {len(present)} entities unavailable",
                fix="Check power and network, or remove the device if it is gone",
            )


@rule(
    "integration/not-loaded",
    Severity.ERROR,
    "Integration failed to load",
    ONBOARDING,
    why="Everything it provides is missing, so dashboards show unavailable cards and "
        "automations that use it do nothing.",
    tags=("health",),
)
def integration_not_loaded(ctx: AuditContext) -> Iterator[Finding]:
    healthy = {ConfigEntryState.LOADED, ConfigEntryState.NOT_LOADED}
    for entry in ctx.hass.config_entries.async_entries():
        if entry.disabled_by or entry.state in healthy:
            continue
        reason = f" ({entry.reason})" if getattr(entry, "reason", None) else ""
        yield Finding(
            subject=entry.title,
            detail=f"{entry.domain} is {entry.state}{reason}",
            fix="Reconfigure or reload the integration; if it needs reauthentication, "
                "complete that in Settings",
        )
