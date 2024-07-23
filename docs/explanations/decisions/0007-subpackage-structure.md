# 7. Sub-package Structure

Date: 2024-04-22

## Status

Accepted

## Context

[](./0004-repository-structure) proposed a top level repository structure. This builds upon it, suggesting a top level structure divided into:

- `ophyd_async.core`: Core classes like `Device`, `Signal` and `AsyncStatus`
- `ophyd_async.epics`: Epics specific signals and devices
- `ophyd_async.tango`: Tango specific signals and devices
- `ophyd_async.fastcs`: FastCS (EPICS or Tango) devices like PandA
- `ophyd_async.planstubs`: Plan stubs for various flyscan functionality
- `ophyd_async.sim`: Simulated devices for demos and tests

This ADR proposes a public sub-package structure. The internal private structure should be flat, but can change according to the number of classes in a public package.

## Decision

### core

There will be a flat public namespace under core, with contents reimported from an underscore prefixed python files, e.g.:

- `_status.py` for `AsyncStatus`, `WatchableAsyncStatus`, etc.
- `_protocol.py` for `AsyncReadable`, `AsyncStageable`, etc.
- `_device.py` for `Device`, `DeviceVector`, etc.
- `_signal.py` for `Signal`, `SignalBackend`, `observe_signal`, etc.
- `_mock.py` for `MockSignalBackend`, `get_mock_put`, etc.
- `_readable.py` for `StandardReadable`, `ConfigSignal`, `HintedSignal`, etc.
- `_detector.py` for `StandardDetector`, `DetectorWriter`, `DetectorControl`, `TriggerInfo`, etc.
- `_flyer.py` for `StandardFlyer`, `FlyerControl`, etc.

There are some renames that will be required, e.g. `HardwareTriggeredFlyable` -> `StandardFlyer`

### epics

Epics modules consist of 2 sorts of classes:
- `IO` classes, which are `Device` subclasses containing `Signals` that map as closely as possible to the EPICS template hierarchy. Their name matches the EPICS template with the suffix `IO`.
- `Control` and `Writer` classes that plug into `StandardDetector` and `StandardFlyer` telling them which logic to use during various bluesky verbs.

There should be an additional level of packages that correspond to the epics support module, and contain classes that map to the EPICS database and logic classes e.g.:

- `epics.signal`: containing `epics_signal_rw`, `CaSignalBackend`, etc.
- `epics.adcore`: containing `ADDriverIO`, `NDFileHdfIO`, `ADHdfWriter` etc. 
- `epics.adpilatus`: containing `ADPilatusIO`, `PilatusControl` etc.

The name of the module is the EPICS module lowercased with dashes and other special characters converted to underscores.

They can be imported from modules:

```python
from ophyd_async.epics import adcore, adpilatus

drv = adpilatus.ADPilatusIO(prefix + "DRV:")
hdf = adcore.NDFileHDFIO(prefix + "HDF:")
```

The structure is left to an individual module's size. For instance `motor` will probably be a single `motor.py`, while `ADCore` will likely be an `ADCore/` directory with `_io.py`, `_writer.py`, `_control.py`.

Detector modules should include a reference `StandardDetector` subclass, but without making any site specific decisions about PV naming.

### tango

This has not been created at the time of writing, but it is envisioned that it will follow the EPICS structure where it makes sense.

### fastcs

There will be one subpackage for each FastCS Device. At the time of writing there are none of these, but PandA and Odin will shortly be converted to FastCS, so it makes sense to make:

- `fastcs.panda`
- `fastcs.odin`

in preparation. 

For PandA its namespace should contain `CommonPandaBlocks`, `SeqBlock`, `PandaHdfWriter`, `PandaPcapController`, etc. These should be included in files like `_control.py`, `_writer.py`, `_block.py`, `_table.py` and imported into the `panda` namespace.

### planstubs

There will be some planstubs for shared setup that may reach across modules like `epics` and `fastcs/panda`, these should live in a `planstubs/` package.

### sim

There will be 2 subpackages:
- `sim.demo` for demo devices like `PatternDetector` and `SimMotor` used in tutorials.
- `sim.testing` for devices that will support tests in `ophyd-async` and `bluesky`. Some test fixtures could be moved here

There should probably be one file per Device, in an underscore prefixed file reimported into the public namespace, e.g. `demo/_sim_motor.py` and `demo/_pattern_detector.py`.

## Consequences

The public import paths are fixed, but the underlying implementation can move from modules to packages without change to the public interface.
