"""Device, entity, area and floor registry tools.

In-process access to the registries, which over the network are reachable only
through the WebSocket API.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)

from ..permissions import Access, Policy
from ._schema import Arg, tool


@tool(
    "ha_get_devices",
    "List devices with manufacturer, model, firmware and area. Optionally filter by a "
    "substring of the name, manufacturer or model.",
    Access.SENSITIVE,
    {
        "search": Arg("string", "Case-insensitive substring"),
        "area_id": Arg("string", "Only devices in this area"),
        "without_area": Arg("boolean", "Only devices with no area assigned", default=False),
    },
)
async def get_devices(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    devices = dr.async_get(hass)
    search = (args.get("search") or "").lower()

    results = []
    for device in devices.devices.values():
        if args.get("area_id") and device.area_id != args["area_id"]:
            continue
        if args.get("without_area") and device.area_id:
            continue
        name = device.name_by_user or device.name or ""
        haystack = f"{name} {device.manufacturer or ''} {device.model or ''}".lower()
        if search and search not in haystack:
            continue
        results.append(
            {
                "id": device.id,
                "name": name,
                "manufacturer": device.manufacturer,
                "model": device.model,
                "sw_version": device.sw_version,
                "area_id": device.area_id,
                "is_service": device.entry_type == dr.DeviceEntryType.SERVICE,
                "disabled": bool(device.disabled_by),
            }
        )
    return results


@tool(
    "ha_get_entity_registry",
    "List entity registry entries showing device, area, category and whether each is "
    "disabled or hidden. Unlike ha_get_states this includes disabled entities and the "
    "integration providing each one.",
    Access.SENSITIVE,
    {
        "domain": Arg("string", "Filter by domain"),
        "device_id": Arg("string", "Only entities on this device"),
        "area_id": Arg("string", "Only entities in this area"),
        "platform": Arg("string", "Only entities from this integration, e.g. 'zha'"),
    },
)
async def get_entity_registry(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    entities = er.async_get(hass)
    devices = dr.async_get(hass)

    results = []
    for entry in entities.entities.values():
        if args.get("domain") and entry.domain != args["domain"]:
            continue
        if args.get("device_id") and entry.device_id != args["device_id"]:
            continue
        if args.get("platform") and entry.platform != args["platform"]:
            continue

        device = devices.async_get(entry.device_id) if entry.device_id else None
        effective_area = entry.area_id or (device.area_id if device else None)
        if args.get("area_id") and effective_area != args["area_id"]:
            continue

        results.append(
            {
                "entity_id": entry.entity_id,
                "name": entry.name or entry.original_name,
                "platform": entry.platform,
                "device_id": entry.device_id,
                "area_id": effective_area,
                "area_is_override": entry.area_id is not None,
                "entity_category": entry.entity_category,
                "disabled": bool(entry.disabled_by),
                "hidden": bool(entry.hidden_by),
            }
        )
    return results


@tool(
    "ha_update_entity",
    "Update an entity's registry entry: rename it, change its entity_id, override its "
    "area, set an icon, or hide/disable it. Only the fields you pass are changed. "
    "Changing entity_id breaks automations, scripts and dashboards that reference the "
    "old one, so search for references first.",
    Access.WRITE,
    {
        "entity_id": Arg("string", "Current entity ID", required=True),
        "name": Arg("string", "New friendly name"),
        "new_entity_id": Arg("string", "Rename the entity ID itself"),
        "area_id": Arg(
            "string",
            "Area to assign this entity to, overriding its device's area. Pass an empty "
            "string to clear the override and inherit from the device again.",
        ),
        "icon": Arg("string", "MDI icon, e.g. 'mdi:thermometer'"),
        "hidden": Arg("boolean", "Hide from the UI without disabling it"),
        "disabled": Arg("boolean", "Stop the entity being updated at all"),
        "labels": Arg("array", "Replace the entity's labels with these label ids", items={"type": "string"}),
    },
)
async def update_entity(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    entities = er.async_get(hass)
    entity_id = args["entity_id"]
    if entities.async_get(entity_id) is None:
        raise ValueError(f"No such entity in the registry: {entity_id}")

    changes: dict[str, Any] = {}
    if args.get("name") is not None:
        changes["name"] = args["name"]
    if args.get("new_entity_id"):
        changes["new_entity_id"] = args["new_entity_id"]
    if args.get("icon") is not None:
        changes["icon"] = args["icon"]
    if (area := args.get("area_id")) is not None:
        # An empty string clears the override rather than setting a blank area.
        changes["area_id"] = area or None
    if args.get("hidden") is not None:
        changes["hidden_by"] = er.RegistryEntryHider.USER if args["hidden"] else None
    if args.get("disabled") is not None:
        changes["disabled_by"] = er.RegistryEntryDisabler.USER if args["disabled"] else None
    if args.get("labels") is not None:
        changes["labels"] = set(args["labels"])

    if not changes:
        raise ValueError("Nothing to update; pass at least one field to change.")

    updated = entities.async_update_entity(entity_id, **changes)
    return {
        "entity_id": updated.entity_id,
        "name": updated.name,
        "area_id": updated.area_id,
        "changed": sorted(changes),
    }


@tool(
    "ha_update_device",
    "Update a device's registry entry: assign it to an area, rename it, or disable it. "
    "Every entity on the device inherits the area unless it carries its own override, "
    "so this is the right fix when a whole device is in the wrong room or none. Pass "
    "an empty area_id to remove the device from its area.",
    Access.WRITE,
    {
        "device_id": Arg("string", "Device ID from ha_get_devices", required=True),
        "area_id": Arg(
            "string",
            "Area to place the device in. An empty string clears it, which is correct "
            "for service devices such as weather or fire-danger feeds.",
        ),
        "name": Arg("string", "Name shown for the device, overriding the integration's"),
        "disabled": Arg("boolean", "Disable the device and all its entities"),
        "labels": Arg("array", "Replace the device's labels with these label ids", items={"type": "string"}),
    },
)
async def update_device(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    devices = dr.async_get(hass)
    device_id = args["device_id"]
    if devices.async_get(device_id) is None:
        raise ValueError(f"No such device: {device_id}")

    changes: dict[str, Any] = {}
    if (area := args.get("area_id")) is not None:
        changes["area_id"] = area or None
    if args.get("name") is not None:
        changes["name_by_user"] = args["name"] or None
    if args.get("disabled") is not None:
        changes["disabled_by"] = dr.DeviceEntryDisabler.USER if args["disabled"] else None
    if args.get("labels") is not None:
        changes["labels"] = set(args["labels"])
    if not changes:
        raise ValueError("Nothing to update; pass at least one field to change.")

    updated = devices.async_update_device(device_id, **changes)
    return {
        "device_id": updated.id,
        "name": updated.name_by_user or updated.name,
        "area_id": updated.area_id,
        "disabled": bool(updated.disabled_by),
        "changed": sorted(changes),
    }


@tool(
    "ha_get_areas",
    "List areas with their floor, aliases and the number of devices and entities in each.",
    Access.SENSITIVE,
)
async def get_areas(hass: HomeAssistant, _policy: Policy, _args: dict[str, Any]) -> Any:
    areas = ar.async_get(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    device_counts: dict[str, int] = {}
    for device in devices.devices.values():
        if device.area_id:
            device_counts[device.area_id] = device_counts.get(device.area_id, 0) + 1

    entity_counts: dict[str, int] = {}
    for entry in entities.entities.values():
        device = devices.async_get(entry.device_id) if entry.device_id else None
        area = entry.area_id or (device.area_id if device else None)
        if area:
            entity_counts[area] = entity_counts.get(area, 0) + 1

    return [
        {
            "area_id": area.id,
            "name": area.name,
            "floor_id": area.floor_id,
            "aliases": sorted(area.aliases),
            "devices": device_counts.get(area.id, 0),
            "entities": entity_counts.get(area.id, 0),
        }
        for area in areas.async_list_areas()
    ]


@tool(
    "ha_manage_area",
    "Create, rename or delete an area, or assign it to a floor.",
    Access.WRITE,
    {
        "action": Arg("string", "What to do", required=True, enum=["create", "update", "delete"]),
        "area_id": Arg("string", "Area to update or delete"),
        "name": Arg("string", "Area name, for create or rename"),
        "floor_id": Arg("string", "Floor to place the area on"),
        "icon": Arg("string", "MDI icon"),
    },
    op_field="action",
    op_access={
        "create": Access.WRITE,
        "update": Access.WRITE,
        "delete": Access.DESTRUCTIVE,
    },
)
async def manage_area(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    areas = ar.async_get(hass)
    action = args["action"]

    if action == "create":
        if not args.get("name"):
            raise ValueError("name is required to create an area")
        area = areas.async_create(
            args["name"], floor_id=args.get("floor_id"), icon=args.get("icon")
        )
        return {"created": area.id, "name": area.name}

    if not args.get("area_id"):
        raise ValueError(f"area_id is required to {action} an area")

    if action == "delete":
        # Deleting an area unassigns every device and entity in it.
        areas.async_delete(args["area_id"])
        return {"deleted": args["area_id"]}

    changes = {k: args[k] for k in ("name", "floor_id", "icon") if args.get(k) is not None}
    if not changes:
        raise ValueError("Nothing to update")
    area = areas.async_update(args["area_id"], **changes)
    return {"updated": area.id, "name": area.name, "floor_id": area.floor_id}


@tool(
    "ha_get_floors",
    "List floors. Devices and entities cannot be assigned to a floor directly; they "
    "inherit it from their area.",
    Access.SENSITIVE,
)
async def get_floors(hass: HomeAssistant, _policy: Policy, _args: dict[str, Any]) -> Any:
    floors = fr.async_get(hass)
    return [
        {"floor_id": f.floor_id, "name": f.name, "level": f.level, "icon": f.icon}
        for f in floors.async_list_floors()
    ]


@tool(
    "ha_create_floor",
    "Create a floor so areas on the same level can be targeted together.",
    Access.WRITE,
    {
        "name": Arg("string", "Floor name, e.g. 'Upstairs'", required=True),
        "level": Arg("integer", "Storey number; 0 is ground level"),
        "icon": Arg("string", "MDI icon"),
    },
)
async def create_floor(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    floors = fr.async_get(hass)
    floor = floors.async_create(args["name"], level=args.get("level"), icon=args.get("icon"))
    return {"created": floor.floor_id, "name": floor.name}


@tool(
    "ha_get_labels",
    "List labels. Labels tag areas, devices, entities and automations across domains "
    "and are the right tool for groupings that are not rooms.",
    Access.SENSITIVE,
)
async def get_labels(hass: HomeAssistant, _policy: Policy, _args: dict[str, Any]) -> Any:
    labels = lr.async_get(hass)
    return [
        {"label_id": item.label_id, "name": item.name, "color": item.color, "icon": item.icon}
        for item in labels.async_list_labels()
    ]


@tool(
    "ha_manage_label",
    "Create, rename or delete a label. Labels are the right home for groupings that "
    "are not rooms, such as 'All House' or 'Integrations'; assign them with the "
    "labels field on ha_update_entity, ha_update_device or ha_manage_area.",
    Access.WRITE,
    {
        "action": Arg("string", "What to do", required=True, enum=["create", "update", "delete"]),
        "label_id": Arg("string", "Label to update or delete"),
        "name": Arg("string", "Label name, for create or rename"),
        "color": Arg("string", "Colour name or hex, e.g. 'indigo' or '#3f51b5'"),
        "icon": Arg("string", "MDI icon"),
        "description": Arg("string", "What the label is for"),
    },
    op_field="action",
    op_access={"create": Access.WRITE, "update": Access.WRITE, "delete": Access.DESTRUCTIVE},
)
async def manage_label(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    labels = lr.async_get(hass)
    action = args["action"]
    extra = {k: args[k] for k in ("color", "icon", "description") if args.get(k) is not None}

    if action == "create":
        if not args.get("name"):
            raise ValueError("name is required to create a label")
        label = labels.async_create(args["name"], **extra)
        return {"created": label.label_id, "name": label.name}

    if not args.get("label_id"):
        raise ValueError(f"label_id is required to {action} a label")
    if action == "delete":
        labels.async_delete(args["label_id"])
        return {"deleted": args["label_id"]}

    changes = dict(extra)
    if args.get("name"):
        changes["name"] = args["name"]
    if not changes:
        raise ValueError("Nothing to update")
    label = labels.async_update(args["label_id"], **changes)
    return {"updated": label.label_id, "name": label.name}


@tool(
    "ha_remove_entity",
    "Delete an entity's registry entry. This is the fix for an orphaned entity whose "
    "integration is gone, or one left over from removed hardware, and it frees the "
    "entity_id for reuse. Anything referencing the entity stops working.",
    Access.DESTRUCTIVE,
    {"entity_id": Arg("string", "Entity to remove", required=True)},
)
async def remove_entity(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    entities = er.async_get(hass)
    if entities.async_get(args["entity_id"]) is None:
        raise ValueError(f"No such entity in the registry: {args['entity_id']}")
    entities.async_remove(args["entity_id"])
    return {"removed": args["entity_id"]}


@tool(
    "ha_remove_device",
    "Delete a device and every entity on it from the registries. Use it for ghost "
    "devices whose integration has forgotten them, such as entries with an unknown "
    "manufacturer and only unavailable entities. A device its integration still "
    "provides will be recreated on the next reload.",
    Access.DESTRUCTIVE,
    {"device_id": Arg("string", "Device to remove", required=True)},
)
async def remove_device(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    devices = dr.async_get(hass)
    device = devices.async_get(args["device_id"])
    if device is None:
        raise ValueError(f"No such device: {args['device_id']}")
    name = device.name_by_user or device.name
    entities = er.async_get(hass)
    removed = [e.entity_id for e in entities.entities.values() if e.device_id == device.id]
    devices.async_remove_device(device.id)
    return {"removed_device": name, "removed_entities": removed}


def _decode_features(domain: str, value: int) -> list[str] | int:
    """Translate a supported_features bitmask into flag names where the domain has them."""
    import importlib

    class_name = {
        "alarm_control_panel": "AlarmControlPanelEntityFeature",
        "camera": "CameraEntityFeature",
        "climate": "ClimateEntityFeature",
        "cover": "CoverEntityFeature",
        "fan": "FanEntityFeature",
        "humidifier": "HumidifierEntityFeature",
        "light": "LightEntityFeature",
        "lock": "LockEntityFeature",
        "media_player": "MediaPlayerEntityFeature",
        "remote": "RemoteEntityFeature",
        "siren": "SirenEntityFeature",
        "update": "UpdateEntityFeature",
        "vacuum": "VacuumEntityFeature",
        "valve": "ValveEntityFeature",
        "water_heater": "WaterHeaterEntityFeature",
    }.get(domain)
    if not class_name:
        return value
    try:
        flag = getattr(importlib.import_module(f"homeassistant.components.{domain}"), class_name)
    except (ImportError, AttributeError):
        return value
    return [member.name for member in flag if member.value and value & member.value == member.value]


@tool(
    "ha_describe_entity",
    "Everything about one entity in a single call: current state and attributes, its "
    "registry entry, the device it belongs to, its effective area and floor, labels, "
    "the features it supports by name rather than as a bitmask, and the services its "
    "domain accepts. Use it before acting on an entity you have not seen before.",
    Access.SENSITIVE,
    {"entity_id": Arg("string", "Entity to describe", required=True)},
)
async def describe_entity(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    entity_id = args["entity_id"]
    if not policy.can_read_entity(entity_id):
        raise ValueError(f"No such entity: {entity_id}")

    state = hass.states.get(entity_id)
    entry = er.async_get(hass).async_get(entity_id)
    if state is None and entry is None:
        raise ValueError(f"No such entity: {entity_id}")

    domain = entity_id.split(".")[0]
    device = dr.async_get(hass).async_get(entry.device_id) if entry and entry.device_id else None
    area_id = (entry.area_id if entry else None) or (device.area_id if device else None)
    area = ar.async_get(hass).async_get_area(area_id) if area_id else None
    floor = fr.async_get(hass).async_get_floor(area.floor_id) if area and area.floor_id else None
    features = state.attributes.get("supported_features") if state else None

    return {
        "entity_id": entity_id,
        "state": state.state if state else None,
        "last_changed": state.last_changed if state else None,
        "attributes": dict(state.attributes) if state else {},
        "supported_features": _decode_features(domain, int(features)) if isinstance(features, int) else features,
        "registry": {
            "name": entry.name if entry else None,
            "original_name": entry.original_name if entry else None,
            "platform": entry.platform if entry else None,
            "unique_id": entry.unique_id if entry else None,
            "entity_category": entry.entity_category if entry else None,
            "device_class": (entry.device_class or entry.original_device_class) if entry else None,
            "disabled": bool(entry.disabled_by) if entry else None,
            "hidden": bool(entry.hidden_by) if entry else None,
            "area_is_override": bool(entry.area_id) if entry else None,
            "labels": sorted(entry.labels) if entry else [],
            "aliases": sorted(entry.aliases) if entry else [],
        } if entry else None,
        "device": {
            "id": device.id,
            "name": device.name_by_user or device.name,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "sw_version": device.sw_version,
            "area_id": device.area_id,
        } if device else None,
        "area": {"area_id": area.id, "name": area.name} if area else None,
        "floor": {"floor_id": floor.floor_id, "name": floor.name} if floor else None,
        "services": sorted(hass.services.async_services_for_domain(domain)),
    }
