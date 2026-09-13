# Entity and device naming

Home Assistant composes a display name from two parts: the **device name** and the
**entity name**. An integration that sets `has_entity_name` (mandatory for new
integrations) makes this composition automatic:

```
friendly_name = "<device name> <entity name>"
entity_id     = <domain>.<device name>_<entity name>
```

## Rules

1. **The entity name describes only the data point.** "Battery", "Power usage",
   "Temperature". Not what device it belongs to, not where it is.
2. **Never repeat the device name in the entity name.** A device named
   "Nightlight" with an entity named "Battery" produces `sensor.nightlight_battery`.
   Naming the entity "Nightlight battery" produces
   `sensor.nightlight_nightlight_battery`.
3. **Never put the area in the name.** Area membership is structured data; it is
   already available for targeting and display. "Kitchen Ceiling Light" in the
   Kitchen area is redundant, and it breaks if the device moves.
4. **Never include the entity type.** `light.kitchen_light` and
   `sensor.outside_temperature_sensor` stutter. The domain already says it.
5. **The primary feature of a device has no entity name at all.** A smart bulb's
   light entity is just the device: `light.nightlight`. In the UI this is shown
   as the device name alone.
6. **Capitalise as a sentence.** "Power usage", not "Power Usage".

## Why it matters

Beyond tidiness, the composed name is what voice assistants and LLMs match
against. "Turn on the kitchen light" resolves cleanly when the area is Kitchen
and the entity is a light; it resolves ambiguously when six entities all contain
the word "kitchen" in their names.

## Where this and the voice guidance appear to disagree

Home Assistant's voice documentation recommends naming things the way a person
would say them — `<area> <descriptor>`, so "Living room lamp". Read beside rule
2 above, that looks contradictory.

It is not, because they describe different halves of the same name. Home
Assistant composes:

```
friendly_name = "<device name>" + "<entity name>"
```

The rules above govern the **entity** half, which an integration sets. Users
name the **device**, and usually name it after where it is. A device called
"Living Room Lamp" with a primary entity named `None` composes to exactly the
"Living room lamp" the voice guidance asks for. Both are satisfied at once.

What is genuinely redundant is the area appearing **twice** — a device named
"Living Room Lamp" whose entity is also named "Living room", or an entity name
that repeats a device name already containing the room.

So treat a composed name that mentions its own area as a matter of taste rather
than a defect. What is never acceptable is **two entities with the same name in
the same area**: a person can tell them apart from context, and a voice
assistant cannot. See `ha://knowledge/companion`.

## Renaming safely

Renaming an entity in the registry changes its `entity_id`. Automations,
scripts, scenes and dashboards that reference the old ID **are not updated
automatically**. Search for the old ID before renaming, and update references in
the same change.

Reference: <https://developers.home-assistant.io/docs/core/entity/>
