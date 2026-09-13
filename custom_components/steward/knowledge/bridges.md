# Bridges, Matter and duplicate devices

## The problem nothing warns you about

Matter, Matterbridge, HomeKit bridges and vendor hubs all re-expose devices that
Home Assistant may already have natively. Add a Hue bridge over Matter while the
Hue integration is already running and every bulb exists twice: two devices, two
sets of entities, both working.

Nothing flags this, because each integration is behaving correctly on its own.
The cost shows up everywhere else:

- Two entries in every entity picker, with nothing to distinguish them
- Duplicate tiles on dashboards and in CarPlay
- A voice assistant with two equally good matches for "the kitchen light"
- Automations that target one copy while a person uses the other

## Prefer the native integration

Home Assistant's own guidance on the Hue bridge is blunt: Matter supports only a
limited set of features, the native integration supports many more, and bridging
Hue into Home Assistant over Matter means **you would gain nothing and lose
features**.

That generalises. A bridge speaks a lowest-common-denominator protocol, so the
bridged copy is almost always the poorer one:

| | Native integration | Bridged copy |
|---|---|---|
| Features | Everything the vendor exposes — scenes, effects, transitions, diagnostics | Basic on/off, brightness, colour |
| Updates | Follows the vendor's API | Limited to what the bridge maps |
| Diagnostics | Usually present | Usually absent |

So the rule of thumb is: **use the native integration where one exists, and
reserve bridges for devices that have none.**

## Where bridges genuinely help

Bridges are the right answer when there is no native integration, or when the
household needs the vendor's own app to keep working alongside Home Assistant.
SwitchBot, Aqara, IKEA Dirigera and similar hubs exist for exactly that.

Matterbridge is a common case: it presents non-Matter devices to Matter
controllers, which is useful for exposing Home Assistant devices *to* Apple
Home. Exposing them back into the same Home Assistant instance is the
duplication described above.

## Resolving a duplicate

Decide which copy is authoritative, then remove the other properly:

1. Identify which integration provides the richer entity — compare supported
   features, not entity counts.
2. Check what references the copy you are removing. Automations, scripts,
   scenes and dashboards all pin entity IDs.
3. **Disable or remove the device**, rather than hiding entities one at a time.
   Hiding leaves the entities live and still matchable by voice.
4. If the surviving entity has the uglier ID because the duplicate claimed the
   good one first, free the ID by deleting the removed entity's registry entry,
   then rename.

## Bridge devices themselves

A bridge appears as a device of its own, with the bridged devices beneath it.
The bridge belongs in the room the hardware sits in; **the devices it bridges
belong in the rooms they are actually in**, which is rarely the same place. This
is the same per-entity area override described in `ha://knowledge/areas`.

Reference: <https://www.home-assistant.io/integrations/matter/>
