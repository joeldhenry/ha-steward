"""Diagnostics and instance information."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper

from ..permissions import Access, Policy
from ._schema import Arg, tool


@tool(
    "ha_get_config",
    "Get core configuration: version, location, unit system and loaded components.",
    Access.READ,
)
async def get_config(hass: HomeAssistant, policy: Policy, _args: dict[str, Any]) -> Any:
    config = hass.config.as_dict()
    return {
        "version": config.get("version"),
        "location_name": config.get("location_name"),
        "time_zone": config.get("time_zone"),
        "currency": config.get("currency"),
        "country": config.get("country"),
        "unit_system": config.get("unit_system"),
        "components": len(config.get("components", [])),
        "connected_as": {"name": policy.user.name, "is_admin": policy.user.is_admin},
    }


@tool(
    "ha_render_template",
    "Render a Jinja2 template against live state. Use this to check a template before "
    "putting it in an automation.",
    Access.SENSITIVE,
    {
        "template": Arg("string", "Template string", required=True),
        "variables": Arg("object", "Variables to expose to the template", default={}),
    },
)
async def render_template(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    tpl = template_helper.Template(args["template"], hass)
    return {"result": tpl.async_render(variables=args.get("variables") or {}, parse_result=True)}


@tool(
    "ha_get_config_entries",
    "List configured integrations with their setup state, so you can see which failed "
    "to load or need reauthentication.",
    Access.SENSITIVE,
    {"domain": Arg("string", "Filter to one integration domain")},
)
async def get_config_entries(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    entries = hass.config_entries.async_entries(args.get("domain"))
    return [
        {
            "entry_id": entry.entry_id,
            "domain": entry.domain,
            "title": entry.title,
            "state": str(entry.state),
            "source": entry.source,
            "disabled_by": entry.disabled_by,
        }
        for entry in entries
    ]


@tool(
    "ha_reload",
    "Reload a config domain without restarting Home Assistant. Much faster than a "
    "restart when iterating on automations, scripts or templates.",
    Access.WRITE,
    {
        "domain": Arg(
            "string", "Domain to reload", required=True,
            enum=["automation", "script", "scene", "template", "input_boolean",
                  "input_select", "input_number", "input_datetime", "input_text", "all"],
        )
    },
)
async def reload(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    domain = args["domain"]
    if domain == "all":
        await hass.services.async_call("homeassistant", "reload_all", {}, blocking=True, context=policy.context)
    else:
        await hass.services.async_call(domain, "reload", {}, blocking=True, context=policy.context)
    return {"reloaded": domain}


@tool(
    "ha_restart",
    "Restart Home Assistant Core. Every integration reconnects and automations stop for "
    "the duration. Prefer ha_reload when only YAML config changed.",
    Access.DESTRUCTIVE,
    {"confirm": Arg("boolean", "Must be true", required=True)},
)
async def restart(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    if not args.get("confirm"):
        raise ValueError("Refusing to restart: pass confirm=true.")
    await hass.services.async_call("homeassistant", "restart", {}, blocking=False, context=policy.context)
    return {"restarting": True}
