"""Boot a real Home Assistant core and exercise the Steward integration."""
import os
import asyncio, sys, json, types
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar, device_registry as dr, entity_registry as er,
    floor_registry as fr, frame, label_registry as lr,
)
from homeassistant.helpers import condition as condition_helper, trigger as trigger_helper
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries

import tempfile
from harness import boot, run
CFG = tempfile.mkdtemp(prefix="hacfg-")


async def main():
    hass = await boot(CFG)

    areas = ar.async_get(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    living = areas.async_create("Living Room")
    courtyard = areas.async_create("Courtyard")
    areas.async_create("staircase")          # casing violation
    areas.async_create("Intergrations")      # not-a-room + typo
    areas.async_create("Garage")

    # A two-gang wall switch physically in the living room, one gang driving a
    # courtyard light. Exactly the case the audit should catch.
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState
    demo_entry = ConfigEntry(
        version=1, minor_version=1, domain="demo", title="Demo", data={}, options={},
        source="user", entry_id="test", unique_id="demo", discovery_keys={},
        subentries_data=[], state=ConfigEntryState.LOADED,
    )
    # Register without triggering setup, the way HA's own test helpers do.
    hass.config_entries._entries[demo_entry.entry_id] = demo_entry

    mcp_entry = ConfigEntry(
        version=1, minor_version=1, domain="steward", title="Steward", data={},
        options={"allow_write": True, "allow_destructive": False, "require_admin": True},
        source="user", entry_id="hamcp", unique_id="steward", discovery_keys={},
        subentries_data=[], state=ConfigEntryState.LOADED,
    )
    hass.config_entries._entries[mcp_entry.entry_id] = mcp_entry
    dev = devices.async_get_or_create(
        config_entry_id="test",
        identifiers={("demo", "front_door_switch")},
        name="Front Door Switch",
        manufacturer="Acme",
        model="2-gang",
    )
    devices.async_update_device(dev.id, area_id=living.id)

    orphan = devices.async_get_or_create(
        config_entry_id="test",
        identifiers={("demo", "orphan")},
        name="Orphan Sensor",
        manufacturer="Acme",
    )

    # Each gang carries a name of its own, as a real multi-gang switch does.
    # From 2026.10 that is what lets an entity hold an area apart from its device.
    e1 = entities.async_get_or_create("light", "demo", "gang1", device_id=dev.id,
                                      suggested_object_id="front_door_light",
                                      original_name="Front Door Light")
    e2 = entities.async_get_or_create("light", "demo", "gang2", device_id=dev.id,
                                      suggested_object_id="courtyard_light",
                                      original_name="Courtyard Light")

    # A single-entity device whose one entity has no name of its own: it stands
    # for the device, so its room can only change on the device.
    lamp = devices.async_get_or_create(
        config_entry_id="test",
        identifiers={("demo", "garage_lamp")},
        name="Garage Lamp",
        manufacturer="Acme",
    )
    devices.async_update_device(lamp.id, area_id=living.id)
    e_lamp = entities.async_get_or_create("light", "demo", "lamp", device_id=lamp.id,
                                          suggested_object_id="garage_lamp")
    garage = areas.async_get_area_by_name("Garage")
    e3 = entities.async_get_or_create("sensor", "demo", "energy1",
                                      suggested_object_id="solar_forecast_today")
    entities.async_get_or_create("binary_sensor", "demo", "orphan1", device_id=orphan.id,
                                 suggested_object_id="orphan_motion")

    hass.states.async_set(e1.entity_id, "off", {"friendly_name": "Front Door Light"})
    hass.states.async_set(e2.entity_id, "off", {"friendly_name": "Courtyard Light"})
    hass.states.async_set(e_lamp.entity_id, "off", {"friendly_name": "Garage Lamp"})
    hass.states.async_set(e3.entity_id, "23.4",
                          {"friendly_name": "Solar forecast today",
                           "unit_of_measurement": "kWh", "device_class": "energy"})
    hass.states.async_set("binary_sensor.orphan_motion", "unavailable",
                          {"friendly_name": "Orphan motion"})
    await hass.async_block_till_done()

    # --- exercise the integration ---
    from custom_components.steward.protocol import MCPProtocol

    from homeassistant.auth.permissions import OwnerPermissions, PolicyPermissions
    from homeassistant.auth.permissions.system_policies import USER_POLICY

    class User:
        """Enough of homeassistant.auth.models.User for the policy layer."""
        def __init__(s, name, admin):
            s.name, s.is_admin, s.id = name, admin, f"user-{name.lower()}"
            s.permissions = OwnerPermissions if admin else PolicyPermissions(USER_POLICY, None)

    admin = MCPProtocol(hass, User("Joel", True))
    guest = MCPProtocol(hass, User("Guest", False))

    async def call(proto, name, args):
        r = await proto.dispatch({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                  "params": {"name": name, "arguments": args}})
        return r["result"]

    def wrong_area(audit):
        return next((f["count"] for f in audit["findings"] if f["rule"] == "entity/wrong-area"), 0)

    before = json.loads((await call(admin, "ha_audit", {}))["content"][0]["text"])
    print("=== remediation loop ===")
    print("wrong-area findings before:", wrong_area(before))

    fix = await call(admin, "ha_update_entity",
                     {"entity_id": e2.entity_id, "area_id": courtyard.id})
    print("applied fix:", fix["content"][0]["text"].replace(chr(10), " "))

    after = json.loads((await call(admin, "ha_audit", {}))["content"][0]["text"])
    print("wrong-area findings after: ", wrong_area(after))
    assert wrong_area(after) == wrong_area(before) - 1, "fix did not clear the finding"
    print("-> finding cleared\n")

    print("=== main entity of a device ===")
    import homeassistant.const as ha_const
    from custom_components.steward import registries
    lamp_finding = next(
        f for group in after["findings"] if group["rule"] == "entity/wrong-area"
        for f in group["examples"] if f.get("entity_id") == e_lamp.entity_id
    )
    print("fix offered:", lamp_finding["fix"][:90])
    refused = await call(admin, "ha_update_entity",
                         {"entity_id": e_lamp.entity_id, "area_id": garage.id})
    if registries.accepts_own_area(entities.async_get(e_lamp.entity_id)):
        # Before 2026.10 any entity may hold an override.
        assert not refused.get("isError"), refused
        assert "Override this entity" in lamp_finding["fix"], lamp_finding
        print(f"   -> {ha_const.__version__} accepts the override")
    else:
        text = refused["content"][0]["text"]
        assert refused.get("isError") and "ha_update_device" in text and lamp.id in text, refused
        assert "move the device" in lamp_finding["fix"], lamp_finding
        print("   -> override refused, and the error names the device to move")
        moved_lamp = await call(admin, "ha_update_device",
                                {"device_id": lamp.id, "area_id": garage.id})
        assert not moved_lamp.get("isError"), moved_lamp
    final = json.loads((await call(admin, "ha_audit", {}))["content"][0]["text"])
    assert wrong_area(final) == wrong_area(after) - 1, "moving the lamp did not clear the finding"
    print("   -> finding cleared\n")

    if hasattr(devices, "async_get_or_create_child"):
        print("=== child devices ===")
        child = devices.async_get_or_create_child(
            config_entry_id="test", identifiers={("demo", "front_door_switch_gang3")},
            name="Garage Gang", parent_device_id=dev.id,
        )
        e_child = entities.async_get_or_create("light", "demo", "gang3", device_id=child.id,
                                               suggested_object_id="garage_gang")
        hass.states.async_set(e_child.entity_id, "off", {"friendly_name": "Garage Gang"})
        listed = json.loads((await call(admin, "ha_get_devices", {"search": "garage gang"}))["content"][0]["text"])
        assert len(listed) == 1 and listed[0]["parent_device_id"] == dev.id, listed
        # No area of its own yet: it is in the parent's room, with the parent's hardware.
        assert listed[0]["area_id"] == living.id and listed[0]["area_is_inherited"], listed
        assert listed[0]["manufacturer"] == "Acme" and listed[0]["model"] == "2-gang", listed
        print("   -> listed under its parent, inheriting area and hardware details")

        child_audit = json.loads((await call(admin, "ha_audit", {}))["content"][0]["text"])
        child_finding = next(
            f for group in child_audit["findings"] if group["rule"] == "entity/wrong-area"
            for f in group["examples"] if f.get("entity_id") == e_child.entity_id
        )
        assert 'Set the area of its device "Garage Gang"' in child_finding["fix"], child_finding
        placed = await call(admin, "ha_update_device", {"device_id": child.id, "area_id": garage.id})
        assert not placed.get("isError") and f'"effective_area_id": "{garage.id}"' in placed["content"][0]["text"], placed
        described = json.loads((await call(admin, "ha_describe_entity", {"entity_id": e_child.entity_id}))["content"][0]["text"])
        assert described["area"]["area_id"] == garage.id, described["area"]
        assert described["device"]["parent_device_id"] == dev.id, described["device"]
        assert described["registry"]["accepts_area_override"] is False, described["registry"]
        cleared_child = json.loads((await call(admin, "ha_audit", {}))["content"][0]["text"])
        assert wrong_area(cleared_child) == wrong_area(child_audit) - 1
        print("   -> ha_update_device places the child, and the finding clears\n")

    print("=== ha_update_device ===")
    moved = await call(admin, "ha_update_device", {"device_id": dev.id, "area_id": courtyard.id})
    print("move device ->", moved["content"][0]["text"].replace(chr(10), " ")[:120])
    reg = json.loads((await call(admin, "ha_get_entity_registry", {"device_id": dev.id}))["content"][0]["text"])
    # area_is_override is now only present when true, so a thousand-entity
    # instance stays inside the response cap.
    inherited = [e for e in reg if not e.get("area_is_override")]
    assert inherited and all(e["area_id"] == courtyard.id for e in inherited), "entities did not inherit the device area"
    print(f"   -> {len(inherited)} non-overridden entities now inherit courtyard")
    cleared = await call(admin, "ha_update_device", {"device_id": dev.id, "area_id": ""})
    assert '"area_id": null' in cleared["content"][0]["text"], cleared
    print("   -> empty area_id clears the device's area\n")

    print("=== permissions ===")
    guest_tools = await guest.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    guest_names = {t["name"] for t in guest_tools["result"]["tools"]}
    admin_tools = await admin.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    admin_names = {t["name"] for t in admin_tools["result"]["tools"]}
    print(f"admin sees {len(admin_names)} tools, non-admin sees {len(guest_names)}")
    print("hidden from non-admin:", ", ".join(sorted(admin_names - guest_names)))

    denied = await call(guest, "ha_update_entity", {"entity_id": e1.entity_id, "name": "x"})
    print("non-admin write ->", denied["content"][0]["text"][:95])
    assert denied.get("isError"), "non-admin write was not blocked"

    denied2 = await call(admin, "ha_restart", {"confirm": True})
    print("admin destructive (disabled in options) ->", denied2["content"][0]["text"][:95])
    assert denied2.get("isError"), "destructive op was not blocked"

    print("\n=== security ===")
    from types import SimpleNamespace
    from homeassistant.setup import async_setup_component
    from custom_components.steward.permissions import Access, Policy
    from custom_components.steward.tools.entities import is_destructive_service

    # A generic service call must not be a way around the destructive switch.
    assert await async_setup_component(hass, "homeassistant", {})
    assert hass.services.has_service("homeassistant", "restart")
    for domain, service in (("homeassistant", "restart"), ("HomeAssistant", "Stop")):
        sneaky = await call(admin, "ha_call_service", {"domain": domain, "service": service})
        assert sneaky.get("isError") and "destructive" in sneaky["content"][0]["text"].lower(), sneaky
    for pair in (("recorder", "purge"), ("shell_command", "anything"), ("hassio", "host_shutdown")):
        assert is_destructive_service(*pair), pair
    assert not is_destructive_service("light", "turn_on")
    print("   -> restart, stop, purge and shell commands need the destructive level")

    # With "require admin" off, a non-admin gets service calls and nothing else.
    def policy_for(user, **options):
        base = {"allow_write": True, "allow_destructive": True, "require_admin": False}
        return Policy(SimpleNamespace(options={**base, **options}), user)
    loose = policy_for(guest.user)
    assert loose.allows(Access.WRITE, user_scoped=True)
    assert not loose.allows(Access.WRITE), "non-admin reached a registry or config write"
    assert not loose.allows(Access.DESTRUCTIVE), "non-admin reached a destructive operation"
    assert not loose.allows(Access.SENSITIVE)
    assert not policy_for(guest.user, require_admin=True).allows(Access.WRITE, user_scoped=True)
    assert policy_for(admin.user).allows(Access.DESTRUCTIVE)
    print("   -> a non-admin is limited to service calls even with 'require admin' off")

    # Positional params are refused, without a traceback in the log.
    positional = await admin.dispatch({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": [1]})
    assert positional["error"]["code"] == -32602, positional
    print("   -> list-shaped params rejected as invalid")

    # A template that would stall the event loop is abandoned at the timeout.
    import time
    began = time.monotonic()
    slow = await call(admin, "ha_render_template",
                      {"template": "{% for a in range(99999) %}{% for b in range(99999) %}"
                                   "{% endfor %}{% endfor %}done"})
    assert slow.get("isError") and "within" in slow["content"][0]["text"], slow
    assert time.monotonic() - began < 20
    quick = await call(admin, "ha_render_template", {"template": "{{ 1 + 1 }}"})
    assert '"result": 2' in quick["content"][0]["text"], quick
    print(f"   -> runaway template stopped after {time.monotonic() - began:.0f}s")

    # Oversized windows are refused at validation.
    wide = await call(admin, "ha_history", {"entity_ids": [e1.entity_id], "hours_back": 1e6})
    assert wide.get("isError") and "Invalid arguments" in wide["content"][0]["text"], wide
    print("   -> an unbounded history window is rejected")

    # Disabling or removing Steward turns every tool off at once, reads included.
    from homeassistant.config_entries import ConfigEntryState as _State
    object.__setattr__(mcp_entry, "state", _State.NOT_LOADED)
    off = await call(admin, "ha_get_states", {})
    assert off.get("isError") and "disabled" in off["content"][0]["text"], off
    listed_off = await admin.dispatch({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
    assert listed_off["result"]["tools"] == [], "tools still listed with Steward unloaded"
    del hass.config_entries._entries[mcp_entry.entry_id]
    gone = await call(admin, "ha_update_entity", {"entity_id": e1.entity_id, "name": "x"})
    assert gone.get("isError"), "write allowed after Steward was removed"
    object.__setattr__(mcp_entry, "state", _State.LOADED)
    hass.config_entries._entries[mcp_entry.entry_id] = mcp_entry
    assert not (await call(admin, "ha_get_states", {})).get("isError")
    print("   -> unloaded or removed: nothing is served; loaded again: back")

    entry = hass.states.get(e2.entity_id)
    print("\nunknown tool ->", (await call(admin, "ha_nope", {}))["content"][0]["text"][:60])
    print("bad args     ->", (await call(admin, "ha_get_state", {}))["content"][0]["text"][:70])
    await hass.async_stop()

run(main)

# Everything above has passed by this point. Tearing down Home Assistant's
# threads can crash the interpreter itself on some builds, which would turn a
# green run red, so leave before that can happen.
sys.stdout.flush()
os._exit(0)
