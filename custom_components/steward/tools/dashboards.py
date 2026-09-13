"""Lovelace dashboards.

Storage-mode dashboards can be read and rewritten. YAML-mode dashboards and
the auto-generated default are readable only; the default has no stored config
at all until someone takes control of it, which is what saving does."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..permissions import Access, Policy
from ..ws_bridge import CommandFailed, ws_call
from ._schema import Arg, tool

DEFAULT = "lovelace"


def _url_path(value: str | None) -> str | None:
    return None if not value or value == DEFAULT else value


@tool(
    "ha_dashboard",
    "Work with Lovelace dashboards. 'list' shows every dashboard; 'get' returns one "
    "dashboard's full view and card config; 'save' replaces that config; 'create', "
    "'update' and 'delete' manage the dashboards themselves; 'resources' lists custom "
    "card resources. Use 'lovelace' as the url_path for the default dashboard. A "
    "dashboard still on the auto-generated strategy has no stored config, and saving "
    "one is what takes it over.",
    Access.WRITE,
    {
        "action": Arg("string", "What to do", required=True,
                      enum=["list", "get", "save", "create", "update", "delete", "resources"]),
        "url_path": Arg("string", "Dashboard url_path, or 'lovelace' for the default"),
        "config": Arg("object", "Full dashboard config for 'save', including its views"),
        "dashboard_id": Arg("string", "Dashboard id from 'list', for update and delete"),
        "title": Arg("string", "Title, for create or update"),
        "icon": Arg("string", "MDI icon, for create or update"),
        "show_in_sidebar": Arg("boolean", "Show in the sidebar, for create or update"),
        "require_admin": Arg("boolean", "Admins only, for create or update"),
    },
    op_field="action",
    op_access={
        "list": Access.READ,
        "get": Access.READ,
        "resources": Access.READ,
        "save": Access.WRITE,
        "create": Access.WRITE,
        "update": Access.WRITE,
        "delete": Access.DESTRUCTIVE,
    },
)
async def dashboard(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    action = args["action"]

    if action == "list":
        dashboards = await ws_call(hass, policy, "lovelace/dashboards/list")
        return [{"id": DEFAULT, "url_path": DEFAULT, "title": "Overview (default)", "mode": "auto"}, *dashboards]

    if action == "resources":
        return await ws_call(hass, policy, "lovelace/resources")

    if action == "get":
        try:
            return await ws_call(hass, policy, "lovelace/config", url_path=_url_path(args.get("url_path")))
        except CommandFailed as err:
            if err.code == "config_not_found":
                return {
                    "url_path": args.get("url_path") or DEFAULT,
                    "config": None,
                    "note": "Auto-generated; no stored config. Saving a config takes it over.",
                }
            raise

    if action == "save":
        if not args.get("config"):
            raise ValueError("config is required to save a dashboard")
        await ws_call(hass, policy, "lovelace/config/save",
                      url_path=_url_path(args.get("url_path")), config=args["config"])
        return {"saved": args.get("url_path") or DEFAULT}

    if action == "create":
        if not args.get("url_path") or not args.get("title"):
            raise ValueError("url_path and title are required to create a dashboard")
        fields = {k: args[k] for k in ("title", "icon", "show_in_sidebar", "require_admin") if args.get(k) is not None}
        return await ws_call(hass, policy, "lovelace/dashboards/create",
                             url_path=args["url_path"], mode="storage", **fields)

    if not args.get("dashboard_id"):
        raise ValueError(f"dashboard_id is required to {action} a dashboard")
    if action == "delete":
        await ws_call(hass, policy, "lovelace/dashboards/delete", dashboard_id=args["dashboard_id"])
        return {"deleted": args["dashboard_id"]}

    fields = {k: args[k] for k in ("title", "icon", "show_in_sidebar", "require_admin") if args.get(k) is not None}
    if not fields:
        raise ValueError("Nothing to update")
    return await ws_call(hass, policy, "lovelace/dashboards/update", dashboard_id=args["dashboard_id"], **fields)
