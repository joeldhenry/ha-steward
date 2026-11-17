"""Permission gating for tools.

Two layers, checked in order:

1. Server policy, set per config entry. An install used for auditing can be
   made read-only regardless of who connects.
2. The connecting user's own Home Assistant account. A non-admin cannot be
   granted more than their account allows, and every service call carries
   that user's context so Home Assistant's own policy engine applies as well.
"""

from __future__ import annotations

from enum import StrEnum

from homeassistant.auth.models import User
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from typing import Any

from .const import (
    CONF_ALLOW_DESTRUCTIVE,
    CONF_ALLOW_WRITE,
    CONF_REQUIRE_ADMIN,
    DEFAULT_ALLOW_DESTRUCTIVE,
    DEFAULT_ALLOW_WRITE,
    DEFAULT_REQUIRE_ADMIN,
)


class Access(StrEnum):
    """What a tool does, from the caller's point of view."""

    READ = "read"
    """Returns state any authenticated user may see."""

    SENSITIVE = "sensitive"
    """Reads Home Assistant itself restricts to administrators: logs, traces,
    the registries, full automation logic, and template rendering."""

    WRITE = "write"
    """Changes state or configuration, reversibly."""

    DESTRUCTIVE = "destructive"
    """Deletes configuration or restarts the instance."""


# Least privilege first. Used to pick the lowest level a bundled tool offers.
ACCESS_ORDER = (Access.READ, Access.SENSITIVE, Access.WRITE, Access.DESTRUCTIVE)


class NotPermitted(Exception):
    """Raised when a tool is not permitted. Surfaced to the caller as text."""


def active_entry(hass: HomeAssistant, domain: str) -> ConfigEntry | None:
    """The Steward entry, only while it is set up and enabled.

    Home Assistant cannot unregister an HTTP view, so the endpoint outlives a
    disabled or deleted entry until the next restart. Everything that serves a
    request asks here first, so turning Steward off takes effect at once.
    """
    for entry in hass.config_entries.async_entries(domain):
        if entry.state is ConfigEntryState.LOADED and not entry.disabled_by:
            return entry
    return None


class Policy:
    """Effective permissions for one request."""

    def __init__(
        self, entry: ConfigEntry | None, user: User, refresh_token_id: str | None = None
    ) -> None:
        options = entry.options if entry else {}
        # Without an entry there are no options to honour, and the defaults
        # allow writes. Deny everything instead.
        self._active = entry is not None
        self._refresh_token_id = refresh_token_id
        self._allow_write = options.get(CONF_ALLOW_WRITE, DEFAULT_ALLOW_WRITE)
        self._allow_destructive = options.get(
            CONF_ALLOW_DESTRUCTIVE, DEFAULT_ALLOW_DESTRUCTIVE
        )
        self._require_admin = options.get(CONF_REQUIRE_ADMIN, DEFAULT_REQUIRE_ADMIN)
        self._user = user

    @property
    def user(self) -> User:
        return self._user

    async def async_refresh_token(self, hass: HomeAssistant) -> Any:
        """The caller's refresh token, for commands run through the WebSocket bridge."""
        from .ws_bridge import stand_in_refresh_token

        if self._refresh_token_id:
            token = hass.auth.async_get_refresh_token(self._refresh_token_id)
            if token is not None:
                return token
        tokens = getattr(self._user, "refresh_tokens", None) or {}
        return next(iter(tokens.values()), None) or stand_in_refresh_token()

    @property
    def context(self) -> Context:
        """Context for service calls, so they run as the connecting user."""
        return Context(user_id=self._user.id)

    def can_read_entity(self, entity_id: str) -> bool:
        """Whether the user's own Home Assistant policy lets them see this entity."""
        return self._user.permissions.check_entity(entity_id, POLICY_READ)

    def allows(self, access: Access, *, user_scoped: bool = False) -> bool:
        """Whether this request may perform an operation of this kind.

        ``user_scoped`` marks an operation that runs as a service call under
        the caller's own context, where Home Assistant applies that user's
        entity permissions itself. Those are the only changes a non-admin can
        be given. Everything else acts on the registries, the config files or
        the integrations directly, with nothing behind it to check the user, so
        it needs an administrator whatever the options say.
        """
        if not self._active:
            return False
        if access is Access.READ:
            return True
        if access is Access.SENSITIVE:
            return self._user.is_admin
        if not self._user.is_admin and (self._require_admin or not user_scoped):
            return False
        if access is Access.WRITE:
            return self._allow_write
        return self._allow_write and self._allow_destructive

    def check(self, access: Access, tool_name: str, *, user_scoped: bool = False) -> None:
        """Raise if the operation is not permitted, explaining what to change."""
        if self.allows(access, user_scoped=user_scoped):
            return

        if not self._active:
            raise NotPermitted(
                "Steward is disabled or has been removed from this Home Assistant."
            )
        if access is Access.SENSITIVE:
            raise NotPermitted(
                f"'{tool_name}' reads information Home Assistant restricts to "
                f"administrators, and this account is not one."
            )
        if not self._user.is_admin and (self._require_admin or not user_scoped):
            raise NotPermitted(
                f"'{tool_name}' performs a {access} operation and this account is not "
                f"a Home Assistant administrator."
            )
        if access is Access.DESTRUCTIVE and not self._allow_destructive:
            raise NotPermitted(
                f"'{tool_name}' deletes configuration or restarts Home Assistant. "
                f"Enable 'Allow destructive operations' in the Steward integration "
                f"options to permit it."
            )
        raise NotPermitted(
            f"'{tool_name}' modifies this instance, which is running in read-only "
            f"mode. Enable 'Allow write operations' in the Steward integration options."
        )
