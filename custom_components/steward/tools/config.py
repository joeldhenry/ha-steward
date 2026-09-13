"""Read and write automation, script and scene configuration.

These live in YAML files rather than the state machine: automations.yaml and
scenes.yaml are lists keyed by an ``id`` field, scripts.yaml is a mapping keyed
by object id. Home Assistant reloads the domain after a write, so changes take
effect without a restart.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from homeassistant.config import (
    AUTOMATION_CONFIG_PATH,
    SCENE_CONFIG_PATH,
    SCRIPT_CONFIG_PATH,
)
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import dump, load_yaml

from ..permissions import Access, Policy
from ._schema import Arg, tool

# Serialises read-modify-write so two concurrent edits cannot lose one another.
_WRITE_LOCK = asyncio.Lock()

KINDS: dict[str, dict[str, Any]] = {
    "automation": {"path": AUTOMATION_CONFIG_PATH, "keyed_by_id": True},
    "script": {"path": SCRIPT_CONFIG_PATH, "keyed_by_id": False},
    "scene": {"path": SCENE_CONFIG_PATH, "keyed_by_id": True},
}


def _read(path: str) -> Any:
    """Read a config file, treating a missing one as empty."""
    try:
        return load_yaml(path)
    except FileNotFoundError:
        return None


def _write(path: str, data: Any) -> None:
    # Serialise before truncating, so a dump failure cannot empty the file.
    contents = dump(data)
    with open(path, "w", encoding="utf8") as handle:
        handle.write(contents)


async def _validate(hass: HomeAssistant, kind: str, config_id: str, config: dict[str, Any]) -> None:
    """Run Home Assistant's own validator so a bad config is rejected before it lands."""
    if kind == "automation":
        from homeassistant.components.automation.config import async_validate_config_item

        await async_validate_config_item(hass, config_id, config)
    elif kind == "script":
        from homeassistant.components.script.config import async_validate_config_item

        await async_validate_config_item(hass, config_id, config)
    else:
        from homeassistant.components.scene import PLATFORM_SCHEMA

        PLATFORM_SCHEMA({"platform": "homeassistant", "scenes": [config]})


@tool(
    "ha_config",
    "Read and write automation, script and scene configuration: the triggers, "
    "conditions and actions themselves. 'list' and 'get' are the only way to see an "
    "automation's logic. Updates replace the whole config rather than merging, so call "
    "'get' first and send the complete object back. Home Assistant validates before "
    "saving and reloads the domain afterwards. Operates on automations.yaml, "
    "scripts.yaml and scenes.yaml, the files the UI editor uses. Automations kept in "
    "other files via !include are visible as entities but cannot be edited here.",
    Access.WRITE,
    {
        "action": Arg("string", "What to do", required=True,
                      enum=["list", "get", "create", "update", "delete"]),
        "kind": Arg("string", "Which config to act on", required=True,
                    enum=["automation", "script", "scene"]),
        "config_id": Arg(
            "string",
            "Identifier. For automations and scenes this is the 'id' field, not the "
            "entity_id. For scripts it is the object id, so script.evening_routine is "
            "'evening_routine'. Omit when creating; one is generated.",
        ),
        "config": Arg("object", "The configuration, for create and update"),
    },
    op_field="action",
    op_access={
        # Automation logic is admin-only to read in Home Assistant itself.
        "list": Access.SENSITIVE,
        "get": Access.SENSITIVE,
        "create": Access.WRITE,
        "update": Access.WRITE,
        "delete": Access.DESTRUCTIVE,
    },
)
async def config_tool(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    action = args["action"]
    kind = args["kind"]
    spec = KINDS[kind]
    path = hass.config.path(spec["path"])
    keyed_by_id = spec["keyed_by_id"]

    if action in ("list", "get"):
        current = await hass.async_add_executor_job(_read, path)
        if current is None:
            return [] if action == "list" else None

        if action == "list":
            if keyed_by_id:
                return [
                    {
                        "config_id": item.get("id"),
                        "alias": item.get("alias"),
                        "description": item.get("description"),
                    }
                    for item in current
                ]
            return [
                {"config_id": key, "alias": value.get("alias")}
                for key, value in current.items()
            ]

        config_id = args.get("config_id")
        if not config_id:
            raise ValueError("config_id is required to get a config")
        if keyed_by_id:
            found = next((i for i in current if str(i.get("id")) == config_id), None)
        else:
            found = current.get(config_id)
        if found is None:
            raise ValueError(f"No {kind} with config_id '{config_id}'")
        return found

    config_id = args.get("config_id")
    if action in ("update", "delete") and not config_id:
        raise ValueError(f"config_id is required to {action} a {kind}")
    if action == "create" and not config_id:
        config_id = str(int(time.time() * 1000))

    if action in ("create", "update"):
        config = args.get("config")
        if not config:
            raise ValueError(f"config is required to {action} a {kind}")
        await _validate(hass, kind, config_id, config)

    async with _WRITE_LOCK:
        current = await hass.async_add_executor_job(_read, path)
        if current is None:
            current = [] if keyed_by_id else {}

        if action == "delete":
            if keyed_by_id:
                remaining = [i for i in current if str(i.get("id")) != config_id]
                if len(remaining) == len(current):
                    raise ValueError(f"No {kind} with config_id '{config_id}'")
                current = remaining
            else:
                if config_id not in current:
                    raise ValueError(f"No {kind} with config_id '{config_id}'")
                current.pop(config_id)
        elif keyed_by_id:
            # Replace rather than merge. Merging would leave a trigger or
            # condition behind after it was removed from the new config.
            entry = {"id": config_id, **{k: v for k, v in config.items() if k != "id"}}
            index = next(
                (i for i, item in enumerate(current) if str(item.get("id")) == config_id), None
            )
            if index is None:
                if action == "update":
                    raise ValueError(f"No {kind} with config_id '{config_id}'")
                current.append(entry)
            else:
                current[index] = entry
        else:
            if action == "update" and config_id not in current:
                raise ValueError(f"No {kind} with config_id '{config_id}'")
            current[config_id] = config

        await hass.async_add_executor_job(_write, path, current)

    await hass.services.async_call(kind, "reload", {}, blocking=True)
    return {"action": action, "kind": kind, "config_id": config_id, "reloaded": True}
