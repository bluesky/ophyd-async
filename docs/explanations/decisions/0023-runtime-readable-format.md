# 23. Make readable format a runtime setting keyed by Device

Date: 2026-08-18

## Status

Accepted

## Context

In ophyd v1 a `Component`'s `kind` could be changed at runtime, so one Device could serve
several techniques: a monochromator's energy is configuration for one and a hinted read for
another. `StandardReadable` could not do this, as `add_readables` appended bound methods to
tuples that did not record which device each came from. The same primitive is needed to
opt an areaDetector plugin in after construction, rather than registering every plugin a
detector carries.

Rejected alternatives:

- **Parsing the plugin chain** to register what it wires up: too large, and it fails once
  plugins cross IOCs.
- **One registry for formats and logic objects**: formats are keyed by child and merged by
  union, logics are one per role and conflict on overlap, so they share no rules.

## Decision

### The registry is a dict keyed by device

`StandardReadable` maps each registered child to its format, and the verbs read it on
every call.

- `Device` has no `__eq__`, and `DeviceVector` and `DeviceMap` hash by `id()`, so keying
  by `Device` is identity keying.
- A tuple of pairs was rejected: rebuilding it per registration made construction O(n²).
- It is a `cached_property`, because Devices register children before
  `super().__init__()`, which would discard anything `__init__` assigned.
- Registering a device twice replaces its format rather than adding a second
  contribution.
- The `ConfigSignal` and `HintedSignal` markers are removed: they compared equal to their
  target, which only worked while `add_readables` matched at registration.

### Runtime changes can be undone to a baseline sealed by a metaclass

Making class-declared formats immutable, or adding a separate `StandardDynamicReadable`,
was rejected: switching technique would then need a class change, and ophyd v1 users rely
on mutability. Instead `reset_readable_formats` returns a Device to what it declared, so a
plan can undo a change without recording it.

Formats are declared in annotations and by registration before and after
`super().__init__()`. A metaclass `__call__` is the only point after all three, and
`Device` already has a metaclass.

The snapshot is per instance, so a parent's `__init__` that sets a format on a nested
`StandardReadable` is a runtime change of that child, not a default: it is stored in settings
and dropped by `reset_readable_formats`.

### Format changes apply between runs, not within one

A change part way through a run would make `describe()` disagree with the descriptor
emitted at its start. This is documented rather than enforced, as a Device cannot see run
boundaries.

### Formats are stored with the values, but are not Settings

A technique change wants values and formats together, so they share one file. Values stay
flat, and one reserved key holds the format changes as `owner:child`, where `owner` is the
path of the `StandardReadable` that owns the child, and `child` is its path from the owner:

```yaml
energy: 7.0
<READABLE_FORMATS>:
  energy: HINTED_SIGNAL
  temperature: null
  mirror:pitch: CONFIG_SIGNAL
```

- `<` cannot begin a Python identifier, so no attribute path collides with a reserved key,
  and it needs no YAML quoting. A root-owned child has no `owner:` prefix, which avoids the
  `? '' :` form PyYAML emits for an empty key.
- A flat key keeps the section one level deep, like the values, and `:` cannot appear in
  a dotted path.
- Keying by owner allows one child registered on two owners with different formats, and
  reaches nested children such as `driver.acquire_time` and `DeviceVector` elements.
- A child outside its owner has no path from it, so it is warned about and not stored.
- A config-only `store_snapshot` still stores formats, as they decide which signals are
  configuration.
- A file without the key leaves formats alone, so no version marker is needed.

### Only changes are stored, and applying resets to the class defaults first

Rejected:

- **Store every format, apply by replacing the registry with the stored one**: a file
  saved by an older version would unregister a signal added to the class since, and undo
  any change a later release made to a default format.
- **Store every format, apply by merging it into the registry**: loading a file only sets
  the children it lists. If one technique's settings opt in a detector plugin, a file saved
  for a technique without that plugin does not list it, so loading that file afterwards
  leaves the plugin registered.

Formats are applied after values, so a failed value write leaves them untouched.

### A DeviceSnapshot holds typed values and formats, and Settings stays values only

`Settings` stays a mapping of signals to values. Giving it formats made `|`, `partition`
and `apply_settings_if_different` need rules for them: whether a sub-Device's formats may
merge when applying resets the whole tree, and which half of a partition carries them.
Formats are not values, so they are not in it.

A `DeviceSnapshot` is a Device plus its values by path and its format changes by
`(owner path, child path)`, so one file is one Device state. The `retrieve_snapshot` plan
splits the stored layout into those before building it, so core knows nothing of the file
format and a bad format string raises when retrieved. Construction resolves
the paths against the Device, so a stale path raises one `NameError` before anything is
written. `settings` and `readable_formats` return new, typed copies, so neither is a live
view and neither can be given paths relative to the wrong root. There is no combined apply
plan: callers use `apply_settings` and `apply_readable_formats`, where `None` formats leave
them alone. `store_settings` and `retrieve_settings` are deprecated in favour of the
snapshot plans, and delegate to them.

## Consequences

- A Device can switch, save and restore techniques at runtime.
- `add_readables` is deprecated in favour of `set_readable_format`.
- A runtime change to a device registered outside its owner has no stable path, so it is
  not stored.
