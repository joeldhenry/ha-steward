# Correcting device types

An integration reports what a device *is* electrically, which is often not what
it *does*. A relay driving a ceiling light is reported as a `switch`, so it gets
a toggle instead of a light card, is missed by "turn off all the lights", and is
invisible to anything that targets the `light` domain.

## Switch as X

The **Switch as X** helper re-presents a switch entity as a different domain:

| Target | Use for |
|---|---|
| `light` | Relays and plugs driving light fixtures |
| `fan` | Relays driving fans |
| `cover` | Relays driving blinds, garage doors, gates |
| `lock` | Relays driving strikes or latches |
| `valve` | Relays driving water or gas valves |
| `siren` | Relays driving sirens |

Create it under **Settings → Devices & services → Helpers → Create helper →
Switch as X**, choosing the switch entity and the target type.

The original switch entity is hidden, not deleted: it stays available to
anything referencing it, but disappears from pickers so the new entity is the
obvious choice. The new entity joins the original's device and area.

Prefer a native integration option where one exists. Many Zigbee and ESPHome
devices can be told directly that a relay is a light, which is cleaner than
layering a helper on top.

## Sensor classes

Three attributes decide whether a sensor is usable beyond a raw number:

- **`device_class`** — what the reading *is* (`power`, `energy`, `temperature`).
  Drives icon, colour, and unit validation.
- **`state_class`** — how it behaves over time. This is what creates long-term
  statistics:
  - `measurement` — a value that goes up and down (power, temperature)
  - `total_increasing` — a counter that only rises and resets to zero (an energy
    meter)
  - `total` — a counter that can also decrease (net import/export)
- **`unit_of_measurement`** — must be consistent with the device class.

A sensor with no `state_class` generates no long-term statistics. Its history
is purged with everything else (10 days by default) and it cannot appear on the
Energy dashboard or be queried for monthly totals. For an energy sensor this is
usually a defect, not a choice.

The Energy dashboard specifically requires `device_class: energy` with
`state_class: total_increasing` (or `total`), in Wh/kWh/MWh.

## One function, two entities

Some integrations expose the same physical function twice: a relay as both a
`switch` and a `light`, or a climate unit as both `climate` and a set of
`select` helpers. Leaving both visible means a person or a model has two ways to
do one thing and no way to tell which is right.

Pick the entity that best describes the function, and hide the other. Hiding
keeps existing references working; disabling stops it being updated at all and
will break anything still pointing at it.

References:
<https://www.home-assistant.io/integrations/switch_as_x/>,
<https://www.home-assistant.io/integrations/sensor/>
