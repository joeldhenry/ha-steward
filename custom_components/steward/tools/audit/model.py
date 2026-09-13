"""Rule definitions and the registry that collects them."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import AuditContext


class Severity(StrEnum):
    ERROR = "error"
    """Something is broken: data is not recorded, or a reference does not resolve."""

    WARNING = "warning"
    """Works today but will misbehave, confuse a voice assistant, or break on a change."""

    INFO = "info"
    """Tidiness and convention."""


SEVERITY_ORDER = (Severity.ERROR, Severity.WARNING, Severity.INFO)


@dataclass(slots=True)
class Finding:
    """One instance of a rule being violated."""

    detail: str
    fix: str
    entity_id: str | None = None
    device: str | None = None
    area: str | None = None
    subject: str | None = None

    def as_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in (
                ("entity_id", self.entity_id),
                ("device", self.device),
                ("area", self.area),
                ("subject", self.subject),
                ("detail", self.detail),
                ("fix", self.fix),
            )
            if value is not None
        }


Check = Callable[["AuditContext"], Iterator[Finding]]


@dataclass(slots=True)
class Rule:
    id: str
    severity: Severity
    title: str
    knowledge: str
    check: Check
    why: str = ""
    """What goes wrong if this is left alone. Shown with the findings."""
    tags: frozenset[str] = field(default_factory=frozenset)


REGISTRY: dict[str, Rule] = {}


def rule(
    rule_id: str,
    severity: Severity,
    title: str,
    knowledge: str,
    why: str = "",
    tags: tuple[str, ...] = (),
) -> Callable[[Check], Check]:
    """Register an audit rule.

    A rule is a generator so it can stop early and never builds a list it does
    not need; the tool decides how many findings to render.
    """

    def decorate(check: Check) -> Check:
        if rule_id in REGISTRY:
            raise ValueError(f"Duplicate audit rule: {rule_id}")
        REGISTRY[rule_id] = Rule(
            id=rule_id,
            severity=severity,
            title=title,
            knowledge=knowledge,
            check=check,
            why=why,
            tags=frozenset(tags),
        )
        return check

    return decorate
