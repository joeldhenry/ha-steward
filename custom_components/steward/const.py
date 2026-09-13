"""Constants for the Steward integration."""

from typing import Final

DOMAIN: Final = "steward"

# Namespaced under the integration so sibling endpoints can be added later
# without registering another view. The built-in mcp_server integration owns
# /api/mcp, and Home Assistant will not let two integrations share a path.
MCP_PATH: Final = "/api/steward/mcp"

SERVER_NAME: Final = "steward"
SERVER_TITLE: Final = "Steward - Home Assistant MCP Plugin"
SERVER_VERSION: Final = "0.2.1"

# Echoed back when the client asks for something we do not recognise.
DEFAULT_PROTOCOL_VERSION: Final = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS: Final = frozenset(
    {"2024-11-05", "2025-03-26", "2025-06-18"}
)

CONF_ALLOW_WRITE: Final = "allow_write"
CONF_ALLOW_DESTRUCTIVE: Final = "allow_destructive"
CONF_REQUIRE_ADMIN: Final = "require_admin"
CONF_RATE_LIMIT: Final = "rate_limit"
CONF_RATE_WINDOW: Final = "rate_window"

DEFAULT_ALLOW_WRITE: Final = True
DEFAULT_ALLOW_DESTRUCTIVE: Final = False
DEFAULT_REQUIRE_ADMIN: Final = True
# Generous for a person, restrictive for a model stuck in a retry loop.
DEFAULT_RATE_LIMIT: Final = 120
DEFAULT_RATE_WINDOW: Final = 60

# JSON-RPC 2.0 error codes.
PARSE_ERROR: Final = -32700
INVALID_REQUEST: Final = -32600
METHOD_NOT_FOUND: Final = -32601
INVALID_PARAMS: Final = -32602
INTERNAL_ERROR: Final = -32603
