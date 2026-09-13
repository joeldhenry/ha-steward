"""Boot a real Home Assistant core and exercise the Steward integration."""
import asyncio, sys, json, types
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar, device_registry as dr, entity_registry as er,
    floor_registry as fr, label_registry as lr,
)
from homeassistant.config_entries import ConfigEntries

import tempfile
CFG = tempfile.mkdtemp(prefix="hacfg-")


async def main():
    hass = HomeAssistant(CFG)
    hass.config_entries = ConfigEntries(hass, {})
    # Load the registries the tools read.
    for mod in (ar, dr, er, fr, lr):
        await mod.async_load(hass)
    await hass.async_start()

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

    e1 = entities.async_get_or_create("light", "demo", "gang1", device_id=dev.id,
                                      suggested_object_id="front_door_light")
    e2 = entities.async_get_or_create("light", "demo", "gang2", device_id=dev.id,
                                      suggested_object_id="courtyard_light")
    e3 = entities.async_get_or_create("sensor", "demo", "energy1",
                                      suggested_object_id="solar_forecast_today")
    entities.async_get_or_create("binary_sensor", "demo", "orphan1", device_id=orphan.id,
                                 suggested_object_id="orphan_motion")

    hass.states.async_set(e1.entity_id, "off", {"friendly_name": "Front Door Light"})
    hass.states.async_set(e2.entity_id, "off", {"friendly_name": "Courtyard Light"})
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

    entry = hass.states.get(e2.entity_id)
    print("\nunknown tool ->", (await call(admin, "ha_nope", {}))["content"][0]["text"][:60])
    print("bad args     ->", (await call(admin, "ha_get_state", {}))["content"][0]["text"][:70])
    await hass.async_stop()

asyncio.run(main())
