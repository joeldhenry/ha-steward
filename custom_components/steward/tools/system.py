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


@tool(
    "ha_check_config",
    "Validate the whole YAML configuration the way Settings, System, Check "
    "configuration does. Run it before ha_restart; a restart with a broken config "
    "leaves the instance in safe mode.",
    Access.SENSITIVE,
)
async def check_config(hass: HomeAssistant, _policy: Policy, _args: dict[str, Any]) -> Any:
    from homeassistant.config import async_check_ha_config_file

    error = await async_check_ha_config_file(hass)
    return {"valid": error is None, "errors": error}


@tool(
    "ha_validate_config",
    "Validate automation building blocks without saving anything: a list of triggers, "
    "conditions or actions. Returns the normalised form Home Assistant would store, "
    "or the validation error. Use it to check a fragment before assembling an "
    "automation with ha_config.",
    Access.READ,
    {
        "kind": Arg("string", "Which block type", required=True,
                    enum=["triggers", "conditions", "actions"]),
        "config": Arg("array", "The list of blocks to validate", required=True,
                      items={"type": "object"}),
    },
)
async def validate_config(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    from homeassistant.helpers import condition, config_validation as cv, script, trigger

    # Two steps, in the order Home Assistant uses. The schema normalises the
    # modern keys to the internal ones (trigger becomes platform) and the async
    # validator then checks the block against the integration that implements
    # it. Skipping the first makes the second fail with KeyError: 'platform'.
    steps = {
        "triggers": (cv.TRIGGER_SCHEMA, trigger.async_validate_trigger_config),
        "conditions": (cv.CONDITIONS_SCHEMA, condition.async_validate_conditions_config),
        "actions": (cv.SCRIPT_SCHEMA, script.async_validate_actions_config),
    }
    schema, validator = steps[args["kind"]]
    try:
        normalised = await validator(hass, schema(args["config"]))
    except Exception as err:  # noqa: BLE001 - the error text is the answer
        return {"valid": False, "error": f"{type(err).__name__}: {err}"}
    return {"valid": True, "normalised": normalised}


@tool(
    "ha_config_entry",
    "Act on an installed integration: reload it (the usual fix for a device that has "
    "gone unavailable), unload it, set it up again, or remove it. Use "
    "ha_get_config_entries to find the entry_id.",
    Access.WRITE,
    {
        "action": Arg("string", "What to do", required=True,
                      enum=["reload", "unload", "setup", "remove"]),
        "entry_id": Arg("string", "Config entry id", required=True),
    },
    op_field="action",
    op_access={
        "reload": Access.WRITE,
        "unload": Access.WRITE,
        "setup": Access.WRITE,
        "remove": Access.DESTRUCTIVE,
    },
)
async def config_entry(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    entry = hass.config_entries.async_get_entry(args["entry_id"])
    if entry is None:
        raise ValueError(f"No config entry {args['entry_id']}")
    action = args["action"]
    if action == "remove":
        await hass.config_entries.async_remove(entry.entry_id)
        return {"removed": entry.title, "domain": entry.domain}
    ok = await getattr(hass.config_entries, f"async_{action}")(entry.entry_id)
    refreshed = hass.config_entries.async_get_entry(entry.entry_id)
    return {
        "action": action,
        "ok": bool(ok),
        "title": entry.title,
        "domain": entry.domain,
        "state": str(refreshed.state) if refreshed else "removed",
    }


@tool(
    "ha_repairs",
    "List the issues Home Assistant's Repairs panel is showing: failing integrations, "
    "deprecations, misconfigurations. Each carries a severity and whether Home "
    "Assistant offers a fix. 'ignore' hides one.",
    Access.SENSITIVE,
    {
        "action": Arg("string", "What to do", default="list", enum=["list", "ignore"]),
        "domain": Arg("string", "Issue domain, for ignore"),
        "issue_id": Arg("string", "Issue id, for ignore"),
    },
    op_field="action",
    op_access={"list": Access.SENSITIVE, "ignore": Access.WRITE},
)
async def repairs(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    from homeassistant.helpers import issue_registry as ir

    if args.get("action", "list") == "ignore":
        if not args.get("domain") or not args.get("issue_id"):
            raise ValueError("domain and issue_id are required to ignore an issue")
        ir.async_ignore_issue(hass, args["domain"], args["issue_id"], True)
        return {"ignored": f"{args['domain']}/{args['issue_id']}"}

    registry = ir.async_get(hass)
    return [
        {
            "domain": issue.domain,
            "issue_id": issue.issue_id,
            "severity": str(issue.severity),
            "is_fixable": issue.is_fixable,
            "active": issue.active,
            "dismissed": issue.dismissed_version is not None,
            "breaks_in": issue.breaks_in_ha_version,
            "translation_key": issue.translation_key,
            "placeholders": issue.translation_placeholders,
            "learn_more": issue.learn_more_url,
        }
        for issue in registry.issues.values()
    ]


@tool(
    "ha_assist",
    "Send a sentence to Assist exactly as a voice assistant would and return what it "
    "understood and did. Use it to prove a naming or area fix worked: after moving the "
    "courtyard light, ask to 'turn off the courtyard lights' and see whether it "
    "resolves. Sentences that control devices will control them.",
    Access.WRITE,
    {
        "text": Arg("string", "What to say, e.g. 'is the back door open'", required=True),
        "language": Arg("string", "Language code; defaults to the instance language"),
        "agent_id": Arg("string", "Conversation agent; defaults to Home Assistant's built-in"),
    },
)
async def assist(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    from ..ws_bridge import ws_call

    payload: dict[str, Any] = {"text": args["text"]}
    for key in ("language", "agent_id"):
        if args.get(key):
            payload[key] = args[key]
    result = await ws_call(hass, policy, "conversation/process", **payload)
    response = (result or {}).get("response") or {}
    speech = ((response.get("speech") or {}).get("plain") or {}).get("speech")
    return {
        "response_type": response.get("response_type"),
        "speech": speech,
        "targets": (response.get("data") or {}).get("targets"),
        "success": (response.get("data") or {}).get("success"),
        "failed": (response.get("data") or {}).get("failed"),
        "language": response.get("language"),
    }


@tool(
    "ha_backup",
    "List existing backups or create a new one. Take a backup before a batch of "
    "changes to an unfamiliar instance; it is step one of the onboarding procedure.",
    Access.WRITE,
    {
        "action": Arg("string", "What to do", required=True, enum=["list", "create"]),
        "name": Arg("string", "Name for a new backup"),
        "include_database": Arg("boolean", "Include the recorder database", default=True),
    },
    op_field="action",
    op_access={"list": Access.SENSITIVE, "create": Access.WRITE},
)
async def backup(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    from ..ws_bridge import ws_call

    if "backup" not in hass.config.components:
        raise ValueError("The 'backup' integration is not loaded.")

    if args["action"] == "list":
        info = await ws_call(hass, policy, "backup/info")
        backups = (info or {}).get("backups") or []
        return {
            "count": len(backups),
            "backups": [
                {
                    "backup_id": b.get("backup_id"),
                    "name": b.get("name"),
                    "date": b.get("date"),
                    "size_mb": round((sum(a.get("size", 0) for a in (b.get("agents") or {}).values())) / 1_048_576, 1)
                    if isinstance(b.get("agents"), dict) else None,
                    "homeassistant_version": b.get("homeassistant_version"),
                    "database_included": b.get("database_included"),
                }
                for b in backups
            ],
            "last_completed_automatic": (info or {}).get("last_completed_automatic_backup"),
        }

    agents = await ws_call(hass, policy, "backup/agents/info")
    agent_ids = [a.get("agent_id") for a in (agents or {}).get("agents", []) if a.get("agent_id")]
    local = [a for a in agent_ids if a.endswith(".local")] or agent_ids[:1]
    if not local:
        raise ValueError("No backup agent is configured.")
    started = await ws_call(
        hass, policy, "backup/generate",
        agent_ids=local,
        include_database=args.get("include_database", True),
        include_homeassistant=True,
        name=args.get("name") or None,
    )
    return {"started": True, "backup_job_id": (started or {}).get("backup_job_id"), "agents": local,
            "note": "Runs in the background; use action 'list' to see it once finished."}


@tool(
    "ha_energy",
    "Read or change the Energy dashboard's configuration: which entities supply grid "
    "import and export, solar production, battery flow and gas or water. 'validate' "
    "reports why a configured entity is unsuitable, which is usually a missing "
    "device_class or state_class.",
    Access.WRITE,
    {
        "action": Arg("string", "What to do", required=True, enum=["get", "save", "validate"]),
        "preferences": Arg("object", "Full energy preferences object for 'save', as returned by 'get'"),
    },
    op_field="action",
    op_access={"get": Access.SENSITIVE, "validate": Access.SENSITIVE, "save": Access.WRITE},
)
async def energy(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    from ..ws_bridge import ws_call

    if "energy" not in hass.config.components:
        raise ValueError("The 'energy' integration is not loaded.")
    action = args["action"]
    if action == "get":
        return await ws_call(hass, policy, "energy/get_prefs")
    if action == "validate":
        return await ws_call(hass, policy, "energy/validate")
    if not args.get("preferences"):
        raise ValueError("preferences is required to save")
    return await ws_call(hass, policy, "energy/save_prefs", **args["preferences"])
