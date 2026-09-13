"""Helpers for declaring a tool's arguments once.

A tool needs two things from its arguments: a JSON Schema to advertise, and a
validator to apply. Writing both by hand invites them to drift, so they are
derived from one declaration.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant

from ..permissions import Access, Policy
from . import Tool, register


@dataclass(slots=True)
class Arg:
    """One tool argument."""

    type: str
    description: str
    required: bool = False
    default: Any = None
    enum: list[str] | None = None
    items: dict[str, Any] | None = None
    minimum: int | None = None
    maximum: int | None = None

    def json_schema(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": self.type, "description": self.description}
        if self.enum is not None:
            schema["enum"] = self.enum
        if self.items is not None:
            schema["items"] = self.items
        if self.minimum is not None:
            schema["minimum"] = self.minimum
        if self.maximum is not None:
            schema["maximum"] = self.maximum
        if self.default is not None:
            schema["default"] = self.default
        return schema

    def validator(self) -> Any:
        base = {
            "string": str,
            "boolean": bool,
            "integer": vol.Coerce(int),
            "number": vol.Coerce(float),
            "array": list,
            "object": dict,
        }[self.type]
        if self.enum is not None:
            return vol.In(self.enum)
        if self.minimum is not None or self.maximum is not None:
            return vol.All(base, vol.Range(min=self.minimum, max=self.maximum))
        return base


def tool(
    name: str,
    description: str,
    access: Access,
    args: dict[str, Arg] | None = None,
    op_field: str | None = None,
    op_access: dict[str, Access] | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Tool]:
    """Declare a tool from its arguments and handler.

    ``op_field`` and ``op_access`` let one tool bundle operations of differing
    risk, so reading a dashboard is not gated behind permission to delete one.
    """
    args = args or {}

    def decorate(handler: Callable[[HomeAssistant, Policy, dict[str, Any]], Awaitable[Any]]) -> Tool:
        schema_dict: dict[Any, Any] = {}
        for arg_name, arg in args.items():
            if arg.required:
                key: Any = vol.Required(arg_name)
            elif arg.default is None:
                # No default means the key is simply absent, not present as None
                # for the validator to choke on.
                key = vol.Optional(arg_name)
            elif isinstance(arg.default, (dict, list)):
                # A mutable default must be produced per call, not shared.
                key = vol.Optional(arg_name, default=lambda d=arg.default: type(d)(d))
            else:
                key = vol.Optional(arg_name, default=arg.default)
            schema_dict[key] = arg.validator()

        input_schema = {
            "type": "object",
            "properties": {n: a.json_schema() for n, a in args.items()},
            "required": [n for n, a in args.items() if a.required],
        }

        return register(
            Tool(
                name=name,
                description=description,
                access=access,
                input_schema=input_schema,
                schema=vol.Schema(schema_dict),
                handler=handler,
                op_field=op_field,
                op_access=op_access or {},
            )
        )

    return decorate
