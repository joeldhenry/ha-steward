"""HTTP transport for the MCP server.

Authentication is Home Assistant's own. Setting ``requires_auth`` makes the
auth middleware validate the bearer token and reject anything else with a
401 carrying ``WWW-Authenticate: Bearer resource_metadata=...``. That is the
RFC 9728 challenge an MCP client follows to discover the authorization server,
and Home Assistant has been an OAuth 2.1 authorization server with Client ID
Metadata Document support since 2025.

So a client only needs the endpoint URL: it discovers the rest, opens a browser,
and the user logs in to Home Assistant as normal. No long-lived token to paste,
and no separate authorization server to run.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.components.http.const import KEY_HASS_REFRESH_TOKEN_ID, KEY_HASS_USER
from homeassistant.core import HomeAssistant

from .const import (
    CONF_RATE_LIMIT,
    CONF_RATE_WINDOW,
    DEFAULT_RATE_LIMIT,
    DEFAULT_RATE_WINDOW,
    DOMAIN,
    INVALID_REQUEST,
    MCP_PATH,
    PARSE_ERROR,
)
from .protocol import MCPProtocol, json_rpc_error
from .rate_limit import RateLimiter

_LOGGER = logging.getLogger(__name__)

# A batch counts each message against the rate limit, and a single batch may
# not exceed this many. Without both, one request could carry a thousand calls.
MAX_BATCH = 50


def async_register_http(hass: HomeAssistant) -> None:
    """Register the MCP view."""
    hass.http.register_view(MCPView())


def _limiter(hass: HomeAssistant) -> RateLimiter:
    """One limiter per instance, rebuilt when the options change."""
    entries = hass.config_entries.async_entries(DOMAIN)
    options = entries[0].options if entries else {}
    max_calls = options.get(CONF_RATE_LIMIT, DEFAULT_RATE_LIMIT)
    window = options.get(CONF_RATE_WINDOW, DEFAULT_RATE_WINDOW)

    store = hass.data.setdefault(DOMAIN, {})
    cached = store.get("_limiter")
    if cached is None or store.get("_limiter_settings") != (max_calls, window):
        cached = RateLimiter(max_calls, window)
        store["_limiter"] = cached
        store["_limiter_settings"] = (max_calls, window)
    return cached


class MCPView(HomeAssistantView):
    """Streamable HTTP transport endpoint."""

    url = MCP_PATH
    name = "api:steward"
    requires_auth = True

    async def post(self, request: web.Request) -> web.StreamResponse:
        """Handle a JSON-RPC request or batch."""
        hass = request.app[KEY_HASS]
        user = request[KEY_HASS_USER]

        try:
            payload = await request.json()
        except ValueError:
            return self.json(json_rpc_error(None, PARSE_ERROR, "Invalid JSON"), 400)

        if isinstance(payload, list):
            if not payload:
                return self.json(json_rpc_error(None, INVALID_REQUEST, "Empty batch"), 400)
            if len(payload) > MAX_BATCH:
                return self.json(
                    json_rpc_error(None, INVALID_REQUEST, f"Batch exceeds {MAX_BATCH} messages"),
                    400,
                )
            messages = payload
        elif isinstance(payload, dict):
            messages = [payload]
        else:
            return self.json(
                json_rpc_error(None, PARSE_ERROR, "Expected an object or array"), 400
            )

        # Key on the refresh token rather than the access token, so a client
        # rotating short-lived tokens keeps one budget, and so the credential
        # itself is never used as a key.
        limiter = _limiter(hass)
        caller = f"{user.id}:{request.get(KEY_HASS_REFRESH_TOKEN_ID, '')}"
        retry_after: float | None = None
        for _ in messages:
            if (retry_after := limiter.check(caller)) is not None:
                break
        if retry_after is not None:
            _LOGGER.debug("Rate limit reached for %s", user.name)
            return self.json(
                {"error": "rate limit exceeded", "retry_after_seconds": retry_after},
                429,
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

        protocol = MCPProtocol(hass, user)
        responses: list[dict[str, Any]] = []
        for message in messages:
            if (response := await protocol.dispatch(message)) is not None:
                responses.append(response)

        if not responses:
            # Notifications only; nothing to say back.
            return web.Response(status=202)
        if isinstance(payload, dict):
            return self.json(responses[0])
        return self.json(responses)

    async def get(self, request: web.Request) -> web.StreamResponse:
        """Reject SSE upgrades.

        The spec allows a server to open a stream here for server-initiated
        messages, and requires a 405 when it does not. Nothing this server does
        is asynchronous.
        """
        return web.Response(status=405, text="This server does not use server-initiated streams.")
