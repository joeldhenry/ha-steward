"""Automation, script and scene tools."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..permissions import Access, Policy
from ._schema import Arg, tool


@tool(
    "ha_get_automations",
    "List automations with their entity_id, config id and last trigger time. The config "
    "id, not the entity_id, is what reads and writes the automation's logic.",
    Access.READ,
    {"search": Arg("string", "Case-insensitive substring matched against the name")},
)
async def get_automations(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    search = (args.get("search") or "").lower()
    results = []
    for state in hass.states.async_all("automation"):
        name = str(state.attributes.get("friendly_name", ""))
        if search and search not in name.lower():
            continue
        results.append(
            {
                "entity_id": state.entity_id,
                "name": name,
                "id": state.attributes.get("id"),
                "enabled": state.state == "on",
                "last_triggered": state.attributes.get("last_triggered"),
            }
        )
    return results


@tool(
    "ha_toggle_automation",
    "Enable or disable an automation without deleting it.",
    Access.WRITE,
    {
        "entity_id": Arg("string", "Automation entity_id", required=True),
        "enabled": Arg("boolean", "true to enable, false to disable", required=True),
    },
)
async def toggle_automation(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    service = "turn_on" if args["enabled"] else "turn_off"
    await hass.services.async_call(
        "automation", service, {"entity_id": args["entity_id"]}, blocking=True,
        context=policy.context,
    )
    return {"entity_id": args["entity_id"], "enabled": args["enabled"]}


@tool(
    "ha_trigger_automation",
    "Run an automation's actions immediately, bypassing its triggers.",
    Access.WRITE,
    {
        "entity_id": Arg("string", "Automation entity_id", required=True),
        "skip_condition": Arg(
            "boolean", "Run the actions even if conditions are not met", default=True
        ),
    },
)
async def trigger_automation(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    await hass.services.async_call(
        "automation",
        "trigger",
        {"entity_id": args["entity_id"], "skip_condition": args.get("skip_condition", True)},
        blocking=True,
        context=policy.context,
    )
    return {"triggered": args["entity_id"]}


@tool(
    "ha_run_script",
    "Run a script immediately.",
    Access.WRITE,
    {
        "entity_id": Arg("string", "Script entity_id", required=True),
        "variables": Arg("object", "Variables to pass into the script", default={}),
    },
)
async def run_script(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    data: dict[str, Any] = {"entity_id": args["entity_id"]}
    if args.get("variables"):
        data["variables"] = args["variables"]
    await hass.services.async_call("script", "turn_on", data, blocking=True, context=policy.context)
    return {"started": args["entity_id"]}


@tool(
    "ha_activate_scene",
    "Activate a scene, applying its stored entity states.",
    Access.WRITE,
    {
        "entity_id": Arg("string", "Scene entity_id", required=True),
        "transition": Arg("number", "Transition time in seconds"),
    },
)
async def activate_scene(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    data: dict[str, Any] = {"entity_id": args["entity_id"]}
    if args.get("transition") is not None:
        data["transition"] = args["transition"]
    await hass.services.async_call("scene", "turn_on", data, blocking=True, context=policy.context)
    return {"activated": args["entity_id"]}
