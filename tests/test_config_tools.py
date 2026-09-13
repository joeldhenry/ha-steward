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
    try:
        await _body(hass)
    finally:
        await hass.async_stop()


async def _body(hass):
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
    # A real recorder so history and statistics run against actual data. Logbook
    # depends on frontend and therefore the whole HTTP stack, so it is exercised
    # on a live instance instead.
    # Bootstrap primes recorder state before component setup; do the same.
    from homeassistant.helpers.recorder import async_initialize_recorder
    async_initialize_recorder(hass)
    assert await async_setup_component(hass, "recorder", {"recorder": {"db_url": f"sqlite:///{CFG}/recorder.db", "commit_interval": 0}})
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

    proto = MCPProtocol(hass, User("Joel", True))

    async def call(name, args):
        r = await proto.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": name, "arguments": args}})
        return r["result"]

    def show(label, res):
        text = res["content"][0]["text"]
        flag = "ERR " if res.get("isError") else "ok  "
        print(f"{flag}{label}: {text[:150].replace(chr(10),' ')}")
        return text

    tools = await proto.dispatch({"jsonrpc": "2.0", "id": 0, "method": "tools/list"})
    names = [t["name"] for t in tools["result"]["tools"]]
    print(f"tools: {len(names)}\n  " + "\n  ".join(sorted(names)) + "\n")

    print("=== ha_config: automation lifecycle ===")
    show("list (empty)", await call("ha_config", {"action": "list", "kind": "automation"}))

    created = show("create", await call("ha_config", {
        "action": "create", "kind": "automation", "config_id": "test1",
        "config": {"alias": "Porch light at sunset",
                   "triggers": [{"trigger": "sun", "event": "sunset"}],
                   "conditions": [],
                   "actions": [{"action": "light.turn_on",
                                "target": {"entity_id": "light.porch"}}],
                   "mode": "single"}}))

    show("list", await call("ha_config", {"action": "list", "kind": "automation"}))
    got = show("get", await call("ha_config", {"action": "get", "kind": "automation",
                                               "config_id": "test1"}))

    print("\n-- replace semantics: update without the condition should not leave it behind --")
    await call("ha_config", {"action": "update", "kind": "automation", "config_id": "test1",
                             "config": {"alias": "Renamed",
                                        "triggers": [{"trigger": "sun", "event": "sunrise"}],
                                        "actions": [{"action": "light.turn_off",
                                                     "target": {"entity_id": "light.porch"}}]}})
    after = json.loads(show("get after update", await call(
        "ha_config", {"action": "get", "kind": "automation", "config_id": "test1"})))
    assert after["alias"] == "Renamed", after
    assert after["triggers"][0]["event"] == "sunrise", after
    print("   -> replaced cleanly, stale keys gone")

    print("\n-- validation rejects a broken config --")
    show("invalid", await call("ha_config", {
        "action": "create", "kind": "automation", "config_id": "bad",
        "config": {"alias": "Bad", "triggers": [{"trigger": "nonsense_platform"}],
                   "actions": []}}))

    print("\n-- entity actually exists in HA after reload --")
    await hass.async_block_till_done()
    print("   automation entities:", [s.entity_id for s in hass.states.async_all("automation")])

    show("delete", await call("ha_config", {"action": "delete", "kind": "automation",
                                            "config_id": "test1"}))
    show("get deleted", await call("ha_config", {"action": "get", "kind": "automation",
                                                 "config_id": "test1"}))

    print("\n=== ha_config: script ===")
    show("create script", await call("ha_config", {
        "action": "create", "kind": "script", "config_id": "evening_routine",
        "config": {"alias": "Evening routine",
                   "sequence": [{"action": "light.turn_off",
                                 "target": {"entity_id": "light.porch"}}]}}))
    await hass.async_block_till_done()
    print("   script entities:", [s.entity_id for s in hass.states.async_all("script")])

    print("\n=== diagnostics against a real recorder ===")
    from homeassistant.components.recorder import get_instance
    hass.states.async_set("light.porch", "off", {"friendly_name": "Porch"})
    hass.states.async_set("light.porch", "on", {"friendly_name": "Porch", "brightness": 200})
    hass.states.async_set("light.porch", "off", {"friendly_name": "Porch"})
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()

    hist = show("ha_history minimal", await call("ha_history", {"entity_ids": ["light.porch"], "hours_back": 1}))
    rows = json.loads(hist).get("light.porch", [])
    assert len(rows) >= 3, f"expected 3 state changes, got {len(rows)}"
    assert all("attributes" not in r for r in rows), "minimal should drop attributes"
    print(f"   -> {len(rows)} rows, no attributes")

    full = json.loads(show("ha_history full", await call("ha_history", {"entity_ids": ["light.porch"], "hours_back": 1, "minimal": False})))
    assert any("attributes" in r for r in full["light.porch"]), "full history should carry attributes"
    print("   -> full history carries attributes")

    lb = show("ha_logbook (no logbook component)", await call("ha_logbook", {"entity_id": "light.porch", "hours_back": 1}))
    assert "logbook" in lb and "not loaded" in lb, lb
    show("ha_statistics ids", await call("ha_statistics", {}))
    show("ha_trace list", await call("ha_trace", {"action": "list"}))
    show("ha_error_log", await call("ha_error_log", {"lines": 5}))

    print("\n=== non-admin: sensitive reads blocked, plain reads allowed ===")
    guest = MCPProtocol(hass, User("Guest", False))
    async def gcall(name, args):
        r = await guest.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                  "params": {"name": name, "arguments": args}})
        return r["result"]
    show("guest ha_get_states", await gcall("ha_get_states", {"domain": "light"}))
    show("guest ha_error_log", await gcall("ha_error_log", {}))
    show("guest ha_config get", await gcall("ha_config", {"action": "list", "kind": "automation"}))
    show("guest ha_render_template", await gcall("ha_render_template", {"template": "{{ 1 }}"}))


asyncio.run(main())
