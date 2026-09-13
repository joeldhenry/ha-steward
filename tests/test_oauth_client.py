"""The client metadata document must satisfy Home Assistant's own validator.

Home Assistant fetches the client_id URL and parses the body with
_parse_metadata_document_redirect_uris, then compares the request's
redirect_uri against the result with exact string matching. This test runs
our document through a copy of that validator taken from the 2026.9.2 tag, so
a change on either side that would break login shows up here first.
"""
import asyncio, importlib.util, json, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from homeassistant.core import HomeAssistant
from homeassistant.helpers.network import NoURLAvailableError

VALIDATOR = pathlib.Path(__file__).with_name("indieauth_2026_9_2.py")


def load_validator():
    spec = importlib.util.spec_from_file_location("indieauth_2026_9_2", VALIDATOR)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


async def main():
    from custom_components.steward.oauth_client import (
        CLIENT_METADATA_PATH, client_metadata_document, redirect_uris,
    )
    hass = HomeAssistant(tempfile.mkdtemp(prefix="hacfg-"))
    try:
        # No external URL configured: the view must refuse rather than emit a
        # document whose client_id Home Assistant could never fetch.
        try:
            client_metadata_document(hass); raise AssertionError("expected NoURLAvailableError")
        except NoURLAvailableError:
            print("ok   no external URL -> NoURLAvailableError")

        hass.config.external_url = "https://ha.example.test"
        doc = client_metadata_document(hass)
        url = doc["client_id"]
        assert url == "https://ha.example.test" + CLIENT_METADATA_PATH, url
        print("ok   client_id names the external HTTPS URL:", url)

        v = load_validator()
        body = json.dumps(doc).encode()
        accepted = v._parse_metadata_document_redirect_uris(url, body, 200, False)
        assert accepted == redirect_uris(), accepted
        print(f"ok   HA 2026.9.2 validator accepts the document: {len(accepted)} redirect URIs")

        # What Claude Code sends with --callback-port 8080, exact-matched the way HA does.
        assert "http://localhost:8080/callback" in accepted
        assert "http://127.0.0.1:8080/callback" in accepted
        assert "http://localhost:53394/callback" not in accepted
        print("ok   pinned port matches; a random port still would not")

        assert v._is_valid_metadata_client_id(url)
        assert all(v._is_valid_metadata_redirect_uri(u) for u in accepted)
        assert len(body) < 4096, len(body)
        print(f"ok   document is {len(body)} bytes, under any fetch cap")
    finally:
        await hass.async_stop()

asyncio.run(main())
