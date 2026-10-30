# How to change what a Device reports at runtime

A [](#StandardReadable) decides what each child contributes to `read()`,
`read_configuration()` and `hints` from its [](#StandardReadableFormat).
[](#StandardReadable.set_readable_format) changes that on a live Device, like changing a
`Component`'s `kind` in ophyd v1.

## Changing one signal

A monochromator's energy might be scanned in one technique and held fixed in another:

```python
from ophyd_async.core import StandardReadableFormat as Format

# Scanning: energy is a hinted read
mono.set_readable_format(mono.energy, Format.HINTED_SIGNAL)

# Fixed: energy is configuration, recorded once per run
mono.set_readable_format(mono.energy, Format.CONFIG_SIGNAL)

# Not reported at all
mono.set_readable_format(mono.energy, None)
```

[](#StandardReadable.get_readable_formats) yields each registered child with its format:

```python
for child, format in mono.get_readable_formats():
    print(child.name, format)
```

```{note}
Change formats **between runs**, not inside one, or `describe()` and `read()` will disagree
with the descriptor emitted at the start of the run.
```

## Putting it back

[](#StandardReadable.reset_readable_formats) undoes every runtime change on one Device,
back to the formats its class declared. [](#apply_readable_formats) with no changes does
the same for a whole tree:

```python
from ophyd_async.core import apply_readable_formats

mono.reset_readable_formats()  # this Device only
apply_readable_formats(beamline, {})  # every Device in the tree
```

Both also discard formats loaded from a settings file.

```{seealso}
[](./store-and-retrieve.md) to save formats with signal values and load them back, and
[](../explanations/decisions/0023-runtime-readable-format.md) for the design.
```
