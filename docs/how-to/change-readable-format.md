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

## Saving and restoring a technique

Formats are part of a Device's state, and they change on the same cadence as signal
values, so [](#store_settings) stores both and [](#apply_settings) applies both:

```python
def save_technique(det):
    provider = YamlSettingsProvider("/path/to/profiles")
    yield from store_settings(provider, "fixed_energy", det)


def load_technique(det, technique: str):
    provider = YamlSettingsProvider("/path/to/profiles")
    settings = yield from retrieve_settings(provider, technique, det)
    yield from apply_settings(settings)
```

Values stay flat in the yaml, and formats go under the reserved
[](#READABLE_FORMATS_KEY), so the file stays readable and hand-editable:

```yaml
energy: 7.0
temperature: 20.0
<READABLE_FORMATS>:
  <ROOT>:
    energy: CONFIG_SIGNAL
    temperature: CONFIG_SIGNAL
  stats:
    stats.total: HINTED_UNCACHED_SIGNAL
```

The outer key of each formats entry is the [](#StandardReadable) the child is registered
on, with [](#ROOT_PATH) for the Device you stored. It is recorded rather than inferred
because the same child can be registered on more than one Device with different formats.

```{note}
Applying **replaces** the children registered on each Device the file names, rather than
merging into them. That is what makes switching technique work: loading a profile drops
what the previous one registered instead of accumulating both.
```

Because each part is optional, a file with no `<READABLE_FORMATS>` key leaves formats
alone — so settings files saved before formats were storable keep working untouched. The
reverse is useful too: a hand-written formats-only profile switches technique without
writing a single value to hardware.

```yaml
<READABLE_FORMATS>:
  <ROOT>:
    energy: HINTED_SIGNAL
```

```{seealso}
[](../explanations/decisions/0021-runtime-readable-format.md) for why the registry is
keyed by Device and how the file is laid out, and [](./store-and-retrieve.md) for the
wider store/retrieve workflow.
```
