"""Tool registry.

Tools run in-process against the ``hass`` object, so there is no REST or
WebSocket round trip and no access token to manage.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant

from ..permissions import ACCESS_ORDER, Access, Policy

Handler = Callable[[HomeAssistant, Policy, dict[str, Any]], Awaitable[Any]]



@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    access: Access
    """Access required when no per-operation entry matches."""
    input_schema: dict[str, Any]
    schema: vol.Schema
    handler: Handler
    op_field: str | None = None
    """Argument naming the operation, for tools that bundle several."""
    op_access: Mapping[str, Access] = field(default_factory=dict)
    """Access required per operation, e.g. {"get": READ, "delete": DESTRUCTIVE}."""

    def validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.schema(arguments)

    def access_for(self, arguments: Mapping[str, Any]) -> Access:
        """Access this specific call needs."""
        if self.op_field and self.op_access:
            op = arguments.get(self.op_field)
            if isinstance(op, str) and op in self.op_access:
                return self.op_access[op]
        return self.access

    @property
    def min_access(self) -> Access:
        """The least privilege any operation on this tool requires.

        A tool is listed when the caller can perform at least one of its
        operations; hiding a readable tool because its delete is gated would
        remove the read too.
        """
        levels = [self.access, *self.op_access.values()]
        return min(levels, key=ACCESS_ORDER.index)

    def restricted_ops(self, policy: Policy) -> list[str]:
        """Operations this caller may not perform."""
        if not self.op_access:
            return []
        return sorted(op for op, access in self.op_access.items() if not policy.allows(access))


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    """Add a tool, refusing a duplicate name rather than shadowing one."""
    if tool.name in _REGISTRY:
        raise ValueError(f"Duplicate tool name: {tool.name}")
    _REGISTRY[tool.name] = tool
    return tool


def _load() -> dict[str, Tool]:
    # Imported for their registration side effects.
    from . import (  # noqa: F401
        audit,
        automations,
        config,
        dashboards,
        diagnostics,
        entities,
        helpers,
        registry,
        system,
    )

    return _REGISTRY


TOOLS: dict[str, Tool] = _load()
