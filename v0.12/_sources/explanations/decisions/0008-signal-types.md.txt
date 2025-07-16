# 8. Settle on Signal Types
Date: 2024-10-18

## Status

Accepted

## Context

At present, soft Signals allow any sort of datatype, while CA, PVA, Tango restrict these to what the control system allows. This means that some soft signals when `describe()` is called on them will give `dtype=object` which is not understood by downstream tools. It also means that load/save will not necessarily understand how to serialize results. Finally we now require `dtype_numpy` for tiled, so arbitrary object types are not suitable even if they are serializable. We should restrict the datatypes allowed in Signals to objects that are serializable and are sensible to add support for in downstream tools.

## Decision

We will allow the following:
- Primitives:
    - `bool`
    - `int`
    - `float`
    - `str`
- Enums:
    - `StrictEnum` subclass which will be checked to have the same members as the CS
    - `SubsetEnum` subclass which will be checked to be a subset of the CS members
- 1D arrays:
    - `Array1D[np.bool_]`
    - `Array1D[np.int8]`
    - `Array1D[np.uint8]`
    - `Array1D[np.int16]`
    - `Array1D[np.uint16]`
    - `Array1D[np.int32]`
    - `Array1D[np.uint32]`
    - `Array1D[np.int64]`
    - `Array1D[np.uint64]`
    - `Array1D[np.float32]`
    - `Array1D[np.float64]`
    - `Sequence[str]`
    - `Sequence[MyEnum]` where `MyEnum` is a subclass of `StrictEnum` or `SubsetEnum`
- Specific structures:
    - `np.ndarray` to represent arrays where dimensionality and dtype can change and must be read from CS
    - `Table` subclass (which is a pydantic `BaseModel`) where all members are 1D arrays

## Consequences

Clients will be expected to understand:
- Python primitives (with Enums serializing as strings)
- Numpy arrays
- Pydantic BaseModels

All of the above have sensible `dtype_numpy` fields, but `Table` will give a structured row-wise `dtype_numpy`, while the data will be serialized in a column-wise fashion.

The following breaking changes will be made to ophyd-async:

## pvi structure changes
Structure now read from `.value` rather than `.pvi`. Supported in FastCS. Requires at least PandABlocks-ioc 0.10.0
## `StrictEnum` is now requried for all strictly checked `Enums`
```python
# old
from enum import Enum
class MyEnum(str, Enum):
    ONE = "one"
    TWO = "two"
# new
from ophyd_async.core import StrictEnum
class MyEnum(StrictEnum):
    ONE = "one"
    TWO = "two"
```
## `SubsetEnum` is now an `Enum` subclass:
```python
from ophyd_async.core import SubsetEnum
# old
MySubsetEnum = SubsetEnum["one", "two"]
# new
class MySubsetEnum(SubsetEnum):
    ONE = "one"
    TWO = "two"
```
## Use python primitives for scalar types instead of numpy types
```python
# old
import numpy as np
x = epics_signal_rw(np.int32, "PV")
# new
x = epics_signal_rw(int, "PV")
```
## Use `Array1D` for 1D arrays instead of `npt.NDArray`
```python
import numpy as np
# old
import numpy.typing as npt
x = epics_signal_rw(npt.NDArray[np.int32], "PV")
# new
from ophyd_async.core import Array1D
x = epics_signal_rw(Array1D[np.int32], "PV")
```
## Use `Sequence[str]` for arrays of strings instead of `npt.NDArray[np.str_]`
```python
import numpy as np
# old
import numpy.typing as npt
x = epics_signal_rw(npt.NDArray[np.str_], "PV")
# new
from collections.abc import Sequence
x = epics_signal_rw(Sequence[str], "PV")
```
## `MockSignalBackend` requires a real backend
```python
# old
fake_set_signal = SignalRW(MockSignalBackend(float))
# new
fake_set_signal = soft_signal_rw(float)
await fake_set_signal.connect(mock=True)
```
## `get_mock_put` is no longer passed timeout as it is handled in `Signal`
```python
# old
get_mock_put(driver.capture).assert_called_once_with(Writing.ON, wait=ANY, timeout=ANY)
# new
get_mock_put(driver.capture).assert_called_once_with(Writing.ON, wait=ANY)
```
## `super().__init__` required for `Device` subclasses
```python
# old
class MyDevice(Device):
    def __init__(self, name: str = ""):
        self.signal, self.backend_put = soft_signal_r_and_setter(int)
# new
class MyDevice(Device):
    def __init__(self, name: str = ""):
        self.signal, self.backend_put = soft_signal_r_and_setter(int)
        super().__init__(name=name)
```
## Arbitrary `BaseModel`s not supported, pending use cases for them
The `Table` type has been suitable for everything we have seen so far, if you need an arbitrary `BaseModel` subclass then please make an issue
## Child `Device`s set parent on attach, and can't be public children of more than one parent
```python
class SourceDevice(Device):
    def __init__(self, name: str = ""):
        self.signal = soft_signal_rw(int)
        super().__init__(name=name)

# old
class ReferenceDevice(Device):
    def __init__(self, signal: SignalRW[int], name: str = ""):
        self.signal = signal
        super().__init__(name=name)

    def set(self, value) -> AsyncStatus:
        return self.signal.set(value + 1)
# new
from ophyd_async.core import Reference

class ReferenceDevice(Device):
    def __init__(self, signal: SignalRW[int], name: str = ""):
        self._signal_ref = Reference(signal)
        super().__init__(name=name)

    def set(self, value) -> AsyncStatus:
        return self._signal_ref().set(value + 1)
```
