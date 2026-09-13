"""Dashboards.

Most users never build one. Home Assistant generates an Overview from the area
registry, so for them the dashboard *is* the area data — which is why the area
rules carry a dashboard tag. These rules cover the dashboards that do exist.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from ..context import ACTIONABLE, AuditContext
from ..model import Finding, Severity, rule

AREAS = "ha://knowledge/areas"
ONBOARDING = "ha://knowledge/onboarding"
ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def _card_entities(node: Any) -> Iterator[str]:
    """Every entity ID referenced anywhere in a dashboard config."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("entity", "entity_id") and isinstance(value, str):
                if ENTITY_ID.match(value):
                    yield value
            elif key == "entities" and isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and ENTITY_ID.match(item):
                        yield item
            yield from _card_entities(value)
    elif isinstance(node, list):
        for item in node:
            yield from _card_entities(item)


@rule(
    "dashboard/broken-reference",
    Severity.WARNING,
    "Dashboard card references an entity that does not exist",
    ONBOARDING,
    why="The card renders as 'Entity not available', which is the most visible kind of "
        "rot in an instance.",
    tags=("dashboard", "health"),
)
def broken_reference(ctx: AuditContext) -> Iterator[Finding]:
    known = set(ctx.hass.states.async_entity_ids())
    known.update(e.entity_id for e in ctx.all_entities)

    for url_path, config in ctx.dashboards.items():
        if not isinstance(config, dict):
            continue
        missing = sorted(set(_card_entities(config)) - known)
        if missing:
            yield Finding(
                subject=url_path,
                detail=f"{len(missing)} missing: {', '.join(missing[:4])}"
                       + (f" and {len(missing) - 4} more" if len(missing) > 4 else ""),
                fix="Remove the cards or repoint them at the entities that replaced these",
            )


@rule(
    "dashboard/auto-generated-only",
    Severity.INFO,
    "No dashboard has been customised",
    AREAS,
    why="Everything the user sees comes from the auto-generated Overview, which groups "
        "purely by area. Fixing area assignment is what improves their dashboard; "
        "nothing else will.",
    tags=("dashboard", "areas"),
)
def auto_generated_only(ctx: AuditContext) -> Iterator[Finding]:
    if ctx.dashboards:
        return
    unassigned = sum(
        1 for e in ctx.live_entities
        if ctx.is_primary(e) and e.domain in ACTIONABLE and not ctx.area_id_of(e)
    )
    yield Finding(
        detail=f"using the auto-generated Overview, with {unassigned} controllable "
               f"entities in no area",
        fix="Assign every controllable entity to a room. The default dashboard groups "
            "by area, so that alone determines what the user sees.",
    )
