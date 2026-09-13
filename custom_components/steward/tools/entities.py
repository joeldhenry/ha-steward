"""Entity state and service tools."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from ..permissions import Access, Policy
from ._schema import Arg, tool


@tool(
    "ha_get_states",
    "List entity states, filtered by domain or a name search. Returns identifying "
    "fields only; set include_attributes for the full payload, which is large across "
    "many entities.",
    Access.READ,
    {
        "domain": Arg("string", "Filter by domain, e.g. 'light', 'sensor'"),
        "search": Arg("string", "Case-insensitive substring matched against entity_id and name"),
        "area_id": Arg("string", "Only entities in this area, including those inheriting it from their device"),
        "device_id": Arg("string", "Only entities on this device"),
        "label_id": Arg("string", "Only entities carrying this label"),
        "include_attributes": Arg(
            "boolean", "Include every attribute. Combine with a filter.", default=False
        ),
    },
)
async def get_states(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    domain = args.get("domain")
    search = (args.get("search") or "").lower()

    # Area, device and label live in the registries, not on the state.
    allowed: set[str] | None = None
    if any(args.get(k) for k in ("area_id", "device_id", "label_id")):
        from homeassistant.helpers import device_registry as dr, entity_registry as er

        entities, devices = er.async_get(hass), dr.async_get(hass)
        allowed = set()
        for entry in entities.entities.values():
            if args.get("device_id") and entry.device_id != args["device_id"]:
                continue
            if args.get("label_id") and args["label_id"] not in entry.labels:
                continue
            if args.get("area_id"):
                device = devices.async_get(entry.device_id) if entry.device_id else None
                if (entry.area_id or (device.area_id if device else None)) != args["area_id"]:
                    continue
            allowed.add(entry.entity_id)

    results = []
    for state in hass.states.async_all(domain) if domain else hass.states.async_all():
        if allowed is not None and state.entity_id not in allowed:
            continue
        # Non-admins may have a per-entity read policy; honour it.
        if not policy.can_read_entity(state.entity_id):
            continue
        name = str(state.attributes.get("friendly_name", ""))
        if search and search not in state.entity_id.lower() and search not in name.lower():
            continue
        if args.get("include_attributes"):
            results.append(
                {
                    "entity_id": state.entity_id,
                    "state": state.state,
                    "attributes": dict(state.attributes),
                    "last_updated": state.last_updated,
                }
            )
        else:
            results.append(
                {
                    "entity_id": state.entity_id,
                    "state": state.state,
                    "name": name,
                    "unit": state.attributes.get("unit_of_measurement"),
                }
            )
    return results


@tool(
    "ha_get_state",
    "Get the current state and all attributes of one entity.",
    Access.READ,
    {"entity_id": Arg("string", "Entity ID, e.g. 'light.living_room'", required=True)},
)
async def get_state(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    state = hass.states.get(args["entity_id"])
    if state is None or not policy.can_read_entity(state.entity_id):
        # Same answer either way, so a restricted user cannot probe for existence.
        raise ValueError(f"No such entity: {args['entity_id']}")
    return {
        "entity_id": state.entity_id,
        "state": state.state,
        "attributes": dict(state.attributes),
        "last_changed": state.last_changed,
        "last_updated": state.last_updated,
    }


@tool(
    "ha_call_service",
    "Call any Home Assistant service, for example light.turn_on. Use ha_get_services "
    "to discover the fields a service accepts.",
    Access.WRITE,
    {
        "domain": Arg("string", "Service domain, e.g. 'light'", required=True),
        "service": Arg("string", "Service name, e.g. 'turn_on'", required=True),
        "service_data": Arg("object", "Payload including the target", default={}),
    },
)
async def call_service(hass: HomeAssistant, policy: Policy, args: dict[str, Any]) -> Any:
    domain, service = args["domain"], args["service"]
    if not hass.services.has_service(domain, service):
        raise ValueError(f"No such service: {domain}.{service}")

    # The user's context makes Home Assistant apply that user's own entity
    # permissions on top of ours, and attributes the change to them in the logbook.
    await hass.services.async_call(
        domain,
        service,
        args.get("service_data") or {},
        blocking=True,
        context=policy.context,
    )
    return {"called": f"{domain}.{service}"}


@tool(
    "ha_get_services",
    "List available services and the fields they accept. Filter by domain unless you "
    "need the whole catalogue, which runs to tens of thousands of tokens.",
    Access.READ,
    {
        "domain": Arg("string", "Only services in this domain"),
        "names_only": Arg("boolean", "Names without field definitions", default=False),
    },
)
async def get_services(hass: HomeAssistant, _policy: Policy, args: dict[str, Any]) -> Any:
    services = hass.services.async_services()
    domain = args.get("domain")

    if domain:
        if domain not in services:
            raise ValueError(
                f"No services for domain '{domain}'. Available: {', '.join(sorted(services))}"
            )
        services = {domain: services[domain]}

    if args.get("names_only"):
        return {name: sorted(items) for name, items in services.items()}
    return {
        name: {svc: str(desc) for svc, desc in items.items()} for name, items in services.items()
    }
