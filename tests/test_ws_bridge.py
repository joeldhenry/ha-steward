"""The websocket bridge against the installed Home Assistant.

Two breaks reached a live instance because the test environment ran an older
Home Assistant than the target: ActiveConnection gained a required `remote`
argument in 2026.9, and commands that take no arguments are registered with
their schema set to False, which the bridge called as though it were a
validator. Both are asserted here against whatever version is installed, so
running the suite on two versions catches drift in either direction.
"""
import os
import asyncio, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from homeassistant import loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (area_registry as ar, device_registry as dr,
                                   entity_registry as er, floor_registry as fr,
                                   label_registry as lr)
from homeassistant.helpers import frame
from homeassistant.setup import async_setup_component


class FakeUser:
    id = "test-user"
    is_admin = True
    name = "Test"
    refresh_tokens: dict = {}
    permissions = None


class FakePolicy:
    user = FakeUser()

    async def async_refresh_token(self, hass):
        from custom_components.steward.ws_bridge import stand_in_refresh_token
        return stand_in_refresh_token()


async def main():
    from custom_components.steward.ws_bridge import ws_call
    import homeassistant.const as ha_const

    hass = HomeAssistant(tempfile.mkdtemp(prefix="hacfg-"))
    policy = FakePolicy()
    try:
        hass.config.skip_pip = True
        loader.async_setup(hass)
        hass.config_entries = ConfigEntries(hass, {})
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

        await async_setup_component(hass, "homeassistant", {})
        assert await async_setup_component(hass, "input_boolean", {})
        assert await async_setup_component(hass, "counter", {})
        await hass.async_block_till_done()
        print(f"ok   booted Home Assistant {ha_const.__version__}")

        # A command with a real schema. This is the path that died with
        # "ActiveConnection.__init__() missing 1 required positional argument".
        created = await ws_call(
            hass, policy, "input_boolean/create", name="Bridge probe", icon="mdi:test-tube"
        )
        assert created["name"] == "Bridge probe", created
        await hass.async_block_till_done()
        assert hass.states.get("input_boolean.bridge_probe") is not None
        print("ok   schema-bearing command dispatched; entity exists")

        # A command declared with only a type. Recent Home Assistant stores the
        # schema for these as the literal False and dispatches them unvalidated,
        # which is what the bridge called as though it were a validator. Older
        # releases keep a real schema. Registering one here exercises whichever
        # the installed version does, instead of guessing at a built-in command.
        from homeassistant.components import websocket_api
        from homeassistant.components.websocket_api import const as ws_const

        @websocket_api.websocket_command({"type": "steward_test/ping"})
        @websocket_api.callback
        def _ping(hass_, connection, msg):
            connection.send_result(msg["id"], {"pong": True})

        websocket_api.async_register_command(hass, _ping)
        _, schema = hass.data[ws_const.DOMAIN]["steward_test/ping"]
        stored = "False" if schema is False else type(schema).__name__

        pong = await ws_call(hass, policy, "steward_test/ping")
        assert pong == {"pong": True}, pong
        print(f"ok   argument-free command dispatched (this version stores {stored})")

        # Extra keys must be refused rather than reaching a handler that never
        # validated them. The wording differs by version; the refusal must not.
        try:
            await ws_call(hass, policy, "steward_test/ping", bogus="x")
            raise AssertionError("expected a refusal")
        except ValueError as err:
            assert "bogus" in str(err) or "takes no arguments" in str(err), err
            print("ok   extra keys on an argument-free command are refused")

        await ws_call(hass, policy, "input_boolean/delete", input_boolean_id=created["id"])
        await hass.async_block_till_done()
        assert hass.states.get("input_boolean.bridge_probe") is None
        print("ok   delete dispatched; entity gone")
    finally:
        await hass.async_stop()

asyncio.run(main())

# Everything above has passed by this point. Tearing down Home Assistant's
# threads can crash the interpreter itself on some builds, which would turn a
# green run red, so leave before that can happen.
sys.stdout.flush()
os._exit(0)
