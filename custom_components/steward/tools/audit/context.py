"""Everything the rules read, loaded once per audit."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)

# Domains a person targets by room, and which a voice assistant is asked about.
# Area and duplication rules apply only to these, so a vacuum's per-room
# settings and a phone's notify entity do not generate noise.
CONTROLLABLE = frozenset(
    {"light", "switch", "fan", "cover", "lock", "valve", "siren",
     "climate", "media_player", "humidifier", "water_heater", "vacuum"}
)

# Entities a companion app or voice assistant can act on directly.
ACTIONABLE = CONTROLLABLE | {"scene", "script", "button", "input_boolean"}

HEX_BLOB = re.compile(r"(?:^|_)(?:0x)?[0-9a-f]{6,}(?:_|$)", re.IGNORECASE)


@dataclass(slots=True)
class AuditContext:
    """Registries and state, resolved once and shared by every rule."""

    hass: HomeAssistant
    entities: er.EntityRegistry
    devices: dr.DeviceRegistry
    areas: ar.AreaRegistry
    floors: fr.FloorRegistry
    labels: lr.LabelRegistry
    _cache: dict[str, Any] = field(default_factory=dict)

    automation_configs: list[dict[str, Any]] = field(default_factory=list)
    """Parsed automations.yaml. Automation state attributes do not carry config."""
    script_configs: dict[str, Any] = field(default_factory=dict)
    dashboards: dict[str, Any] = field(default_factory=dict)
    """url_path -> stored Lovelace config, for dashboards that have one."""

    @classmethod
    async def build(cls, hass: HomeAssistant) -> AuditContext:
        ctx = cls(
            hass=hass,
            entities=er.async_get(hass),
            devices=dr.async_get(hass),
            areas=ar.async_get(hass),
            floors=fr.async_get(hass),
            labels=lr.async_get(hass),
        )
        ctx.automation_configs = await _load_yaml_list(hass, "automations.yaml")
        ctx.script_configs = await _load_yaml_dict(hass, "scripts.yaml")
        ctx.dashboards = await _load_dashboards(hass)
        return ctx

    # --- collections ----------------------------------------------------

    @property
    def all_entities(self) -> list[er.RegistryEntry]:
        if "entities" not in self._cache:
            self._cache["entities"] = list(self.entities.entities.values())
        return self._cache["entities"]

    @property
    def live_entities(self) -> list[er.RegistryEntry]:
        """Registry entries that are not disabled."""
        if "live" not in self._cache:
            self._cache["live"] = [e for e in self.all_entities if not e.disabled_by]
        return self._cache["live"]

    @property
    def all_devices(self) -> list[dr.DeviceEntry]:
        if "devices" not in self._cache:
            self._cache["devices"] = list(self.devices.devices.values())
        return self._cache["devices"]

    @property
    def physical_devices(self) -> list[dr.DeviceEntry]:
        """Devices that occupy a room. Service devices never will."""
        if "physical" not in self._cache:
            self._cache["physical"] = [
                d for d in self.all_devices
                if d.entry_type != dr.DeviceEntryType.SERVICE and not d.disabled_by
            ]
        return self._cache["physical"]

    @property
    def area_list(self) -> list[ar.AreaEntry]:
        if "areas" not in self._cache:
            self._cache["areas"] = list(self.areas.async_list_areas())
        return self._cache["areas"]

    @property
    def floor_list(self) -> list[fr.FloorEntry]:
        if "floors" not in self._cache:
            self._cache["floors"] = list(self.floors.async_list_floors())
        return self._cache["floors"]

    # --- lookups --------------------------------------------------------

    def device_of(self, entry: er.RegistryEntry) -> dr.DeviceEntry | None:
        return self.devices.async_get(entry.device_id) if entry.device_id else None

    def area_id_of(self, entry: er.RegistryEntry) -> str | None:
        """Effective area: the entity's override, else its device's."""
        if entry.area_id:
            return entry.area_id
        device = self.device_of(entry)
        return device.area_id if device else None

    def area_name(self, area_id: str | None) -> str:
        if not area_id:
            return ""
        area = self.areas.async_get_area(area_id)
        return area.name if area else ""

    def device_name(self, device: dr.DeviceEntry | None) -> str:
        if device is None:
            return ""
        return device.name_by_user or device.name or ""

    def state_of(self, entity_id: str) -> State | None:
        return self.hass.states.get(entity_id)

    def display_name(self, entry: er.RegistryEntry) -> str:
        """What a person or a voice assistant actually sees."""
        state = self.state_of(entry.entity_id)
        if state and (name := state.attributes.get("friendly_name")):
            return str(name)
        return entry.name or entry.original_name or ""

    def is_primary(self, entry: er.RegistryEntry) -> bool:
        """A control rather than a diagnostic or configuration entity."""
        return entry.entity_category is None

    def is_service_entity(self, entry: er.RegistryEntry) -> bool:
        device = self.device_of(entry)
        return device is not None and device.entry_type == dr.DeviceEntryType.SERVICE

    def mentions_area(self, text: str, area_name: str) -> bool:
        """Whole-word match, so 'Bedroom' does not match inside 'Bedrooms'."""
        return re.search(rf"\b{re.escape(area_name)}\b", text, re.IGNORECASE) is not None

    # --- config entries -------------------------------------------------

    @property
    def config_entry_ids(self) -> set[str]:
        if "entry_ids" not in self._cache:
            self._cache["entry_ids"] = {
                e.entry_id for e in self.hass.config_entries.async_entries()
            }
        return self._cache["entry_ids"]


async def _load_yaml_list(hass: HomeAssistant, filename: str) -> list[dict[str, Any]]:
    """Read a list-shaped config file, tolerating its absence."""
    from homeassistant.util.yaml import load_yaml

    def read() -> Any:
        try:
            return load_yaml(hass.config.path(filename))
        except (FileNotFoundError, HomeAssistantError):
            return None

    data = await hass.async_add_executor_job(read)
    return data if isinstance(data, list) else []


async def _load_yaml_dict(hass: HomeAssistant, filename: str) -> dict[str, Any]:
    from homeassistant.util.yaml import load_yaml

    def read() -> Any:
        try:
            return load_yaml(hass.config.path(filename))
        except (FileNotFoundError, HomeAssistantError):
            return None

    data = await hass.async_add_executor_job(read)
    return data if isinstance(data, dict) else {}


async def _load_dashboards(hass: HomeAssistant) -> dict[str, Any]:
    """Stored Lovelace configs, keyed by url_path.

    Dashboards left on the auto-generated strategy have no stored config. That is
    not an error; it is the default, and the reason area data matters.
    """
    if "lovelace" not in hass.config.components:
        return {}
    try:
        from homeassistant.components.lovelace.const import DOMAIN as LOVELACE_DOMAIN
    except ImportError:
        return {}

    data = hass.data.get(LOVELACE_DOMAIN)
    stores = getattr(data, "dashboards", None)
    if not isinstance(stores, dict):
        return {}

    configs: dict[str, Any] = {}
    for url_path, store in stores.items():
        try:
            configs[url_path or "lovelace"] = await store.async_load(False)
        except Exception:  # noqa: BLE001 - a dashboard without stored config is normal
            continue
    return configs
