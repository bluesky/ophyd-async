# 21. Make readable format a runtime setting keyed by Device

Date: 2026-08-18

## Status

Accepted

## Context

In ophyd v1 a `Component`'s `kind` attribute could be changed at runtime, so a beamline
could reuse one Device across techniques: a monochromator's energy signal is
configuration for a fixed-energy technique and a hinted read for one that scans it.

`StandardReadable` had no equivalent. `add_readables(devices, format)` appended bound
methods into four tuples:

```python
case StandardReadableFormat.CONFIG_SIGNAL:
    self._describe_config_funcs += (signal.describe,)
    self._read_config_funcs += (signal.read,)
```

Once appended, the tuples no longer recorded which device a contribution came from, so
nothing could be found, removed or re-formatted afterwards. The only ways to change what
a device reported were to edit its class definition or to keep two near-identical Device
classes differing in one signal's format. This is issue #1394.

The same gap showed up from the other direction in #1395. `StandardDetector` did not
inherit `StandardReadable` and had its own `add_config_signals` instead, so detectors and
every other Device disagreed about how a signal is nominated for `read_configuration()`.
Reviewers of that PR were unwilling to have areaDetector plugins registered automatically,
because a detector typically carries far more plugins (16 ROIs, 16 stats) than are wired
into its chain, and reporting all of them gives no way to tell which values are
meaningful. Per-plugin opt-in needs a per-device call that can be made after construction
— which is the same primitive #1394 asks for.

Three designs were considered.

**Chain parsing.** Inspect the areaDetector plugin graph and register what is actually
wired up. Rejected as too large, and it breaks down once gather/scatter and PVA transfer
plugins are used between IOCs, since it requires every plugin to be exposed to ophyd.

**A single pluggable registry** holding both formats and logic objects, so that
`StandardReadable`, `StandardMovable`, `StandardFlyable` and `StandardDetector` all
register their behaviour the same way. Rejected: a format entry is keyed by child,
unbounded in number and merged by union, whereas a logic object is keyed by role, at most
one per role, and conflicts are an error. A single registry would have to branch on entry
kind at every insert. Runtime mutation also means different things for the two — changing
a format alters the contents of `describe()`, while changing a data logic alters which
bluesky protocols the Device satisfies. Finally the declarative annotation form only fits
formats: `A[SignalRW[float], PvSuffix.rbv("AcquireTime"), Format.CONFIG_SIGNAL]` works
because a format needs exactly `(parent, child)`, whereas `ADHDFDataLogic` needs a prefix,
a driver, a plugin list and a path provider.

**Key the format registry by device**, and leave logic objects alone. Chosen.

## Decision

### The registry holds `(device, format)` pairs

`StandardReadable._readables` is a tuple of pairs in registration order, and the callables
for each verb are derived on demand. `add_readables` becomes a thin wrapper over a new
`set_readable_format(device, format)`, and `format=None` removes the device.

Deriving on demand also fixes staging: `stage()` walks the current registry rather than a
tuple captured at registration, so a format changed between runs takes effect on the next
`stage()`.

Registration is "set" rather than "add": registering the same device twice replaces its
format rather than contributing it twice. This is a behaviour change, and the previous
behaviour was not deliberate.

Formats are normalised to real enum members on the way in. The deprecated `ConfigSignal`
and `HintedSignal` markers announce themselves by comparing equal to their target, which
relied on the `match` statement running during `add_readables`; normalising on entry keeps
the warning at registration rather than moving it to the first `read()`.

### Format changes apply between runs, not within one

A run's descriptor is emitted at its start, and `HINTED_SIGNAL` sets up monitoring in
`stage()`. Changing a format part way through a run would make `describe()` and `read()`
disagree. This is documented rather than enforced: the check would have to know about run
boundaries, which a Device does not.

### `StandardDetector` inherits `StandardReadable`

A detector's step-scan signals are registered exactly like any other Device's, and
`read()`, `describe()` and `hints` merge them on top of whatever the data logics produce.
`add_config_signals` becomes a deprecated wrapper.

Plugins are **not** registered automatically. `AreaDetector` registers only the driver's
`acquire_time` and `acquire_period`, plus whatever the caller passes as `config_sigs`.
Registering a plugin is a `set_readable_format()` call at the call site, which is the
explicit opt-in the #1395 reviewers asked for, now expressible per plugin and reversible
at runtime.

### Formats are stored and retrieved separately from settings

`walk_readable_formats` and `apply_readable_formats` serialise the registry as
`{path of StandardReadable: {path of child: format}}`, using the same dotted attribute
paths as `store_settings`, with `""` for the root Device. Values are plain strings so the
YAML stays hand-editable.

`apply_readable_formats` **replaces** the registered children of each named
`StandardReadable` rather than merging into them, so that loading a technique profile
drops what the previous one registered instead of accumulating the union of both. It
resolves every path before changing anything, so a bad path cannot leave the tree half
applied.

Formats are stored under a different name from `store_settings`, not folded into it:
values and formats change on different cadences, and `Settings` is a mapping of
`SignalRW` to value, whereas a format applies to `SignalR`s and whole Devices too.

## Consequences

- A Device can be switched between techniques at runtime, and the switch can be saved and
  restored, closing #1394.
- `add_readables` keeps working unchanged for all 85 in-tree call sites and for downstream
  Devices, but gains "set" semantics.
- Tests that asserted on `_read_funcs`, `_has_hints` and friends had to be rewritten onto
  the public verbs. Those assertions were already against the testing conventions in
  `CLAUDE.md`, and the derived-on-demand design makes them impossible rather than merely
  discouraged.
- Deriving callables per call costs a pass over the registry on every verb. The registries
  are small (tens of entries), and it is what makes the format mutable.
- Registering a device that is not within the tree still works, but its format cannot be
  stored, since there is no stable path for it. `walk_readable_formats` warns and skips.
- This ADR is numbered 21 rather than 20 to leave 20 for the unmerged bounded-data-logic
  ADR in #1367.
