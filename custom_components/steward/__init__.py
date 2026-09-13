"""Steward: a Model Context Protocol server that runs inside Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, MCP_PATH
from .http import async_register_http

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register the MCP endpoint."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry

    # Views cannot be unregistered, so register once however many entries exist.
    if not hass.data[DOMAIN].get("_view_registered"):
        async_register_http(hass)
        hass.data[DOMAIN]["_view_registered"] = True
        _LOGGER.info("MCP server listening on %s", MCP_PATH)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change so permission changes take effect."""
    await hass.config_entries.async_reload(entry.entry_id)
