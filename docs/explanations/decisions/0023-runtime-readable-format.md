# 23. Make readable format a runtime setting keyed by Device

Date: 2026-08-18

## Status

Accepted

## Context

In ophyd v1 a `Component`'s `kind` could be changed at runtime, so one Device could serve
several techniques: a monochromator's energy is configuration for one and a hinted read for
another. `StandardReadable` had no equivalent: `add_readables` appended bound methods to
tuples that did not record which device each came from, so nothing could be removed or
re-formatted (#1394).

In #1395 reviewers would not have areaDetector plugins registered automatically, as a
detector carries far more plugins than are wired into its chain. Opting a plugin in after
construction needs the same primitive.

Three designs were considered:

- **Chain parsing**, registering what the plugin graph wires up. Rejected as too large, and
  it fails once plugins cross IOCs.
- **One registry for formats and logic objects.** Rejected: formats are keyed by child,
  unbounded and merged by union; logics are keyed by role, one per role, and a conflict is
  an error. Changing a format alters `describe()`; changing a logic alters the protocols
  the Device satisfies.
- **A format registry keyed by device**, leaving logic objects alone. Chosen.

## Decision

### The registry is a dict keyed by device

`StandardReadable` maps each registered child to its format, in registration order, and
the verbs read it on every call. `set_readable_format(device, format)` sets one entry, and
`None` removes it.

- `Device` has no `__eq__`, and `DeviceVector` and `DeviceMap` hash by `id()`, so keying by
  `Device` is identity keying.
- A tuple of pairs was tried for immutability, but rebuilding it per registration made
  construction O(n²): 77 ms for 2000 signals against 13 ms for the dict.
- It is a `cached_property`, because Devices register children before
  `super().__init__()`, which would discard anything `__init__` assigned.
- Only a `SignalR` takes a signal format, checked on registration, so the verbs get typed
  entries.
- Registering a device twice replaces its format; the old double contribution was an
  accident.
- The deprecated `ConfigSignal` and `HintedSignal` markers go: they compared equal to their
  target, which only worked while `add_readables` matched at registration.

### Runtime changes can be undone, and the baseline is sealed by a metaclass

@oliwenmandiamond pointed out that a runtime change makes the class definition misleading,
and proposed either making class-declared formats immutable unless opted out, or a separate
`StandardDynamicReadable`. Both were rejected because they block #1394's case: the
monochromator *declares* `energy` as configuration, and switching technique would need a
class change. @jwlodek added that ophyd v1 has always been mutable and NSLS-II codebases
rely on it.

Instead, `reset_readable_formats` puts a Device back to what its class declared, so a plan
can undo a retune without recording what it changed. Its baseline is the class, so it
discards a stored technique too.

Formats are declared in annotations, by registration before `super().__init__()`, and by
registration after it. A metaclass `__call__` is the only point after all three; a
snapshot at the end of `__init__` misses the third. `Device` already has a metaclass, so
this adds no machinery.

### Format changes apply between runs, not within one

A change part way through a run would make `describe()` disagree with the descriptor
emitted at its start. This is documented rather than enforced, as a Device cannot see run
boundaries.

### Formats are stored with settings, under a reserved key

A technique change wants values and formats together, so they share one file and one
`apply_settings`. Values stay flat, and one reserved key holds the format changes:

```yaml
energy: 7.0
<READABLE_FORMATS>:
  <ROOT_DEVICE>:
    energy: HINTED_SIGNAL
    temperature: null
```

- No version marker: a file without the key changes no formats. An unknown reserved key, from a newer
  version, is warned about and dropped, so the rest of the file still loads.
- `<` cannot begin a Python identifier, so no attribute path collides with a reserved key.
  Unlike `*FORMATS*` it needs no YAML quoting, and `<ROOT_DEVICE>` avoids the `? '' :` form
  PyYAML emits for an empty key.
- Formats are keyed by owner, then child, because one child can be registered on two
  owners with different formats. This needs no "direct child" rule, so `driver.acquire_time`
  and `DeviceVector` elements work.
- A config-only `store_settings` still stores formats, as they decide which signals are
  configuration.

### Only changes are stored, and applying resets to the class defaults first

`walk_readable_formats` stores how each `StandardReadable` differs from its construction,
and `apply_readable_formats` resets the tree to its class defaults, then applies that.
Rejected:

- **Store everything, apply by replacing**: an old file silently unregisters a signal added
  in a later version, and undoes a release's change of default.
- **Store everything, apply by merging**: cannot return from technique B to A, as what B
  changed and A does not mention stays.

Every path is resolved before anything changes, so a bad path cannot half apply.
`Settings.partition` copies the formats to both halves, because plans such as
`apply_panda_settings` apply only the halves. Formats go after values, so a failed write
leaves them untouched.

## Consequences

- A Device can switch, save and restore techniques at runtime, closing #1394.
- `add_readables` keeps working with "set" semantics, but is deprecated in favour of
  `set_readable_format`, which says what it does.
- A runtime change to a device registered outside its owner has no stable path, so
  `walk_readable_formats` warns and skips it.
