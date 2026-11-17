"""Registry access that reads the same on every supported Home Assistant.

2026.10 reshaped the device registry. A device now belongs to one config entry,
`DeviceRegistry.devices` stopped being a mapping, and a part of a device that
can sit in its own room, such as one gang of a wall switch, became a child
device with its own area. A child carries only a name, an area and labels; the
manufacturer, model and entry type live on its parent. The same release stopped
an entity that has no name of its own from holding an area override, because
that entity stands for its device.

Everything Steward needs from that model goes through here, so the tools and
the audit rules do not each have to know which release they are running on.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.helpers import device_registry as dr, entity_registry as er

# Absent before 2026.10, where no device has a parent.
_ChildDeviceEntry: type | None = getattr(dr, "ChildDeviceEntry", None)
_children_of = getattr(dr, "async_entries_for_parent_device", None)
_entity_aliases = getattr(er, "async_get_entity_aliases", None)


def is_child(device: Any) -> bool:
    """Whether this is a child device, which has no hardware details of its own."""
    return _ChildDeviceEntry is not None and isinstance(device, _ChildDeviceEntry)


def all_devices(registry: dr.DeviceRegistry, *, children: bool = True) -> list[Any]:
    """Every device, each followed by its child devices."""
    view = registry.devices
    # A mapping until 2026.10; from then on iterating yields the entries and the
    # mapping methods log a deprecation that becomes an error in 2027.9.
    main = list(view.values()) if isinstance(view, Mapping) else list(view)
    if not children or _children_of is None:
        return main
    result: list[Any] = []
    for device in main:
        result.append(device)
        result.extend(_children_of(registry, device.id))
    return result


def parent_of(registry: dr.DeviceRegistry, device: Any) -> Any | None:
    """The device a child device is part of, or None for a main device."""
    if not is_child(device):
        return None
    return registry.async_get(device.parent_device_id)


def hardware_of(registry: dr.DeviceRegistry, device: Any) -> Any:
    """The entry that holds manufacturer, model, firmware and entry type."""
    return parent_of(registry, device) or device


def device_area_id(registry: dr.DeviceRegistry, device: Any | None) -> str | None:
    """The area a device is in. A child without one of its own is in its parent's."""
    if device is None:
        return None
    if device.area_id:
        return device.area_id
    parent = parent_of(registry, device)
    return parent.area_id if parent else None


def entity_area_id(
    registry: dr.DeviceRegistry, entry: er.RegistryEntry
) -> str | None:
    """Effective area of an entity: its own override, else its device's."""
    if entry.area_id:
        return entry.area_id
    if not entry.device_id:
        return None
    return device_area_id(registry, registry.async_get(entry.device_id))


def is_service(registry: dr.DeviceRegistry, device: Any | None) -> bool:
    """A service device, such as a weather feed, which never occupies a room."""
    if device is None:
        return False
    return hardware_of(registry, device).entry_type == dr.DeviceEntryType.SERVICE


def update_device(registry: dr.DeviceRegistry, device: Any, **changes: Any) -> Any:
    """Apply user-editable changes to a device or a child device."""
    if is_child(device):
        return registry.async_update_child_device(device.id, **changes)
    return registry.async_update_device(device.id, **changes)


def has_own_name(entry: er.RegistryEntry) -> bool:
    """Whether the entity is named apart from its device.

    An entity without a name of its own is the main entity of its device. From
    2026.10 it cannot hold an area override: its room is its device's room.
    Earlier releases have no such rule, so every entity counts as named there.
    """
    if not hasattr(entry, "entity_name"):
        return True
    return bool(entry.entity_name)


def accepts_own_area(entry: er.RegistryEntry) -> bool:
    """Whether Home Assistant will store an area override on this entity."""
    return entry.device_id is None or has_own_name(entry)


def aliases_of(hass: Any, entry: er.RegistryEntry) -> list[str]:
    """An entity's aliases as text.

    From 2026.x the list can hold a marker meaning "the entity's computed name",
    which is not a string and does not sort against one.
    """
    if _entity_aliases is not None:
        return list(_entity_aliases(hass, entry))
    return sorted(str(alias) for alias in entry.aliases)
