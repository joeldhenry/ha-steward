# Tests

These boot a real Home Assistant core, build a small instance in the registries
(including the two-gang switch case the audit exists to catch), and exercise the
MCP protocol, the WebSocket bridge, the audit, the remediation loop and the
permission model.

## Run them against two versions, not one

Current Home Assistant requires Python 3.14. On Python 3.13, `pip install
homeassistant` resolves to the newest release that still supports 3.13, which is
many months behind, and it does so without saying anything. Two breaks reached a
live 2026.9 instance that way while the suites and CI stayed green on an older
release: `ActiveConnection` gained a required argument, and argument-free
WebSocket commands started being registered with their schema set to `False`.

So run both. CI does the same thing in a matrix, and prints the version each job
resolved.

```bash
# Current Home Assistant
uv venv --python 3.14 .venv314
uv pip install --python .venv314/bin/python homeassistant

# Oldest supported, still on 3.13
uv venv --python 3.13 .venv313
uv pip install --python .venv313/bin/python homeassistant

for v in .venv314 .venv313; do
  $v/bin/python -c "import homeassistant.const as c; print('HA', c.__version__)"
  for t in tests/test_*.py; do $v/bin/python -u "$t" >/dev/null || echo "FAIL $t"; done
done
```

## Notes

The harness is deliberately dependency-free rather than using
`pytest-homeassistant-custom-component`, so it runs against whatever Home
Assistant version is installed. That means it also has to do the core setup a
real instance does: the registries, the frame helper, and the trigger and
condition platform registries. Newer releases split registry setup from loading
and will raise "not set up" without it, so each suite calls `async_setup` where
the installed version has it.

Each suite ends with `os._exit(0)`. Every assertion has passed by that point,
and tearing down Home Assistant's threads can crash the interpreter itself on
some builds, which would turn a green run red.
