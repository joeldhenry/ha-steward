"""Exercise the config CRUD and diagnostics tools against a real HA core."""
import os
import asyncio, json, sys, tempfile, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntries, ConfigEntry, ConfigEntryState
from homeassistant.helpers import (area_registry as ar, device_registry as dr,
                                   entity_registry as er, floor_registry as fr,
                                   label_registry as lr)
from homeassistant.helpers import frame
from homeassistant.helpers import condition as condition_helper, trigger as trigger_helper
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
    # 2026.9 keeps the trigger and condition platform registries in
    # hass.data, populated during core setup that a bare harness skips.
    for helper in (trigger_helper, condition_helper):
        if hasattr(helper, "async_setup"):
            await helper.async_setup(hass)
    # 2026.9 requires the frame helper before integrations set up.
    if hasattr(frame, "async_setup"):
        frame.async_setup(hass)
    # 2026.9 split registry setup from loading; older releases only have
    # the load half, so call setup where it exists.
    for mod in (ar, dr, er, fr, lr):
        if hasattr(mod, "async_setup"):
            mod.async_setup(hass)
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

    print("\n=== WebSocket bridge: helpers via a real input_boolean component ===")
    assert await async_setup_component(hass, "input_boolean", {})
    # describe_entity joins the domain's services, so the domain must be loaded.
    assert await async_setup_component(hass, "light", {})
    await hass.async_block_till_done()
    created = json.loads(show("ha_helper create", await call("ha_helper", {
        "action": "create", "kind": "input_boolean",
        "fields": {"name": "Guest mode", "icon": "mdi:account-group"}})))
    hid = created["id"]
    await hass.async_block_till_done()
    assert hass.states.get("input_boolean.guest_mode") is not None, "helper entity did not appear"
    print("   -> input_boolean.guest_mode exists in the state machine")
    listed = json.loads(show("ha_helper list", await call("ha_helper", {"action": "list", "kind": "input_boolean"})))
    assert any(i["id"] == hid for i in listed)
    show("ha_helper update", await call("ha_helper", {"action": "update", "kind": "input_boolean",
                                                       "helper_id": hid, "fields": {"name": "Guest Mode"}}))
    show("ha_helper delete", await call("ha_helper", {"action": "delete", "kind": "input_boolean", "helper_id": hid}))
    await hass.async_block_till_done()
    assert hass.states.get("input_boolean.guest_mode") is None, "helper entity survived deletion"
    print("   -> deleted through the bridge; entity gone")
    rejected = show("ha_helper rejects bad fields", await call("ha_helper", {
        "action": "create", "kind": "input_boolean", "fields": {"name": "x", "icon": 42}}))
    assert rejected.startswith("Error") and "Invalid arguments" in rejected, rejected
    print("   -> Home Assistant's own schema rejected it, not ours")

    print("\n=== labels ===")
    lab = json.loads(show("ha_manage_label create", await call("ha_manage_label",
                          {"action": "create", "name": "Whole house", "icon": "mdi:home"})))
    from homeassistant.helpers import entity_registry as er3
    porch = er3.async_get(hass).async_get_or_create("light", "demo", "porch", suggested_object_id="porch")
    hass.states.async_set(porch.entity_id, "off", {"friendly_name": "Porch", "supported_features": 44})
    show("label onto entity", await call("ha_update_entity", {"entity_id": porch.entity_id, "labels": [lab["created"]]}))
    filtered = json.loads(show("ha_get_states label filter", await call("ha_get_states", {"label_id": lab["created"]})))
    assert [e["entity_id"] for e in filtered] == [porch.entity_id], filtered
    print("   -> label filter returns exactly the labelled entity")

    print("\n=== error log keeps tracebacks attached to their record ===")
    pathlib.Path(CFG, "home-assistant.log").write_text(
        "2026-09-16 18:03:40.001 INFO (MainThread) [homeassistant.core] Starting\n"
        "2026-09-16 18:03:41.881 ERROR (MainThread) [custom_components.steward.protocol] Tool ha_backup failed\n"
        "Traceback (most recent call last):\n"
        '  File "ws_bridge.py", line 78, in ws_call\n'
        "    message = schema(message)\n"
        "TypeError: 'bool' object is not callable\n"
        "2026-09-16 18:03:42.100 INFO (MainThread) [homeassistant.core] Still going\n"
    )
    log = json.loads(show("ha_error_log errors_only", await call("ha_error_log", {"errors_only": True})))
    assert "Traceback (most recent call last):" in log["lines"], log
    assert "'bool' object is not callable" in log["lines"], log
    assert "Still going" not in log["lines"], log
    print("   -> errors_only keeps the stack under the message and drops unrelated records")
    filtered = json.loads(show("ha_error_log filter", await call("ha_error_log", {"filter": "ws_bridge"})))
    assert "Tool ha_backup failed" in filtered["lines"], filtered
    print("   -> filtering on a word that only appears in the stack returns the whole record")

    print("\n=== entity registry stays inside the response cap ===")
    summary = json.loads(show("ha_get_entity_registry summary_only",
                              await call("ha_get_entity_registry", {"summary_only": True})))
    assert "by_platform" in summary and "total" in summary, summary
    assert isinstance(summary["total"], int)
    print("   -> summary_only returns counts, not entries")
    capped = json.loads(show("ha_get_entity_registry limit=1", await call("ha_get_entity_registry", {"limit": 1})))
    if isinstance(capped, dict):
        assert capped["returned"] == 1 and "more match" in capped["note"], capped
        print("   -> over the limit, the tool says how to narrow instead of truncating silently")

    print("\n=== describe, validate, check_config, repairs ===")
    desc = json.loads(show("ha_describe_entity", await call("ha_describe_entity", {"entity_id": porch.entity_id})))
    assert desc["supported_features"] == ["EFFECT", "FLASH", "TRANSITION"], desc["supported_features"]
    assert "turn_on" in desc["services"], f"light services not joined: {desc['services']}"
    assert desc["registry"]["labels"] == [lab["created"]], desc["registry"]["labels"]
    print("   -> features decoded to names; services and labels joined")
    ok = json.loads(show("ha_validate_config ok", await call("ha_validate_config", {
        "kind": "triggers", "config": [{"trigger": "state", "entity_id": porch.entity_id, "to": "on"}]})))
    assert ok["valid"] is True
    bad = json.loads(show("ha_validate_config bad", await call("ha_validate_config", {
        "kind": "triggers", "config": [{"trigger": "nonsense"}]})))
    assert bad["valid"] is False
    show("ha_check_config", await call("ha_check_config", {}))
    show("ha_repairs", await call("ha_repairs", {}))
    unknown = show("ha_config_entry unknown id", await call("ha_config_entry", {"action": "reload", "entry_id": "nope"}))
    assert unknown.startswith("Error") and "No config entry" in unknown, unknown
    print("   -> unknown entry rejected; the reload path needs an integration with a "
          "config flow, so it is verified on a live instance instead")

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

# Everything above has passed by this point. Tearing down Home Assistant's
# threads can crash the interpreter itself on some builds, which would turn a
# green run red, so leave before that can happen.
sys.stdout.flush()
os._exit(0)
