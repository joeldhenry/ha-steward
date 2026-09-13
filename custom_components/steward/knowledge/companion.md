# Voice, CarPlay and the Watch

Assist, Siri, the CarPlay screen and the Apple Watch all read the same registry
data, and all of them resolve an entity by its **name within an area**. A name
that is merely untidy on a dashboard becomes unusable here, because there is no
list to scan and no way to hover.

## Exposure is deliberate

Entities are not automatically available to voice. They are exposed under
**Settings → Voice assistants → Expose**, deliberately, so that locks and garage
doors cannot be operated by accident.

Two consequences worth auditing:

- An entity someone expects to control by voice may simply not be exposed.
- Diagnostic entities — signal strength, firmware version, battery voltage —
  are worth *un*-exposing. Nobody asks an assistant about them, and each one is
  another candidate for a misheard match.

## Naming for speech

The Home Assistant guidance for voice is to name entities the way a person would
say them: `<area> <descriptor> <what it is>`. "Living room lamp" works;
"Tuya Light Controller 0E54B1 Light 1" does not.

This sits slightly differently from the naming rules an integration follows —
see `ha://knowledge/naming`. The reconciliation is that Home Assistant composes
the spoken name from the **device name plus the entity name**, and users
generally name the *device* after where it is. The composed result naturally
reads as "Living room lamp", which is correct for voice.

What matters far more than style:

- **No duplicates within an area.** Two entities named "Ceiling Light" in the
  living room give an assistant nothing to choose between, so the request fails
  or acts on the wrong one. In CarPlay and on the Watch, the two entries are
  visually identical.
- **Every controllable entity has an area.** "Turn off the kitchen lights"
  resolves through the area registry. An entity in no area cannot be reached
  that way at all, however well it is named.

## Aliases

When people in the house say a thing differently — "TV" and "television", or a
second language — add each variation as an alias on the entity rather than
renaming it. Areas and floors take aliases too.

## The domain has to match the request

A voice command fails when the domain or device class does not match the verb.
You cannot ask Assist to *open* the main valve if the relay driving it is still
a `switch`; a switch can only be turned on. A `binary_sensor` with no
`device_class` cannot be queried naturally, because nothing tells the assistant
whether "on" means open, wet, or occupied.

This is the same fix as `ha://knowledge/device-types`: present the entity as
what it actually is, and both voice and the dashboard improve together.

## CarPlay and the Watch specifically

Both render a compact list of tiles, grouped by area, drawn from scenes,
scripts and controllable entities. Two things make that list usable:

- **An icon on every scene and script.** Without one they all show the same
  default glyph, which defeats the purpose of a glanceable list.
- **Short, distinct names.** There is far less room than on a dashboard, and
  long names are truncated.

Because both surfaces group by area, everything in
`ha://knowledge/areas` applies here too — an entity in the wrong room appears
under the wrong heading in the car.

References:
<https://www.home-assistant.io/voice_control/best_practices/>,
<https://www.home-assistant.io/voice_control/voice_remote_expose_devices/>
