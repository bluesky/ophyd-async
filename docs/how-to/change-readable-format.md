# How to change what a Device reports at runtime

A [](#StandardReadable) decides what appears in `read()`, `read_configuration()` and
`hints` from the [](#StandardReadableFormat) each of its children is registered with.
Normally that is fixed when the Device class is written, but it can also be changed on a
live Device with [](#StandardReadable.set_readable_format).

This is the equivalent of changing a `Component`'s `kind` in ophyd v1.

## Changing one signal

A beamline with two techniques might scan a monochromator's energy in one and hold it
fixed in the other. The same Device serves both:

```python
from ophyd_async.core import StandardReadableFormat as Format

# Scanning technique: energy is a hinted read
mono.set_readable_format(mono.energy, Format.HINTED_SIGNAL)

# Fixed technique: energy is configuration, recorded once per run
mono.set_readable_format(mono.energy, Format.CONFIG_SIGNAL)

# Not interesting for this technique at all
mono.set_readable_format(mono.energy, None)
```

[](#StandardReadable.get_readable_format) reports the current format, returning `None` if
the child does not contribute.

```{note}
Change formats **between runs**, not inside one. A run's descriptor is emitted when the
run starts, and [](#StandardReadableFormat.HINTED_SIGNAL) begins monitoring in `stage()`,
so a format changed part way through a run would leave `describe()` and `read()`
disagreeing.
```

## Opting a detector plugin in

A [](#StandardDetector) is a [](#StandardReadable), so the same call works on one. This
matters most for areaDetector, where a detector often carries many more plugins than are
wired into its chain — so plugins are never registered automatically, and you opt in to
the ones that are actually producing meaningful values:

```python
det.set_readable_format(det.stats.total, Format.HINTED_UNCACHED_SIGNAL)
```

Data produced by a [](#DetectorDataLogic) is added on top of these, so a detector can
write a file *and* report a plugin scalar in a step scan.

## Saving and restoring a set of formats

Formats are part of a Device's state, so they can be stored and reloaded like settings
are. Use [](#store_readable_formats) and [](#retrieve_readable_formats) with any
[](#SettingsProvider), then [](#apply_readable_formats):

```python
def save_technique(det):
    provider = YamlSettingsProvider("/path/to/profiles")
    yield from store_readable_formats(provider, "fixed_energy", det)


def load_technique(det, technique: str):
    provider = YamlSettingsProvider("/path/to/profiles")
    formats = yield from retrieve_readable_formats(provider, technique, det)
    apply_readable_formats(det, formats)
```

The stored yaml maps each [](#StandardReadable)'s path to its children's formats, with
`""` for the root Device, so it stays readable and can be edited by hand:

```yaml
'': {energy: CONFIG_SIGNAL, temperature: CONFIG_SIGNAL}
stats: {stats.total: HINTED_UNCACHED_SIGNAL}
```

```{note}
[](#apply_readable_formats) **replaces** the children registered on each Device it names,
rather than merging into them. That is what makes switching technique work: loading a
profile drops what the previous one registered instead of accumulating both.
```

Formats are stored under a different name from [](#store_settings), which stores signal
*values*. The two change on different cadences, so keep them in separate files.

```{seealso}
[](../explanations/decisions/0021-runtime-readable-format.md) for why the registry is
keyed by Device, and [](./store-and-retrieve.md) for storing signal values.
```
