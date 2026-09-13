"""The ha_audit tool."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ...permissions import Access, Policy
from .._schema import Arg, tool
from .context import AuditContext
from .model import REGISTRY, SEVERITY_ORDER, Severity
from . import rules  # noqa: F401  - registers every rule

ALL_TAGS = sorted({tag for rule in REGISTRY.values() for tag in rule.tags})


@tool(
    "ha_audit",
    "Check this instance against current Home Assistant conventions and report what is "
    "wrong with it: area structure, entity naming and area assignment, device types, "
    "sensor classes, dead and orphaned entities, broken automation and dashboard "
    "references, and readiness for voice, CarPlay and the Watch. Each finding names the "
    "knowledge resource explaining the fix. Run this first on an unfamiliar instance. "
    "Filter with tags to focus, for example tags=['dashboard'] or tags=['voice'].",
    Access.SENSITIVE,
    {
        "rules": Arg("array", "Only run these rule ids", items={"type": "string"}),
        "tags": Arg(
            "array",
            f"Only run rules carrying one of these tags. Available: {', '.join(ALL_TAGS)}",
            items={"type": "string"},
        ),
        "min_severity": Arg(
            "string", "Drop findings below this severity",
            default="info", enum=["error", "warning", "info"],
        ),
        "examples": Arg(
            "integer",
            "Examples per rule. Counts are always exact, so raise this only when you "
            "intend to act on individual findings.",
            default=5, minimum=0, maximum=100,
        ),
        "summary_only": Arg(
            "boolean",
            "Return counts per rule with no examples. Use this first on a large "
            "instance, then re-run for the rules that matter.",
            default=False,
        ),
    },
)
async def audit(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    wanted_rules: set[str] | None = set(args["rules"]) if args.get("rules") else None
    wanted_tags: set[str] | None = set(args["tags"]) if args.get("tags") else None
    threshold = SEVERITY_ORDER.index(Severity(args.get("min_severity", "info")))
    limit = 0 if args.get("summary_only") else args.get("examples", 5)

    if wanted_rules and (unknown := wanted_rules - REGISTRY.keys()):
        raise ValueError(
            f"Unknown rule(s): {', '.join(sorted(unknown))}. "
            f"Available: {', '.join(sorted(REGISTRY))}"
        )
    if wanted_tags and (unknown_tags := wanted_tags - set(ALL_TAGS)):
        raise ValueError(
            f"Unknown tag(s): {', '.join(sorted(unknown_tags))}. "
            f"Available: {', '.join(ALL_TAGS)}"
        )

    context = await AuditContext.build(hass)

    selected = [
        rule for rule in REGISTRY.values()
        if (wanted_rules is None or rule.id in wanted_rules)
        and (wanted_tags is None or rule.tags & wanted_tags)
        and SEVERITY_ORDER.index(rule.severity) <= threshold
    ]

    results = []
    skipped: dict[str, str] = {}
    for rule in selected:
        try:
            findings = list(rule.check(context))
        except Exception as err:  # noqa: BLE001 - one bad rule must not void the audit
            skipped[rule.id] = f"{type(err).__name__}: {err}"
            continue
        if not findings:
            continue
        entry: dict[str, Any] = {
            "rule": rule.id,
            "severity": str(rule.severity),
            "title": rule.title,
            "why": rule.why,
            "knowledge": rule.knowledge,
            "tags": sorted(rule.tags),
            "count": len(findings),
        }
        if limit:
            entry["examples"] = [f.as_dict() for f in findings[:limit]]
            if len(findings) > limit:
                entry["truncated"] = len(findings) - limit
        results.append(entry)

    results.sort(key=lambda r: (SEVERITY_ORDER.index(Severity(r["severity"])), -r["count"]))

    report: dict[str, Any] = {
        "instance": {
            "entities": len(context.all_entities),
            "devices": len(context.all_devices),
            "areas": len(context.area_list),
            "floors": len(context.floor_list),
            "automations": len(context.automation_configs),
            "custom_dashboards": len(context.dashboards),
        },
        "totals": {
            str(severity): sum(
                r["count"] for r in results if r["severity"] == str(severity)
            )
            for severity in SEVERITY_ORDER
        },
        "rules_run": len(selected),
        "findings": results,
    }
    if skipped:
        report["rules_skipped"] = skipped
    report["next_step"] = (
        "Read the knowledge resource for a rule before acting on it. Fix areas and "
        "floors first: the auto-generated dashboard and every room-based voice command "
        "depend on them, so later fixes are cheaper afterwards. "
        "See ha://knowledge/onboarding for the order."
    )
    return report
