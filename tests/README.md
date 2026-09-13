# Tests

These boot a real Home Assistant core, build a small instance in the registries
(including the two-gang switch case the audit exists to catch), and exercise the
MCP protocol, the audit, the remediation loop and the permission model.

Home Assistant needs Python 3.13:

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python homeassistant
.venv/bin/python tests/test_integration.py
```

The harness is deliberately dependency-free rather than using
`pytest-homeassistant-custom-component`, so it runs against whatever Home
Assistant version is installed.
