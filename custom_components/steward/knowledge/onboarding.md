# Onboarding an existing Home Assistant instance

A running instance that has grown organically usually has the same handful of
structural problems. Work in this order; each step makes the next one cheaper.

## 1. Fix the area registry first

Everything else targets areas, so correct them before touching entities.

- One area per physical room. Delete or convert anything that is not a room
  ("All House", "Integrations", "Security"); those are labels.
- Consistent capitalisation. `staircase` and `Front door` should be `Staircase`
  and `Front Door`.
- Fix spelling. An area named `Intergrations` will be matched literally by
  anything that targets it by name.
- Define floors if the building has more than one level.

## 2. Assign every physical device to an area

Filter the device list by "no area". Ignore devices with `entry_type: service`
(Sun, Backup, HACS, the weather provider); those are not in a room and never
will be.

## 3. Override entity areas where function and hardware diverge

For any device whose entities affect more than one room (multi-gang switches,
multi-channel relays, a plug whose sensors and switch belong to different
places), override the area per entity. See `ha://knowledge/areas`.

## 4. Correct device types

Switches that drive lights, fans or covers should be re-presented in the right
domain. See `ha://knowledge/device-types`.

## 5. Resolve duplicate representations

Where one function appears as two entities, hide the redundant one.

## 6. Clean up the dead

Entities stuck `unavailable` or `unknown` are usually removed hardware or a
broken integration. Each one is a candidate for a wrong answer. Remove the
integration, or disable the entities.

## 7. Fix sensor classes last

By this point the instance is navigable. Sweep for energy sensors missing
`state_class` and power sensors missing `device_class`, since those silently
break statistics and the Energy dashboard.

## Renaming is not free

Changing an `entity_id` breaks every automation, script, scene and dashboard
that names it. Before a bulk rename, search the config for each old ID and
update the references in the same pass.

## Order of operations for a client handover

1. Take a backup.
2. Run the audit and agree which findings are in scope.
3. Fix areas and floors.
4. Fix device and entity area assignment.
5. Fix device types and duplicates.
6. Fix sensor classes.
7. Re-run the audit and hand over the diff.
