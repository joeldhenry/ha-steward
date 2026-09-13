# Areas, floors, labels and categories

Four organisational tools, each with a distinct job. Using the wrong one is the
most common structural mistake in a Home Assistant install.

| Tool | Represents | Assigned to |
|---|---|---|
| **Area** | A physical room or space | Devices and entities |
| **Floor** | A level of the building, grouping areas | Areas only |
| **Label** | A cross-cutting tag, any dimension you like | Areas, devices, entities, automations, scripts, scenes, helpers |
| **Category** | A per-page grouping for UI filtering | Items within one table |

## Areas are physical, and only physical

An area is a room. "All House", "Integrations", "Batteries" and "Security" are
not rooms — they are labels. Putting them in the area registry corrupts the one
structure that voice control and area-targeted automations depend on.

## Floors group areas, not devices

Devices and entities cannot be assigned to a floor directly; they inherit it
from their area. An install with more than one level should define floors, or
"turn off everything upstairs" has nothing to resolve against.

## Entities inherit their device's area — and can override it

> When you assign a device to an area, all its entities inherit that area. You
> can override this for individual entities.

This override is the correct fix for hardware whose functions are not all in one
place. The official example: keep a smart plug's sensor entities in the living
room while assigning its switch entity to the kitchen.

### The multi-gang switch case

A two-gang wall switch in the hallway drives a porch light and a living room
lamp. The **device** lives in the Hallway. But:

- the gang controlling the porch light should be overridden to **Porch**
- the gang controlling the lamp should be overridden to **Living Room**

Assign each entity to the area it **affects**, not the area the hardware sits
in. Otherwise "turn off the living room lights" misses the lamp, and "turn off
the hallway lights" kills the porch.

Diagnostic and configuration entities (signal strength, firmware, LED mode) can
stay with the device; nobody targets them by room.

Reference: <https://www.home-assistant.io/docs/organizing/>
