# 9. Procedural vs Declarative Devices

Date: 01/10/24

## Status

Accepted

## Context

In [](./0006-procedural-device-definitions.rst) we decided we preferred the procedural approach to devices, because of the issue of applying structure like `DeviceVector`. Since then we have `FastCS` and `Tango` support which use a declarative approach. We need to decide whether we are happy with this situation, or whether we should go all in one way or the other. A suitable test Device would be:

```python
class EpicsProceduralDevice(StandardReadable):
    def __init__(self, prefix: str, num_values: int, name="") -> None:
        with self.add_children_as_readables():
            self.value = DeviceVector(
                {
                    i: epics_signal_r(float, f"{prefix}Value{i}")
                    for i in range(1, num_values + 1)
                }
            )
        with self.add_children_as_readables(ConfigSignal):
            self.mode = epics_signal_rw(EnergyMode, prefix + "Mode")
        super().__init__(name=name)
```

and a Tango/FastCS procedural equivalent would be (if we add support to StandardReadable for Format.HINTED_SIGNAL and Format.CONFIG_SIGNAL annotations):
```python
class TangoDeclarativeDevice(StandardReadable, TangoDevice):
    value: Annotated[DeviceVector[SignalR[float]], Format.HINTED_SIGNAL]
    mode: Annotated[SignalRW[EnergyMode], Format.CONFIG_SIGNAL]
```

But we could specify the Tango one procedurally (with some slight ugliness around the DeviceVector):
```python
class TangoProceduralDevice(StandardReadable):
    def __init__(self, prefix: str, name="") -> None:
        with self.add_children_as_readables():
            self.value = DeviceVector({0: tango_signal_r(float)})
        with self.add_children_as_readables(ConfigSignal):
            self.mode = tango_signal_rw(EnergyMode)
        super().__init__(name=name, connector=TangoConnector(prefix))
```

or the EPICS one could be declarative:
```python
class EpicsDeclarativeDevice(StandardReadable, EpicsDevice):
    value: Annotated[
        DeviceVector[SignalR[float]], Format.HINTED_SIGNAL, EpicsSuffix("Value%d", "num_values")
    ]
    mode: Annotated[SignalRW[EnergyMode], Format.CONFIG_SIGNAL, EpicsSuffix("Mode")]
```

Which do we prefer?

## Decision

We decided that the declarative approach is to be preferred until we need to write formatted strings. At that point we should drop to an `__init__` method and a for loop. This is not a step towards only supporting the declarative approach and there are no plans to drop the procedural approach.

The two approaches now look like:

```python
class Sensor(StandardReadable, EpicsDevice):
    """A demo sensor that produces a scalar value based on X and Y Movers"""

    value: A[SignalR[float], PvSuffix("Value"), Format.HINTED_SIGNAL]
    mode: A[SignalRW[EnergyMode], PvSuffix("Mode"), Format.CONFIG_SIGNAL]


class SensorGroup(StandardReadable):
    def __init__(self, prefix: str, name: str = "", sensor_count: int = 3) -> None:
        with self.add_children_as_readables():
            self.sensors = DeviceVector(
                {i: Sensor(f"{prefix}{i}:") for i in range(1, sensor_count + 1)}
            )
        super().__init__(name)
```

## Consequences

We need to:
- Add support for reading annotations and `PvSuffix` in an `ophyd_async.epics.core.EpicsDevice` baseclass
- Do the `Format.HINTED_SIGNAL` and `Format.CONFIG_SIGNAL` flags in annotations for `StandardReadable`
- Ensure we can always drop to `__init__`


## pvi structure changes
Structure read from `.value` now includes `DeviceVector` support. Requires at least PandABlocks-ioc 0.11.2

## Epics `signal` module moves
`ophyd_async.epics.signal` moves to `ophyd_async.epics.core` with a backwards compat module that emits deprecation warning.
```python
# old
from ophyd_async.epics.signal import epics_signal_rw
# new
from ophyd_async.epics.core import epics_signal_rw
```

## `StandardReadable` wrappers change to `StandardReadableFormat`
`StandardReadable` wrappers change to enum members of `StandardReadableFormat` (normally imported as `Format`)
```python
# old
from ophyd_async.core import ConfigSignal, HintedSignal
class MyDevice(StandardReadable):
    def __init__(self):
        self.add_readables([sig1], ConfigSignal)
        self.add_readables([sig2], HintedSignal)
        self.add_readables([sig3], HintedSignal.uncached)
# new
from ophyd_async.core import StandardReadableFormat as Format
class MyDevice(StandardReadable):
    def __init__(self):
        self.add_readables([sig1], Format.CONFIG_SIGNAL)
        self.add_readables([sig2], Format.HINTED_SIGNAL)
        self.add_readables([sig3], Format.HINTED_UNCACHED_SIGNAL
```

## Declarative Devices are now available
```python
# old
from ophyd_async.core import ConfigSignal, HintedSignal
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw

class Sensor(StandardReadable):
    def __init__(self, prefix: str, name="") -> None:
        with self.add_children_as_readables(HintedSignal):
            self.value = epics_signal_r(float, prefix + "Value")
        with self.add_children_as_readables(ConfigSignal):
            self.mode = epics_signal_rw(EnergyMode, prefix + "Mode")
        super().__init__(name=name)
# new
from typing import Annotated as A
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import EpicsDevice, PvSuffix, epics_signal_r, epics_signal_rw

class Sensor(StandardReadable, EpicsDevice):
    value: A[SignalR[float], PvSuffix("Value"), Format.HINTED_SIGNAL]
    mode: A[SignalRW[EnergyMode], PvSuffix("Mode"), Format.CONFIG_SIGNAL]
```
