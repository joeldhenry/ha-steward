"""Exercise the config CRUD and diagnostics tools against a real HA core."""
import asyncio, json, sys, tempfile, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.helpers import (area_registry as ar, device_registry as dr,
                                   entity_registry as er, floor_registry as fr,
                                   label_registry as lr)
from homeassistant.setup import async_setup_component
from homeassistant import loader

CFG = tempfile.mkdtemp(prefix="hacfg-")
# Reloading a domain re-reads configuration.yaml, so it has to exist.
pathlib.Path(CFG, "configuration.yaml").write_text(
    "homeassistant:\n  name: Test\nautomation: !include automations.yaml\n"
    "script: !include scripts.yaml\n"
)
pathlib.Path(CFG, "automations.yaml").write_text("[]\n")
pathlib.Path(CFG, "scripts.yaml").write_text("{}\n")


async def main():
    hass = HomeAssistant(CFG)
    hass.config.skip_pip = True
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    for mod in (ar, dr, er, fr, lr):
        await mod.async_load(hass)
    await hass.async_start()

    # Real automation + script components so reload and validation work.
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "automation", {})
    assert await async_setup_component(hass, "script", {})
    await hass.async_block_till_done()

    entry = ConfigEntry(version=1, minor_version=1, domain="steward", title="Steward",
                        data={}, options={"allow_write": True, "allow_destructive": True,
                                          "require_admin": True},
                        source="user", entry_id="s", unique_id="steward",
                        discovery_keys={}, subentries_data=[], state=ConfigEntryState.LOADED)
    hass.config_entries._entries[entry.entry_id] = entry

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
        r = await proto.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": name, "arguments": args}})
        return r["result"]

    # Build a small instance with a planted problem per rule family.
    from homeassistant.helpers import area_registry as ar2, device_registry as dr2, entity_registry as er2
    areas, devices, entities = ar2.async_get(hass), dr2.async_get(hass), er2.async_get(hass)
    living = areas.async_create("Living Room"); court = areas.async_create("Courtyard")
    areas.async_create("staircase"); areas.async_create("Intergrations"); areas.async_create("Spare")

    demo = ConfigEntry(version=1, minor_version=1, domain="demo", title="Demo", data={}, options={},
                       source="user", entry_id="demo", unique_id="demo", discovery_keys={},
                       subentries_data=[], state=ConfigEntryState.LOADED)
    hass.config_entries._entries[demo.entry_id] = demo

    dev = devices.async_get_or_create(config_entry_id="demo",
        identifiers={("demo","gang")}, name="Front Door Switch", manufacturer="Acme", model="2-gang")
    devices.async_update_device(dev.id, area_id=living.id)
    dead = devices.async_get_or_create(config_entry_id="demo",
        identifiers={("demo","dead")}, name="Old Sensor", manufacturer="Acme")

    e_court = entities.async_get_or_create("light","demo","g2",device_id=dev.id, suggested_object_id="courtyard_light")
    e_noname = entities.async_get_or_create("light","demo","g3",device_id=dev.id, suggested_object_id="unnamed_light")
    e_hex = entities.async_get_or_create("sensor","demo","hex",device_id=dev.id, suggested_object_id="temp_0x00158d0004a1b2")
    e_energy = entities.async_get_or_create("sensor","demo","kwh", suggested_object_id="solar_today")
    e_scene = entities.async_get_or_create("scene","demo","sc", suggested_object_id="movie_night")
    for i in (1,2):
        entities.async_get_or_create("binary_sensor","demo",f"dead{i}",device_id=dead.id, suggested_object_id=f"old_motion_{i}")
    # Orphan: create an entity on a second entry, then drop the entry so the
    # registry entry outlives its integration.
    gone = ConfigEntry(version=1, minor_version=1, domain="gone", title="Gone", data={}, options={},
                       source="user", entry_id="gone", unique_id="gone", discovery_keys={},
                       subentries_data=[], state=ConfigEntryState.LOADED)
    hass.config_entries._entries[gone.entry_id] = gone
    entities.async_get_or_create("sensor","gone","orphan", config_entry=gone, suggested_object_id="ghost")
    del hass.config_entries._entries[gone.entry_id]

    hass.states.async_set(e_court.entity_id,"off",{"friendly_name":"Courtyard Light"})
    hass.states.async_set(e_noname.entity_id,"off",{})
    hass.states.async_set(e_hex.entity_id,"21",{"friendly_name":"Temp 0x00158d0004a1b2","unit_of_measurement":"°C"})
    hass.states.async_set(e_energy.entity_id,"23.4",{"friendly_name":"Solar today","unit_of_measurement":"kWh","device_class":"energy"})
    hass.states.async_set(e_scene.entity_id,"2026-01-01T00:00:00+00:00",{"friendly_name":"Movie night"})
    hass.states.async_set("binary_sensor.old_motion_1","unavailable",{"friendly_name":"Old motion 1"})
    hass.states.async_set("binary_sensor.old_motion_2","unavailable",{"friendly_name":"Old motion 2"})

    # An automation with a dead reference and a device trigger.
    await call(admin, "ha_config", {"action":"create","kind":"automation","config_id":"a1","config":{
        "alias":"Broken one",
        "triggers":[{"trigger":"device","device_id":dev.id,"domain":"light","type":"turned_on","entity_id":e_court.entity_id}],
        "actions":[{"action":"light.turn_on","target":{"entity_id":"light.does_not_exist"}}]}})
    await hass.async_block_till_done()

    # Two lights sharing a name in one room, plus an exposed light with no area:
    # the cases voice and CarPlay cannot disambiguate.
    d1 = entities.async_get_or_create("light","demo","dup1",device_id=dev.id, suggested_object_id="dup_a")
    d2 = entities.async_get_or_create("light","demo","dup2",device_id=dev.id, suggested_object_id="dup_b")
    orphan_light = entities.async_get_or_create("light","demo","noarea", suggested_object_id="floating")
    hass.states.async_set(d1.entity_id,"off",{"friendly_name":"Ceiling Light"})
    hass.states.async_set(d2.entity_id,"off",{"friendly_name":"Ceiling Light"})
    hass.states.async_set(orphan_light.entity_id,"off",{"friendly_name":"Floating Lamp"})
    # Exposed binary sensor with no device class: voice cannot say what "on" means.
    bs = entities.async_get_or_create("binary_sensor","demo","bare", suggested_object_id="back_door")
    hass.states.async_set(bs.entity_id,"off",{"friendly_name":"Back Door"})
    await hass.async_block_till_done()

    print("=== voice / carplay rules (exposure-dependent) ===")
    from homeassistant.components.homeassistant.exposed_entities import async_should_expose
    print("  exposure API live? light exposed to conversation:",
          async_should_expose(hass, "conversation", d1.entity_id))
    out = json.loads((await call(admin,"ha_audit",{"tags":["voice"],"examples":2}))["content"][0]["text"])
    for f in out["findings"]:
        print(f"  {f['rule']:<30} {f['count']}")
        for ex in f.get("examples",[]): print(f"     {ex['detail'][:88]}")
    print()

    print("=== ha_audit: summary ===")
    out = json.loads((await call(admin,"ha_audit",{"summary_only":True}))["content"][0]["text"])
    print("instance:", json.dumps(out["instance"]))
    print("totals:", json.dumps(out["totals"]), "| rules run:", out["rules_run"])
    if out.get("rules_skipped"): print("SKIPPED:", json.dumps(out["rules_skipped"], indent=2))
    for f in out["findings"]:
        print(f"  [{f['severity']:<7}] {f['rule']:<32} {f['count']}")

    print("\n=== tag filter: dashboard ===")
    out = json.loads((await call(admin,"ha_audit",{"tags":["dashboard"],"examples":1}))["content"][0]["text"])
    for f in out["findings"]:
        print(f"  {f['rule']:<32} {f['count']}  e.g. {f.get('examples',[{}])[0].get('detail','')[:60]}")

    print("\n=== tag filter: carplay/watch/voice ===")
    out = json.loads((await call(admin,"ha_audit",{"tags":["carplay","watch"],"examples":1}))["content"][0]["text"])
    for f in out["findings"]:
        print(f"  {f['rule']:<32} {f['count']}  e.g. {f.get('examples',[{}])[0].get('detail','')[:60]}")

    print("\n=== bad filters rejected ===")
    print(" ", (await call(admin,"ha_audit",{"tags":["nope"]}))["content"][0]["text"][:90])
    print(" ", (await call(admin,"ha_audit",{"rules":["fake/rule"]}))["content"][0]["text"][:90])

    print("\n=== per-op permissions ===")
    t = await guest.dispatch({"jsonrpc":"2.0","id":1,"method":"tools/list"})
    tools = {x["name"]: x for x in t["result"]["tools"]}
    print("  non-admin sees ha_config:", "ha_config" in tools)
    if "ha_config" in tools:
        print("  description hint:", tools["ha_config"]["description"][-70:])
    print("  non-admin read :", (await call(guest,"ha_config",{"action":"list","kind":"automation"}))["content"][0]["text"][:60])
    print("  non-admin write:", (await call(guest,"ha_config",{"action":"create","kind":"automation","config_id":"x","config":{"alias":"x","triggers":[],"actions":[]}}))["content"][0]["text"][:80])
    print("  admin delete (destructive allowed):", (await call(admin,"ha_config",{"action":"delete","kind":"automation","config_id":"a1"}))["content"][0]["text"][:60])

    await hass.async_stop()

asyncio.run(main())
