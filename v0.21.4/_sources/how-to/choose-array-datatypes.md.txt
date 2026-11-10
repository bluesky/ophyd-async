(choose-array-datatypes)=
# How to choose an array datatype for a Signal

An array Signal can be declared three ways. They differ in how much the
annotation promises about the array, and a backend only accepts the spellings
its control system can honour.

| Spelling | Datatype | Number of dimensions |
| --- | --- | --- |
| `Array1D[np.float64]` | fixed at declaration | always 1 |
| `npt.NDArray[np.float64]` | fixed at declaration | read from the control system |
| `np.ndarray` | read from the control system | read from the control system |

## Which one to use

Use [](#Array1D) for a one dimensional array of known datatype. This is the
common case: a waveform of readings, a trajectory of positions, a column of a
[](#Table).

```python
from ophyd_async.core import Array1D
import numpy as np

positions: SignalRW[Array1D[np.float64]]
```

Use `npt.NDArray` when the datatype is known but the number of dimensions is
not, or is greater than one.

```python
import numpy.typing as npt

image: SignalR[npt.NDArray[np.uint16]]
```

Use [](#numpy.ndarray) when neither the datatype nor the number of dimensions
is known until the Signal connects, as for a detector whose pixel format is
configurable.

```python
frame: SignalR[np.ndarray]
```

## What each one checks

A Signal declared with a fixed number of dimensions rejects a value of any
other rank, so a scalar or a nested list written to an [](#Array1D) Signal
raises a `ValueError` rather than being silently reshaped:

```python
signal = soft_signal_rw(Array1D[np.float64])
await signal.set(np.array([1.0, 2.0]))  # ok
await signal.set(np.float64(1.0))       # ValueError: Expected 1D array, got 0D array
```

`npt.NDArray` and [](#numpy.ndarray) constrain no rank, so an array of any
shape is accepted. `npt.NDArray` still coerces the datatype, while
[](#numpy.ndarray) stores whatever it is given.

## Which backends accept which

Soft signals accept all three.

EPICS accepts [](#Array1D) and [](#numpy.ndarray) only. A PV always states the
rank of its data: a Channel Access waveform and a PVA `NTScalarArray` are one
dimensional, and a PVA `NTNDArray` is the image case that [](#numpy.ndarray)
already describes. `npt.NDArray` therefore asks for something no PV can
provide, and raises a `TypeError` when the Signal is created:

```python
epics_signal_rw(npt.NDArray[np.float64], "PV")
# TypeError: Expected Array1D[dtype] or np.ndarray, got npt.NDArray[np.float64]
```

Tango uses `npt.NDArray` for an `IMAGE` attribute and [](#Array1D) for a
`SPECTRUM` attribute.
