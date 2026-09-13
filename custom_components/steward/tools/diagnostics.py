"""History, statistics, logs and automation traces."""

from __future__ import annotations

from datetime import timedelta
from functools import partial
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..permissions import Access, Policy
from ._schema import Arg, tool


def _require(hass: HomeAssistant, component: str) -> None:
    """Fail with an explanation rather than an import error."""
    if component not in hass.config.components:
        raise ValueError(
            f"The '{component}' integration is not loaded, so this data is unavailable."
        )


@tool(
    "ha_history",
    "State history for specific entities. A frequently-updating sensor produces "
    "thousands of rows per hour, so keep the window short. History is purged on the "
    "recorder's retention schedule (10 days by default); for longer periods use "
    "ha_statistics instead.",
    Access.READ,
    {
        "entity_ids": Arg("array", "Entities to fetch history for", required=True,
                          items={"type": "string"}),
        "hours_back": Arg("number", "How far back to look", default=24),
        "minimal": Arg(
            "boolean",
            "Drop attributes and insignificant changes. Turning this off multiplies "
            "the payload several-fold.",
            default=True,
        ),
    },
)
async def history(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    _require(hass, "recorder")
    from homeassistant.components.recorder import get_instance, history as rec_history

    start = dt_util.utcnow() - timedelta(hours=args.get("hours_back", 24))
    minimal = args.get("minimal", True)

    entity_ids = [e for e in args["entity_ids"] if policy.can_read_entity(e)]
    if not entity_ids:
        raise ValueError("None of the requested entities are readable by this account.")

    states = await get_instance(hass).async_add_executor_job(
        partial(
            rec_history.get_significant_states,
            hass,
            start,
            None,
            entity_ids,
            significant_changes_only=minimal,
            minimal_response=minimal,
            no_attributes=minimal,
        )
    )

    # With minimal_response the first row per entity is a State and the rest
    # are compact dicts, so normalise both shapes.
    def row(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return {
                "state": item.get("state"),
                "last_changed": item.get("last_changed"),
                **({"attributes": item["attributes"]} if "attributes" in item else {}),
            }
        out: dict[str, Any] = {"state": item.state, "last_changed": item.last_changed}
        if not minimal:
            out["attributes"] = dict(item.attributes)
        return out

    return {entity_id: [row(r) for r in rows] for entity_id, rows in states.items()}


@tool(
    "ha_statistics",
    "Long-term statistics: the downsampled store behind the Energy dashboard. Unlike "
    "history these survive the recorder's purge, so use them for energy, cost and "
    "generation totals over weeks or months. Call with no statistic_ids to discover "
    "what is tracked.",
    Access.READ,
    {
        "statistic_ids": Arg("array", "Statistic IDs. Omit to list what is available.",
                             items={"type": "string"}),
        "days_back": Arg("number", "How far back to start", default=7),
        "period": Arg("string", "Bucket size", default="day",
                      enum=["5minute", "hour", "day", "week", "month"]),
    },
)
async def statistics(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    _require(hass, "recorder")
    from homeassistant.components.recorder import get_instance, statistics as rec_stats

    instance = get_instance(hass)

    if not args.get("statistic_ids"):
        ids = await instance.async_add_executor_job(rec_stats.list_statistic_ids, hass, None, None)
        return [
            {
                "statistic_id": item["statistic_id"],
                "unit": item.get("display_unit_of_measurement"),
                "has_sum": item.get("has_sum"),
                "has_mean": item.get("has_mean"),
            }
            for item in ids
        ]

    start = dt_util.utcnow() - timedelta(days=args.get("days_back", 7))
    result = await instance.async_add_executor_job(
        rec_stats.statistics_during_period,
        hass,
        start,
        None,
        set(args["statistic_ids"]),
        args.get("period", "day"),
        None,
        {"change", "sum", "min", "max", "mean"},
    )
    return result


@tool(
    "ha_logbook",
    "Logbook entries, which describe what changed and why in readable form. Better "
    "than ha_history for tracing a sequence of events. Numeric sensors never appear "
    "here; Home Assistant treats them as continuous. Use ha_history for those.",
    Access.READ,
    {
        "entity_id": Arg("string", "Restrict to one entity"),
        "hours_back": Arg("number", "How far back to look", default=24),
        "limit": Arg(
            "integer",
            "Most recent entries to return. A busy house logs thousands per hour, so "
            "filter by entity or keep this small.",
            default=100, minimum=1, maximum=2000,
        ),
    },
)
async def logbook(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    _require(hass, "logbook")
    from homeassistant.components.logbook import processor
    from homeassistant.components.recorder import get_instance

    from homeassistant.components.logbook.helpers import async_determine_event_types

    start = dt_util.utcnow() - timedelta(hours=args.get("hours_back", 24))
    entity_ids = [args["entity_id"]] if args.get("entity_id") else None
    if entity_ids and not all(policy.can_read_entity(e) for e in entity_ids):
        raise ValueError("That entity is not readable by this account.")

    event_types = async_determine_event_types(hass, entity_ids, None)
    events = processor.EventProcessor(hass, event_types, entity_ids=entity_ids)
    rows = await get_instance(hass).async_add_executor_job(
        events.get_events, start, dt_util.utcnow()
    )
    if entity_ids is None:
        rows = [r for r in rows if not r.get("entity_id") or policy.can_read_entity(r["entity_id"])]

    limit = args.get("limit", 100)
    if len(rows) <= limit:
        return rows
    # Newest last, so the tail is the most recent slice.
    return {
        "entries": rows[-limit:],
        "returned": limit,
        "total_in_window": len(rows),
        "note": "Truncated to the most recent entries. Filter by entity_id or raise limit.",
    }


@tool(
    "ha_error_log",
    "Read the Home Assistant log, most recent lines last. Filter by a substring such "
    "as an entity ID or integration name to find a specific failure.",
    Access.SENSITIVE,
    {
        "lines": Arg("integer", "Trailing lines to return", default=200, minimum=1, maximum=2000),
        "filter": Arg("string", "Only lines containing this case-insensitive substring"),
        "errors_only": Arg("boolean", "Only ERROR and CRITICAL lines", default=False),
    },
)
async def error_log(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    path = hass.config.path("home-assistant.log")

    def read() -> list[str]:
        try:
            with open(path, encoding="utf8", errors="replace") as handle:
                return handle.read().splitlines()
        except FileNotFoundError:
            return []

    all_lines = await hass.async_add_executor_job(read)
    if not all_lines:
        return {"lines": "", "note": f"No log file at {path}. Logging may be going to the console."}

    matched = all_lines
    if args.get("errors_only"):
        matched = [line for line in matched if "ERROR" in line or "CRITICAL" in line]
    if needle := args.get("filter"):
        matched = [line for line in matched if needle.lower() in line.lower()]

    limit = args.get("lines", 200)
    return {
        "lines": "\n".join(matched[-limit:]),
        "returned_lines": min(len(matched), limit),
        "matched_lines": len(matched),
        "total_lines": len(all_lines),
    }


@tool(
    "ha_trace",
    "Automation and script traces: a step-by-step record of a past run showing which "
    "triggers fired, which conditions passed or failed, and what each step did. This "
    "is how to find out why an automation did not do what was expected, rather than "
    "guessing from its config. Recent traces survive a restart.",
    Access.SENSITIVE,
    {
        "action": Arg("string", "List recent runs, or fetch one in full",
                      required=True, enum=["list", "get"]),
        "item_id": Arg(
            "string",
            "The automation's config id or the script's object id. Omit with 'list' to "
            "see every traced item.",
        ),
        "run_id": Arg("string", "Which run to fetch, from 'list'"),
        "domain": Arg("string", "Which kind of item", default="automation",
                      enum=["automation", "script"]),
    },
)
async def trace(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    _require(hass, "trace")
    # Go through the same helpers the WebSocket API uses. They restore traces
    # persisted across restarts and hide how the store is shaped, which changed
    # between releases.
    from homeassistant.components.trace.util import async_get_trace, async_list_traces

    domain = args.get("domain", "automation")
    item_id = args.get("item_id")

    if args["action"] == "list":
        key = f"{domain}.{item_id}" if item_id else None
        traces = await async_list_traces(hass, domain, key)
        results = [
            {
                "item_id": t.get("item_id"),
                "run_id": t.get("run_id"),
                "started": (t.get("timestamp") or {}).get("start"),
                "finished": (t.get("timestamp") or {}).get("finish"),
                "state": t.get("state"),
                "script_execution": t.get("script_execution"),
                "last_step": t.get("last_step"),
                "error": t.get("error"),
            }
            for t in traces
        ]
        results.sort(key=lambda r: str(r.get("started")), reverse=True)
        if not results:
            return {
                "traces": [],
                "note": "No traces stored for that selection. Trigger the automation and try again.",
            }
        return results

    if not item_id or not args.get("run_id"):
        raise ValueError("item_id and run_id are both required to get a trace; use 'list' first")

    try:
        return await async_get_trace(hass, f"{domain}.{item_id}", args["run_id"])
    except KeyError as err:
        raise ValueError(f"No trace for {domain}.{item_id} run {args['run_id']}") from err
