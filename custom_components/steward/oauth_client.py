"""A Client ID Metadata Document that Steward serves for OAuth clients.

Home Assistant verifies an OAuth client's redirect_uri against the document at
its client_id URL using exact string comparison. Two different clients fail
that check for two different reasons, and this one document fixes both.

Claude Code registers a loopback redirect with no port and then listens on a
random one, so the two never match. Serving our own document sidesteps that
without a separate authorization server: it lists a small set of fixed
loopback ports, the client pins its callback to one of them, and Home
Assistant's own login flow does the rest.

The hosted Claude surfaces (claude.ai web, Desktop, mobile, Cowork) use a
fixed, non-loopback callback instead: https://claude.ai/api/mcp/auth_callback.
Home Assistant's own OAuth metadata omits token_endpoint_auth_methods_supported,
so Claude's connector setup will not select CIMD on its own and falls back to
dynamic client registration, which Home Assistant does not implement. Choosing
"Use your own OAuth client" in the connector dialog and entering this
document's URL as the client ID routes around that, the same way pinning a
callback port does for Claude Code.

The document contains no secrets and is fetched unauthenticated, which is why
the view does not require auth.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import SERVER_TITLE

CLIENT_METADATA_PATH = "/api/steward/oauth-client.json"

# Ports a loopback client may pin its callback to. Both host spellings are
# listed because at least one Claude Code release used 127.0.0.1.
CALLBACK_PORTS: tuple[int, ...] = (8080, 8090, 8888)
CALLBACK_HOSTS: tuple[str, ...] = ("localhost", "127.0.0.1")

# The fixed callback for claude.ai web, Desktop, mobile and Cowork, published
# at https://claude.com/docs/connectors/building/authentication#callback-urls.
CLAUDE_HOSTED_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


def redirect_uris() -> list[str]:
    return [
        *(
            f"http://{host}:{port}/callback"
            for port in CALLBACK_PORTS
            for host in CALLBACK_HOSTS
        ),
        CLAUDE_HOSTED_REDIRECT_URI,
    ]


def client_id_url(hass: HomeAssistant) -> str:
    """The URL this document is served at, as Home Assistant will fetch it.

    Home Assistant checks that the document's client_id field equals the URL
    it fetched, and it fetches over the public internet, so this must be the
    external HTTPS address rather than whatever host the request arrived on.
    """
    base = get_url(hass, prefer_external=True, allow_internal=False, require_ssl=True)
    return f"{base.rstrip('/')}{CLIENT_METADATA_PATH}"


def client_metadata_document(hass: HomeAssistant) -> dict[str, Any]:
    return {
        "client_id": client_id_url(hass),
        "client_name": SERVER_TITLE,
        "redirect_uris": redirect_uris(),
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


class ClientMetadataView(HomeAssistantView):
    """Serve the metadata document."""

    url = CLIENT_METADATA_PATH
    name = "api:steward:oauth-client"
    requires_auth = False

    async def get(self, request: web.Request) -> web.StreamResponse:
        hass = request.app[KEY_HASS]
        try:
            document = client_metadata_document(hass)
        except NoURLAvailableError:
            return self.json_message(
                "Home Assistant has no external HTTPS URL configured. Set one under "
                "Settings, System, Network so this document can name itself.",
                status_code=503,
            )
        return self.json(document)
