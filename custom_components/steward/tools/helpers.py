"""Helpers: the input_*, counter, timer and schedule entities people build
automations around. Each domain stores its items in a collection reachable
only through its WebSocket commands, so everything here goes through the bridge."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..permissions import Access, Policy
from ..ws_bridge import ws_call
from ._schema import Arg, tool

HELPER_KINDS = (
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "counter",
    "timer",
    "schedule",
)


@tool(
    "ha_helper",
    "Create, list, update or delete helper entities: input_boolean, input_number, "
    "input_select, input_text, input_datetime, counter, timer and schedule. Fields "
    "follow Home Assistant's own schema for each kind: every kind takes a 'name'; "
    "input_number takes min, max, step, mode, unit_of_measurement; input_select takes "
    "options; input_datetime takes has_date and has_time; timer takes duration; "
    "schedule takes a day-keyed list of from/to ranges. Only fields you pass are "
    "changed on update. Helpers defined in YAML cannot be edited here.",
    Access.WRITE,
    {
        "action": Arg("string", "What to do", required=True,
                      enum=["list", "create", "update", "delete"]),
        "kind": Arg("string", "Helper domain", required=True, enum=list(HELPER_KINDS)),
        "helper_id": Arg("string", "Helper id from 'list' (the object id, not the entity_id)"),
        "fields": Arg("object", "Fields for create or update, e.g. {\"name\": \"Guest mode\"}"),
    },
    op_field="action",
    op_access={
        "list": Access.READ,
        "create": Access.WRITE,
        "update": Access.WRITE,
        "delete": Access.DESTRUCTIVE,
    },
)
async def helper(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    action, kind = args["action"], args["kind"]
    helper_id = args.get("helper_id")
    fields = args.get("fields") or {}

    if action == "list":
        return await ws_call(hass, policy, f"{kind}/list")

    if action == "create":
        if not fields.get("name"):
            raise ValueError("fields.name is required to create a helper")
        return await ws_call(hass, policy, f"{kind}/create", **fields)

    if not helper_id:
        raise ValueError(f"helper_id is required to {action} a {kind}")

    if action == "delete":
        await ws_call(hass, policy, f"{kind}/delete", **{f"{kind}_id": helper_id})
        return {"deleted": f"{kind}.{helper_id}"}

    if not fields:
        raise ValueError("fields is required to update a helper")
    return await ws_call(hass, policy, f"{kind}/update", **{f"{kind}_id": helper_id}, **fields)
