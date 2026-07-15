# 16. Replace AreaDetector writer parameters with ADWriterFactory

Date: 2026-05-15

## Status

Accepted

## Context

ADR 0012 introduced the composition-based `AreaDetector` baseclass.  Its
`__init__` accepted three writer-related constructor parameters side by side
with every other parameter:

```python
AreaDetector(
    driver,
    prefix,
    path_provider=path_provider,
    writer_type=NDFileHDF5IO,
    writer_suffix="HDF1:",
    ...
)
```

Several problems arose as the codebase matured:

1. **Three parameters always travel together.**  `path_provider`, `writer_type`,
   and `writer_suffix` are only meaningful as a unit; passing them individually
   obscures the relationship and requires callers to remember which combinations
   are valid.

2. **No first-class support for multiple writers.**  The original API exposed a
   single writer slot, so attaching a second HDF writer for a ROI plugin required
   calling `add_detector_logics()` after construction with low-level arguments
   that duplicated information already present at call time.

3. **No way to override array shape or data-type signals.**  The writer logic
   hard-coded `driver.array_size_{x,y,z}`, `driver.data_type`, and
   `driver.color_mode` as the source of NDArray metadata.  This was wrong for
   ROI plugins (which have their own `size_x`/`size_y` signals) and for
   processing plugins that remap the data type or colour mode.

4. **Deferred driver construction.**  Detector subclasses (e.g. `AravisDetector`)
   create their driver internally; the driver signals therefore do not exist at
   the point where the caller constructs `ADWriterFactory`.  Any eager
   `NDArrayDescription(data_type_signal=driver.data_type, ...)` call would need
   the driver to already exist—which it does not.

## Decision

Replace the three writer parameters with a single `*writer_factories` varargs
of `ADWriterFactory` instances:

```python
AreaDetector(
    driver,
    prefix,
    ADWriterFactory.hdf(path_provider),
    ...
)
```

### `ADWriterFactory`

A `@dataclass` (generic over the plugin IO type) with fields:

| Field | Type | Purpose |
|---|---|---|
| `writer_cls` | `type[NDPluginFileIOT]` | Plugin class to instantiate |
| `writer_suffix` | `str` | PV suffix appended to `prefix` |
| `writer_name` | `str` | Attribute name on the detector (`det.hdf`, `det.hdf1`, …) |
| `datakey_suffix` | `str` | Suffix appended to the datakey name in stream resources |
| `array_description` | `NDArrayDescription \| Callable[[ADBaseIO], NDArrayDescription] \| None` | Override for array shape/type metadata |
| `data_logic_factory` | callable | Builds the `DetectorDataLogic` from writer + description |

Three static constructors—`hdf()`, `jpeg()`, and `tiff()`—provide sensible
defaults.  They are named after the file format they produce, and their
`writer_name` defaults to the same string (`"hdf"`, `"jpeg"`, `"tiff"`),
so the writer is automatically stored at `det.hdf` etc.

`__call__(prefix, driver, plugins)` runs at `AreaDetector.__init__` time, when
the driver already exists, and returns `(writer_plugin, DetectorDataLogic)`.

### `NDArrayDescription` and the callable override

`NDArrayDescription` bundles the three signals that describe an NDArray frame:

```python
@dataclass
class NDArrayDescription:
    shape_signals: Sequence[SignalR[int]]
    data_type_signal: SignalR[ADBaseDataType]
    color_mode_signal: SignalR[ADBaseColorMode]
```

When `array_description` is `None`, `__call__` auto-builds it from
`driver.array_size_{z,y,x}`, `driver.data_type`, and `driver.color_mode`.

When a caller needs signals from a different source (an ROI plugin, a
processing plugin) *and* the driver is only created inside the detector
subclass, a callable is used:

```python
ADWriterFactory.hdf(
    path_provider,
    writer_name="hdf1",
    datakey_suffix="-roi1",
    array_description=lambda driver: NDArrayDescription(
        shape_signals=(roi1.size_y, roi1.size_x),
        data_type_signal=driver.data_type,   # driver available here
        color_mode_signal=driver.color_mode,
    ),
)
```

The callable receives the fully-constructed driver at `__call__` time, which is
the first moment all driver signals exist.  This design:

- keeps `data_type_signal` and `color_mode_signal` mandatory on
  `NDArrayDescription` (no silent defaults, no silent fall-through);
- allows *any* signal to be overridden, not just the shape—so a plugin that
  remaps the data type or colour mode can supply its own signal;
- avoids adding a new `Callable` type to `NDArrayDescription` itself, keeping
  that dataclass a plain value object.

### Multiple writers

Passing multiple factories gives each writer a distinct name and datakey suffix:

```python
det = adaravis.AravisDetector(
    "PREFIX:",
    ADWriterFactory.hdf(path_provider, writer_name="hdf1", datakey_suffix="-roi1",
                        array_description=lambda driver: NDArrayDescription(...)),
    ADWriterFactory.hdf(path_provider, writer_name="hdf2", datakey_suffix="-roi2",
                        array_description=lambda driver: NDArrayDescription(...)),
    plugins={"roi1": roi1, "roi2": roi2},
)
det.hdf1  # NDFileHDF5IO for ROI 1
det.hdf2  # NDFileHDF5IO for ROI 2
```

No post-construction `add_detector_logics()` call is required.

### `prefix` placement and guard

`prefix` is placed before `*writer_factories` (as a positional parameter with a
default of `None`) so that callers using the standard single-writer pattern can
pass it positionally.  A guard raises `ValueError` if factories are supplied but
`prefix` is `None`:

```python
if writer_factories and prefix is None:
    raise ValueError("prefix is required when writer_factories are given")
```

## Consequences

- `AreaDetector.__init__` and all seven bundled subclasses are updated; no
  compatibility shim is provided (the library is pre-1.0).
- `writer_name` must be unique across factories passed to the same detector;
  duplicate names raise an `AttributeError` at construction time.
- Callers that previously passed `writer_type=None` to suppress file writing now
  simply omit all factory arguments.
- `ADHDFDataLogic` and `ADMultipartDataLogic` expose their `NDArrayDescription`
  as `array_description` to avoid ambiguity with the similarly-named Python
  concept.
