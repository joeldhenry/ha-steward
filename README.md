# Steward - Home Assistant MCP Plugin

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/joeldhenry/ha-steward/actions/workflows/validate.yml/badge.svg)](https://github.com/joeldhenry/ha-steward/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A Model Context Protocol (MCP) server for Home Assistant, designed for modern
Home Assistant configuration and setup.

Steward runs inside Home Assistant as a HACS integration and gives an AI
assistant (Claude, ChatGPT, Gemini, Copilot) the ability to read and repair how
your instance is configured, as well as to control it.

It knows current Home Assistant conventions for naming, areas, floors, labels and
device classes, audits your instance against them, and fixes what it finds.

Connect it by pasting a URL. There is no access token to create, copy or rotate;
authentication goes through Home Assistant's own login screen.

```
https://your-home-assistant/api/steward/mcp
```

## Contents

- [Why another one](#why-another-one)
- [Web authentication](#web-authentication)
- [Permissions](#permissions)
- [The audit](#the-audit)
- [Knowledge resources](#knowledge-resources)
- [Installation](#installation) — [HACS](#1-install-with-hacs), [configure](#2-add-the-integration), [connect](#3-connect-your-ai-client)
- [Tools](#tools)
- [Troubleshooting](#troubleshooting)

---

## Why another one

Home Assistant's built-in MCP Server integration exposes the Assist intent API:
turn things on and off, set a temperature, control media. That is the right
design for a voice assistant and a hard ceiling if you want help building a
smart home. It cannot read an automation, see the error log, or tell you which
integration failed to load.

Servers that do expose the full admin surface stop at the API. That leaves the
assistant capable but uninformed: it will create an automation referencing an
entity filed under the wrong room, because nothing told it what right looks
like.

This one ships the conventions and checks your instance against them.

---

## Web authentication

Home Assistant has been an OAuth 2.1 authorization server since 2025, with
Client ID Metadata Document support, and its auth middleware answers every
unauthenticated request with the RFC 9728 challenge that MCP clients follow:

```
WWW-Authenticate: Bearer resource_metadata="https://your-ha/.well-known/oauth-protected-resource"
```

This integration is a resource server behind that middleware, so the browser
login flow comes for free. In Claude, ChatGPT or any MCP client that supports
remote servers:

1. Add a custom connector
2. Enter `https://your-home-assistant/api/steward/mcp`
3. The client discovers the authorization server and opens a browser
4. Log in to Home Assistant and approve

Access is tied to that Home Assistant account, shows up in the user's token
list, and is revoked by revoking it there.

### claude.ai, Desktop, mobile and Cowork: use your own OAuth client

Adding Steward as a custom connector in the hosted Claude surfaces can fail
with "Automatic client registration isn't supported by Home Assistant", then
ask you to add an OAuth client ID by hand. This happens because Home
Assistant's OAuth metadata does not advertise `token_endpoint_auth_methods_supported`,
one of two fields Claude checks before it will pick client ID metadata over
dynamic registration; without it, Claude tries dynamic registration first, and
Home Assistant does not implement that.

Steward's own metadata document already covers this. In the connector dialog:

1. Choose **Use your own OAuth client**
2. Enter `https://your-home-assistant/api/steward/oauth-client.json` as the OAuth client ID
3. Leave the client secret blank
4. Save, then log in to Home Assistant and approve

The client ID is the same document Claude Code uses, it lists the fixed
callback the hosted surfaces need alongside the loopback ports.

### Claude Code: pin the callback port

Claude Code identifies itself with a client metadata document that registers
`http://localhost/callback` with no port, then listens on a random port. Home
Assistant compares redirect URIs by exact string match, so the login ends with
"Invalid redirect URI". Two specifications disagree here: the client metadata
document draft requires exact matching, while RFC 8252 section 7.3 says an
authorization server "MUST allow any port to be specified at the time of the
request for loopback IP redirect URIs". Home Assistant follows the first,
Claude Code the second.

Steward serves its own metadata document at `/api/steward/oauth-client.json`,
listing fixed loopback ports 8080, 8090 and 8888. Point Claude Code at it and
pin the callback to one of those ports:

```bash
claude mcp add --transport http --scope user \
  --client-id https://your-home-assistant/api/steward/oauth-client.json \
  --callback-port 8080 \
  steward https://your-home-assistant/api/steward/mcp
```

Then `/mcp`, select `steward`, and log in as usual. The document names your
instance's external URL, so **Settings → System → Network** must have an
external HTTPS address set, which any remotely reachable instance already has.

> Your instance must be reachable over HTTPS for a cloud-hosted client to reach
> it — Nabu Casa, a reverse proxy, or a Cloudflare tunnel. Nothing extra is
> needed for a client on the same network.

---

## Permissions

Two layers, both enforced on every call:

| Layer | Effect |
|---|---|
| **Integration options** | Turn off write or destructive operations instance-wide |
| **The connecting account** | Non-administrators are read-only by default. Every service call carries that user's context, so Home Assistant's own entity policies apply and the logbook attributes the change to them. State reads honour the account's per-entity read policy. |

Four access levels, following Home Assistant's own gating:

| Level | Who | Examples |
|---|---|---|
| `read` | any authenticated user | states, services, running a script |
| `sensitive` | administrators | registries, logs, traces, automation logic, templates, `ha_audit` |
| `write` | administrators, if enabled | service calls, registry edits, config edits |
| `destructive` | administrators, if enabled | deleting config, restarting |

`sensitive` exists because Home Assistant treats these reads as admin-only
itself (the error log and registry listings are `@require_admin` in core), and
a tool that exposed them to any household member would widen that.

Gating is per operation. `ha_config` bundles read, write and delete, so a
read-only connection still gets `list` and `get`, and the tool appears with its
unavailable operations named in the description:

```
Not permitted for this connection: create, delete, update.
```

Tools with no usable operation are omitted entirely, so a model never plans
around a capability it will be denied. An audit-only connection for a client
review is one checkbox.

### Rate limiting

The endpoint is reachable from the internet whenever Home Assistant is, and a
model retrying in a loop issues requests far faster than a person. A sliding
window (120 requests per 60s by default, per caller) keeps one misbehaving
client from saturating the instance, answering `429` with `Retry-After` rather
than dropping the connection.

---

## The audit

`ha_audit` reports how far an instance has drifted from current practice,
grouped by rule, each pointing at the document explaining the fix:

```
[warning] entity/wrong-area            11   Entity names an area it is not assigned to
[warning] entity/no-area               90   Primary entity has no area
[info   ] area/not-a-room               2   Area is a grouping, not a room
```

Take `entity/wrong-area`. A two-gang wall switch in the
hallway drives a porch light and a living room lamp. Both entities inherit the
hallway, because that is where the hardware is, so "turn off the living room
lights" misses the lamp:

```
light.courtyard_light  "Courtyard Light" names "Courtyard" but sits in Living Room
  fix: Set this entity's area override to "Courtyard" if that is the room it affects
```

`ha_update_entity` applies that override, and the finding clears.

Rules only fire for domains you would target by room, so a robot vacuum's
per-room settings and a phone's notify entity do not generate noise.

### Rules

31 rules across 13 tags. Filter with `tags=["dashboard"]` or
`tags=["voice","carplay"]` to focus, or `summary_only=true` for counts alone.

| Group | Rules |
|---|---|
| **Areas & structure** | `area/not-a-room`, `area/naming`, `area/no-floors`, `area/empty`, `device/no-area`, `entity/no-area`, `entity/wrong-area` |
| **Naming** | `entity/no-name`, `entity/name-repeats-area`, `entity/name-repeats-device`, `entity/raw-identifier` |
| **Types & classes** | `sensor/missing-state-class`, `sensor/missing-device-class`, `entity/switch-as-x` |
| **Health** | `entity/unavailable`, `entity/orphaned`, `device/offline`, `integration/not-loaded` |
| **Automations** | `automation/broken-reference`, `automation/device-trigger`, `automation/never-triggered`, `automation/disabled` |
| **Dashboards** | `dashboard/broken-reference`, `dashboard/auto-generated-only` |
| **Voice, CarPlay & Watch** | `voice/duplicate-name`, `voice/exposed-without-area`, `voice/unqueryable-binary-sensor`, `voice/diagnostic-exposed`, `companion/no-icon` |
| **Bridges & duplicates** | `bridge/duplicate-device`, `entity/duplicate-function` |

Every finding carries a `why` explaining what breaks if it is left alone, so the
model can explain the problem to the user instead of reciting a rule id.

### The default dashboard is the area registry

Most people never build a dashboard. Home Assistant generates the Overview from
the area registry, so for them the dashboard is the area data. That is why the
area rules carry a `dashboard` tag and why the audit puts them first: fixing
area assignment is what improves their Overview.

`dashboard/auto-generated-only` says so explicitly, and counts how many
controllable entities are in no room and therefore ungrouped.

### Voice, CarPlay and the Watch

Assist, Siri, CarPlay and the Watch all resolve entities by spoken or displayed
name within an area, so a name that is only untidy on a dashboard is unusable
there:

```
voice/duplicate-name   2 entities named "Ceiling Light" in Living Room: light.dup_a, light.dup_b
  fix: Rename them so each says what it controls, or stop exposing the ones
       nobody asks for by voice

voice/exposed-without-area   "Floating Lamp" is voice-controllable but in no room
  fix: Assign it to the room it affects
```

These read Home Assistant's exposure settings, so they only flag entities an
assistant can reach.

### Matter and bridges

`bridge/duplicate-device` finds one physical device exposed by two integrations,
natively and through Matter, Matterbridge or HomeKit. Both work, both appear
in every picker, and the bridged copy usually supports fewer features. Nothing
in Home Assistant flags this, because each integration is behaving correctly on
its own.

## Knowledge resources

Read on demand, so they cost nothing until asked for:

| Resource | Covers |
|---|---|
| `ha://knowledge/naming` | How names compose from device + entity, what belongs in an entity name, why renaming breaks references |
| `ha://knowledge/areas` | Areas vs floors vs labels vs categories, and assigning an entity to the room it *affects* |
| `ha://knowledge/device-types` | Switch as X, duplicate entities, and the `device_class`/`state_class` rules that decide whether statistics exist |
| `ha://knowledge/automations` | Targeting entities and areas rather than device IDs, silent reference breakage, trigger IDs, modes, and when something should be a scene |
| `ha://knowledge/companion` | How Assist, Siri, CarPlay and the Watch resolve entities by name within an area, exposure, aliases, and domain/device-class mismatches |
| `ha://knowledge/bridges` | Why a device bridged through Matter or HomeKit while also integrated natively appears twice, and how to resolve it |
| `ha://knowledge/onboarding` | The order to fix an inherited instance, and what to do before a handover |

Every rule cites the document that explains it, and each document is written
against the Home Assistant documentation it derives from. Where the official
guidance appears to disagree with itself (the voice docs recommend saying
"living room lamp" while the developer docs say an entity name should not
contain its area), the document explains how both hold at once instead of
picking a side.

## Prompts

`onboard-instance` audits an unfamiliar install and works the findings in a safe
order. `fix-areas` targets the structural rules and proposes per-entity
overrides. Both present changes for approval before touching anything.

---

## Installation

**Requirements**

- Home Assistant **2025.6** or newer
- [HACS](https://hacs.xyz) installed
- For a cloud-hosted AI client to reach it, your instance must be reachable over
  HTTPS: Nabu Casa Cloud, a reverse proxy, or a Cloudflare tunnel. Nothing
  extra is needed for a client on the same network.

### 1. Install with HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=joeldhenry&repository=ha-steward&category=integration)

Or add it by hand:

1. Open **HACS** in the Home Assistant sidebar.
2. Click the **⋮** menu, top right → **Custom repositories**.
3. Paste `https://github.com/joeldhenry/ha-steward` into **Repository**.
4. Set **Type** to **Integration**, then click **Add**.
5. Close the dialog, search HACS for **Steward**, and open it.
6. Click **Download**, then **Download** again to confirm.
7. Restart Home Assistant: **Settings → System → ⋮ (top right) → Restart**.

> HACS downloads the files, but Home Assistant only loads a new integration at
> startup. Skipping the restart is the most common reason Steward does not appear
> in the next step.

### 2. Add the integration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=steward)

1. Go to **Settings → Devices & services**.
2. Click **+ Add integration**, bottom right.
3. Search for **Steward** and select it.
4. Choose the permissions (see [Permissions](#permissions)) and click **Submit**.

The endpoint is live immediately at `/api/steward/mcp`. There is nothing to
restart and no token to generate.

To change permissions later: **Settings → Devices & services → Steward →
Configure**.

### 3. Connect your AI client

Your MCP endpoint is your Home Assistant URL plus `/api/steward/mcp`:

```
https://homeassistant.example.com/api/steward/mcp
```

**Claude** (web, desktop, or Claude Code)
1. **Settings → Connectors → Add custom connector**
2. Paste the URL above and click **Add**
3. Claude discovers the authorization server and opens a browser
4. Log in to Home Assistant and approve access

**ChatGPT**: **Settings → Connectors → Create**, then paste the same URL.

**Any other MCP client**: give it the URL. Clients that support remote MCP
servers discover everything else from it.

Access is tied to the Home Assistant account that logged in. It appears in that
user's profile under security, and revoking it there disconnects the client.

## Tools

- Conventions: `ha_audit`
- Entities: `ha_get_states` (filter by domain, area, device, label or name),
  `ha_get_state`, `ha_describe_entity`, `ha_call_service`, `ha_get_services`
- Registries: `ha_get_devices`, `ha_update_device`, `ha_remove_device`,
  `ha_get_entity_registry`, `ha_update_entity`, `ha_remove_entity`, `ha_get_areas`,
  `ha_manage_area`, `ha_get_floors`, `ha_create_floor`, `ha_get_labels`,
  `ha_manage_label`
- Configuration: `ha_config` reads and writes automation, script and scene
  config, meaning the triggers, conditions and actions themselves. Home Assistant
  validates before saving and reloads the domain afterwards, so a bad config is
  rejected before it is written. `ha_validate_config` checks a block of triggers,
  conditions or actions without saving; `ha_check_config` validates the whole
  YAML configuration.
- Helpers: `ha_helper` for input_boolean, input_number, input_select,
  input_text, input_datetime, counter, timer and schedule
- Dashboards: `ha_dashboard` lists, reads, saves, creates and deletes Lovelace
  dashboards and lists custom resources
- Running things: `ha_get_automations`, `ha_toggle_automation`,
  `ha_trigger_automation`, `ha_run_script`, `ha_activate_scene`, `ha_assist`
- Diagnostics: `ha_trace`, `ha_error_log`, `ha_history`, `ha_statistics`,
  `ha_logbook`, `ha_repairs`
- System: `ha_get_config`, `ha_render_template`, `ha_get_config_entries`,
  `ha_config_entry` (reload, unload, set up, remove), `ha_energy`, `ha_backup`,
  `ha_reload`, `ha_restart`

Anything Home Assistant exposes only as a WebSocket command (helpers, dashboards,
energy preferences, backups, repairs, Assist) runs through the same command
handlers the frontend uses, with the caller's own account, so validation and
admin checks are Home Assistant's rather than a second copy.

Output is bounded by default. `ha_get_states` returns identifying fields with
attributes opt-in, `ha_get_services` filters by domain, and `ha_history` drops
attributes and insignificant changes, because an unfiltered call across a large
instance exhausts a context window before it answers anything.

`ha_config` replaces rather than merges. Home Assistant's own config API
merges an update into the existing entry, which leaves a trigger or condition
behind after it has been removed. Read with `get`, edit, and send the
whole object back.

---

## Troubleshooting

**Steward does not appear under "Add integration"**
Home Assistant was not restarted after the HACS download. Restart, then hard
refresh the browser.

**The client says it cannot reach the server**
Open `https://your-home-assistant/api/steward/mcp` in a browser. A `401
Unauthorized` is correct: the endpoint requires a login, and seeing it proves
the integration is loaded and reachable. A `404` means the integration is not
set up; anything else is a networking or proxy problem.

**"Invalid redirect URI" after logging in**
Claude Code's default client registers a portless loopback callback that Home
Assistant will not match. Use the `--client-id` and `--callback-port` form
under [Claude Code: pin the callback port](#claude-code-pin-the-callback-port).
Confirm `https://your-home-assistant/api/steward/oauth-client.json` returns a
JSON document whose `client_id` is that same URL; if it returns a 503, set an
external URL under **Settings → System → Network**.

**The browser login never appears**
The client needs to reach your instance over HTTPS with a valid certificate, and
the discovery documents must be reachable. Check that
`https://your-home-assistant/.well-known/oauth-authorization-server` returns
JSON. If your reverse proxy blocks `/.well-known/`, MCP authentication cannot
work.

**Everything is read-only**
Either write operations are disabled in the integration options, or the account
you logged in with is not a Home Assistant administrator. Both are shown in the
`initialize` response, and the error text names which one applies.

**Tools are missing from the list**
Tools the current connection may not use are deliberately hidden, so a model
does not plan around a capability it will be denied. Check **Settings → Devices
& services → Steward → Configure**.

## Development

See [tests/README.md](tests/README.md). The tests boot a real Home Assistant
core and exercise the protocol, the audit, the remediation loop and the
permission model.

## License

MIT © [Joel Henry](https://joelhenry.me) / Bleep Bloop Technology
