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

### Formats are stored in the same file as settings, under a reserved key

Values and formats are applied on the same cadence — a technique change wants both — so
they belong in one file and one `apply_settings` call. `store_settings` keeps values flat
and adds one reserved key:

```yaml
energy: 7.0
temperature: 20.0
<READABLE_FORMATS>:
  <ROOT_DEVICE>:
    energy: CONFIG_SIGNAL
    temperature: CONFIG_SIGNAL
```

`Settings` gains a `readable_formats` attribute, so one `retrieve_settings` returns the
whole stored state.

**No version marker is needed.** A file written before formats existed simply lacks the
reserved key, which under replacement semantics reads correctly as "no owner is listed, so
clear no owner" — leave formats alone. Present-but-empty for an owner (`<ROOT_DEVICE>: {}`) means
"clear that owner", which is what a freshly-saved Device with nothing registered produces.
The two states are distinguishable without a version, and each section being independently
optional also makes a hand-written formats-only profile work, changing technique without
writing a value to hardware.

**The reserved keys cannot collide.** `<READABLE_FORMATS>` and `<DEVICE_NAMES>` start with
`<`, which cannot begin a Python identifier, so no attribute assignment can produce a
colliding path — no store-time guard is required. `<` is also not a YAML indicator, so
unlike `*FORMATS*` or `%FORMATS%` the key needs no quoting. `<ROOT_DEVICE>` replaces `""` as the
root owner for the same reason and because an empty-string key makes PyYAML emit its
hard-to-read explicit `? '' :` form. `<DEVICE_NAMES>` is reserved but unwritten, so storing
names later needs no migration.

**The formats section is two levels while values are flat.** A value is intrinsic to one
path; a format is a fact about an (owner, child) *pair*, and the same child can be
registered on two owners with different formats — which #1395 creates directly, since
`NDStatsIO` will declare `total` on itself while a detector may also register `stats.total`.
Recording the owner rather than inferring it also means the layout needs no "must be a
direct child" rule, so `AreaDetector` can keep registering `driver.acquire_time` and
`DeviceVector` elements keep working, with no dependency on #1395 and no second migration
later.

`apply_readable_formats` **replaces** the registered children of each named
`StandardReadable` rather than merging into them, so that loading a technique profile drops
what the previous one registered instead of accumulating the union of both. It resolves
every path before changing anything, so a bad path cannot leave the tree half applied.

`Settings.partition` copies the formats to **both** halves. A device-specific apply plan
normally applies only the halves and never the original `Settings` — `apply_panda_settings`
partitions and calls `apply_settings` twice — so putting formats on one half would let the
plan silently decide whether they were restored at all. Applying them more than once is
harmless: it touches no hardware and is idempotent. `apply_settings` applies formats after
values, so a failed value write leaves the readable registry untouched.

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
