"""Drive Home Assistant's WebSocket commands in-process.

Helpers, dashboards, energy preferences, backups, repairs and Assist all expose
their create, update and delete operations only as WebSocket commands. Their
storage collections are locals inside each integration's setup, so there is
no object to call. The command registry is public, though: every command is
stored in hass.data under the websocket_api domain as (handler, schema), and a
handler takes (hass, connection, msg).

This module invokes those handlers with a real ActiveConnection whose
send_message captures the reply, so the code path, validation and admin checks
are the same ones the frontend goes through, on any release.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any

import voluptuous as vol
from homeassistant.components.websocket_api import const as ws_const
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import Unauthorized

from .permissions import NotPermitted, Policy

_LOGGER = logging.getLogger(__name__)

COMMAND_TIMEOUT = 30


class CommandFailed(Exception):
    """The command ran and Home Assistant answered with an error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{message} ({code})")
        self.code = code


def _decode(message: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    if isinstance(message, bytes):
        message = message.decode()
    return json.loads(message)


async def ws_call(
    hass: HomeAssistant, policy: Policy, command: str, **payload: Any
) -> Any:
    """Run one WebSocket command and return its result payload."""
    registry: dict[str, tuple[Any, vol.Schema]] | None = hass.data.get(ws_const.DOMAIN)
    if not registry or command not in registry:
        raise ValueError(
            f"Home Assistant has no WebSocket command '{command}'. The integration "
            f"that provides it is not loaded."
        )
    handler, schema = registry[command]

    message = {"id": 1, "type": command, **payload}
    try:
        message = schema(message)
    except vol.Invalid as err:
        raise ValueError(f"Invalid arguments for {command}: {err}") from err

    loop = asyncio.get_running_loop()
    reply: asyncio.Future[dict[str, Any]] = loop.create_future()

    def capture(raw: bytes | str | dict[str, Any]) -> None:
        if not reply.done():
            reply.set_result(_decode(raw))

    refresh_token = await policy.async_refresh_token(hass)
    connection = ActiveConnection(_LOGGER, hass, capture, policy.user, refresh_token)

    try:
        handler(hass, connection, message)
    except Unauthorized as err:
        raise NotPermitted(
            f"Home Assistant requires an administrator for '{command}'."
        ) from err
    except vol.Invalid as err:
        raise ValueError(f"Invalid arguments for {command}: {err}") from err

    try:
        result = await asyncio.wait_for(reply, COMMAND_TIMEOUT)
    except TimeoutError as err:
        raise ValueError(f"'{command}' did not answer within {COMMAND_TIMEOUT}s.") from err

    if not result.get("success", False):
        error = result.get("error") or {}
        code = str(error.get("code", "unknown"))
        if code == ws_const.ERR_UNAUTHORIZED:
            raise NotPermitted(f"Home Assistant requires an administrator for '{command}'.")
        raise CommandFailed(code, str(error.get("message", "command failed")))
    return result.get("result")


def stand_in_refresh_token() -> SimpleNamespace:
    """A placeholder when the caller's refresh token cannot be resolved.

    ActiveConnection only reads the token's id, and nothing here issues tokens,
    so a stand-in is safe in tests and for calls made outside an HTTP request.
    """
    return SimpleNamespace(id="steward")
