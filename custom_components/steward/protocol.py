"""MCP JSON-RPC protocol handling."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant.auth.models import User
from homeassistant.core import HomeAssistant

from .const import (
    DEFAULT_PROTOCOL_VERSION,
    DOMAIN,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    SERVER_NAME,
    SERVER_TITLE,
    SERVER_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
)
from .knowledge import KNOWLEDGE, PROMPTS, read_knowledge
from .permissions import NotPermitted, Policy
from .tools import TOOLS

_LOGGER = logging.getLogger(__name__)


def json_rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    """Build a JSON-RPC error response."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def json_rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    """Build a JSON-RPC success response."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


class MCPProtocol:
    """Dispatches one client's JSON-RPC calls."""

    def __init__(self, hass: HomeAssistant, user: User) -> None:
        self.hass = hass
        self.user = user

    @property
    def _policy(self) -> Policy:
        entries = self.hass.config_entries.async_entries(DOMAIN)
        return Policy(entries[0] if entries else None, self.user)

    async def dispatch(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one message. Returns None for notifications."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return json_rpc_error(None, INVALID_REQUEST, "Expected a JSON-RPC 2.0 message")

        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        is_notification = "id" not in message

        if not isinstance(method, str):
            return None if is_notification else json_rpc_error(request_id, INVALID_REQUEST, "Missing method")

        handler = {
            "initialize": self._initialize,
            "ping": lambda _: {},
            "tools/list": self._list_tools,
            "tools/call": self._call_tool,
            "resources/list": self._list_resources,
            "resources/read": self._read_resource,
            "prompts/list": self._list_prompts,
            "prompts/get": self._get_prompt,
        }.get(method)

        if handler is None:
            # Notifications we do not implement (notifications/initialized) are
            # acknowledged without a reply.
            if is_notification:
                return None
            return json_rpc_error(request_id, METHOD_NOT_FOUND, f"Unknown method '{method}'")

        try:
            result = await handler(params)
        except NotPermitted as err:
            return json_rpc_result(request_id, _tool_error(str(err)))
        except vol.Invalid as err:
            return json_rpc_error(request_id, INVALID_PARAMS, str(err))
        except Exception:  # noqa: BLE001 - a tool must not take the endpoint down
            _LOGGER.exception("Error handling MCP method %s", method)
            return json_rpc_error(request_id, INTERNAL_ERROR, "Internal error; see the Home Assistant log")

        return None if is_notification else json_rpc_result(request_id, result)

    async def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        policy = self._policy

        return {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
                "prompts": {"listChanged": False},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "title": SERVER_TITLE,
                "version": SERVER_VERSION,
            },
            "instructions": (
                "This server manages a Home Assistant instance. Before changing how it is "
                "organised (naming, areas, device types), read the relevant "
                "ha://knowledge/* resource, and run ha_audit first when the instance is "
                "unfamiliar. "
                f"Connected as {policy.user.name}"
                f"{'' if policy.user.is_admin else ' (non-admin: registries, logs, configuration and write operations are unavailable)'}."
            ),
        }

    async def _list_tools(self, _params: dict[str, Any]) -> dict[str, Any]:
        policy = self._policy
        return {
            "tools": [
                {
                    "name": tool.name,
                    "description": _describe(tool, policy),
                    "inputSchema": tool.input_schema,
                    "annotations": {
                        "readOnlyHint": tool.min_access == "read" and not tool.op_access,
                        "destructiveHint": tool.access == "destructive"
                        or "destructive" in {str(a) for a in tool.op_access.values()},
                    },
                }
                for tool in TOOLS.values()
                if policy.allows(tool.min_access)
            ]
        }

    async def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        tool = TOOLS.get(name) if isinstance(name, str) else None
        if tool is None:
            return _tool_error(f"Unknown tool '{name}'. Call tools/list for the available tools.")

        try:
            arguments = tool.validate(params.get("arguments") or {})
        except vol.Invalid as err:
            return _tool_error(f"Invalid arguments for {tool.name}: {err}")

        # Checked after validation so the gate applies to the operation actually
        # requested, not to the tool as a whole.
        policy = self._policy
        policy.check(tool.access_for(arguments), tool.name)

        try:
            result = await tool.handler(self.hass, policy, arguments)
        except NotPermitted:
            raise
        except Exception as err:  # noqa: BLE001 - report to the model, not the log alone
            _LOGGER.exception("Tool %s failed", tool.name)
            return _tool_error(f"{type(err).__name__}: {err}")

        return {"content": [{"type": "text", "text": _as_text(result)}], "isError": False}

    async def _list_resources(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "resources": [
                {
                    "uri": f"ha://knowledge/{doc.slug}",
                    "name": doc.slug,
                    "title": doc.title,
                    "description": doc.description,
                    "mimeType": "text/markdown",
                }
                for doc in KNOWLEDGE
            ]
        }

    async def _read_resource(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri.startswith("ha://knowledge/"):
            raise vol.Invalid(f"Unknown resource '{uri}'. Call resources/list for the available URIs.")
        slug = uri.removeprefix("ha://knowledge/")
        try:
            text = await self.hass.async_add_executor_job(read_knowledge, slug)
        except ValueError as err:
            raise vol.Invalid(str(err)) from err
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}

    async def _list_prompts(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "prompts": [
                {"name": p.name, "title": p.title, "description": p.description}
                for p in PROMPTS
            ]
        }

    async def _get_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        prompt = next((p for p in PROMPTS if p.name == name), None)
        if prompt is None:
            raise vol.Invalid(f"Unknown prompt '{name}'")
        return {
            "description": prompt.description,
            "messages": [
                {"role": "user", "content": {"type": "text", "text": prompt.text}}
            ],
        }


def _describe(tool: Any, policy: Policy) -> str:
    """Tell the model up front which operations it may not use."""
    restricted = tool.restricted_ops(policy)
    if not restricted:
        return tool.description
    return (
        f"{tool.description} "
        f"Not permitted for this connection: {', '.join(restricted)}."
    )


def _tool_error(message: str) -> dict[str, Any]:
    """A tool failure is a result, not a protocol error, so the model can react."""
    return {"content": [{"type": "text", "text": f"Error: {message}"}], "isError": True}


def _as_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2, default=str)
