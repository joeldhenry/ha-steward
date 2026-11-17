"""Boot a bare Home Assistant core the way the real bootstrap does.

Each suite used to carry its own copy of the base setup: the registries, the
frame helper, the trigger and condition platforms. Home Assistant adds a step
there most releases, and a copy that misses one does not fail, it waits. In
2026.11 the entity registry started waiting for the config entries to be read
from storage, which a hand-built `ConfigEntries` never signals, so every suite
hung until the six hour job limit.

`bootstrap.async_load_base_functionality` is the function Home Assistant itself
calls for this, on every supported version, so the harness calls it and stops
tracking the list by hand.
"""
import asyncio
import faulthandler
import logging
import sys

from homeassistant import bootstrap, loader
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant

# A suite takes a few seconds. Anything near this is a hang, and a traceback
# after two minutes is worth more than a cancelled job after six hours.
WATCHDOG_SECONDS = 120


class _Deprecations(logging.Handler):
    """Collect Home Assistant's reports of deprecated API use by Steward.

    Home Assistant logs these for a custom integration and raises for its own
    code, then turns the log into an error a year later. The 2026.10 device
    registry report sat in the CI output for five weeks without failing
    anything, so the suites now fail on one.
    """

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.seen: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "custom integration 'steward'" in message and message not in self.seen:
            self.seen.append(message)


DEPRECATIONS = _Deprecations()


async def boot(config_dir: str) -> HomeAssistant:
    """Return a started core with registries and config entries loaded."""
    hass = HomeAssistant(config_dir)
    hass.config.skip_pip = True
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)
    await hass.async_start()
    return hass


def add_entry(hass: HomeAssistant, entry) -> None:
    """Register a config entry without setting it up, as HA's test helpers do."""
    hass.config_entries._entries[entry.entry_id] = entry


def run(main) -> None:
    """Run a suite's coroutine under a watchdog that dumps every thread."""
    faulthandler.dump_traceback_later(WATCHDOG_SECONDS, exit=True, file=sys.stderr)
    logging.getLogger().addHandler(DEPRECATIONS)
    try:
        asyncio.run(main())
    finally:
        faulthandler.cancel_dump_traceback_later()
    if DEPRECATIONS.seen:
        for message in DEPRECATIONS.seen:
            print("DEPRECATED:", message, file=sys.stderr)
        raise SystemExit("Steward used an API that Home Assistant has deprecated")
