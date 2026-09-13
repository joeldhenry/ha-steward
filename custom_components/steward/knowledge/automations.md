# Automations, scripts and scenes

## Target entities, not devices

The automation editor offers device triggers first, and they read well: "when
the hallway motion sensor detects motion". They are also the most common cause
of an automation that silently stops working.

A device trigger stores a `device_id`: an internal identifier generated when the
device is added. Remove a device and add it back and it gets a new `device_id`,
while its `entity_id` stays the same. Re-pair a flaky Zigbee
sensor and every device-based automation referencing it is now pointing at
nothing. Nothing warns you; the automation never fires again.

Entity triggers survive re-pairing, are readable in YAML, and can be shared
between instances. Prefer:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.hallway_motion
    to: "on"
```

over the device equivalent. The same applies to conditions and actions:
`target: {entity_id: ...}` or `target: {area_id: ...}` rather than `device_id`.

## Target areas where you mean a room

Listing eight individual lights is brittle: add a ninth and the automation is
silently incomplete. Targeting the area covers whatever is in the room now:

```yaml
actions:
  - action: light.turn_off
    target:
      area_id: living_room
```

This is another reason area assignment is worth fixing first: it makes
automations shorter and self-maintaining.

## References break silently

An action pointing at an entity that no longer exists does not raise an error
that anyone sees. The automation runs, the step does nothing, and the only
symptom is that the lights did not come on.

Renaming an entity has the same effect, because nothing rewrites the references
for you. Before renaming, search automations, scripts, scenes and dashboards for
the old ID and change them in the same pass.

## Trigger IDs

Any trigger can carry an `id`, which conditions and actions can then branch on.
This is how one automation handles several triggers without becoming several
automations:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.front_door
    to: "on"
    id: opened
  - trigger: state
    entity_id: binary_sensor.front_door
    to: "off"
    id: closed
```

## Modes

`mode` decides what happens when an automation triggers while already running:

- `single` (default) — ignore the new trigger, and warn in the log
- `restart` — abandon the current run and start again. Right for
  motion-activated lights, where a fresh trigger should extend the timeout
- `queued` — run them in order, one at a time. Right for a control loop that
  must not overlap itself
- `parallel` — run concurrently

A `single`-mode automation with a `delay` and a frequently-firing trigger will
fill the log with warnings about overlapping runs. That is usually a sign the
mode is wrong, not the trigger.

## Scenes are the right unit for "set this room up"

A scene captures a set of entity states and applies them together. Using one in
an automation is shorter than a dozen `turn_on` actions, it is editable in the
UI without touching the automation, and it is reusable from a dashboard, a voice
command, CarPlay or the Watch.

If an automation sets more than a few entities to fixed values, it usually
wants to be a scene the automation activates.

References:
<https://www.home-assistant.io/docs/automation/trigger/>,
<https://www.home-assistant.io/docs/automation/modes/>,
<https://community.home-assistant.io/t/why-and-how-to-avoid-device-ids-in-automations-and-scripts/605517>
