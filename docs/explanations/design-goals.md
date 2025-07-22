# Design goals and differences with ophyd sync

Ophyd-async was designed to be a library for asynchronously interfacing with hardware. As such it fulfils the same role in the bluesky ecosystem as [ophyd sync](https://github.com/bluesky/ophyd): an abstraction layer that enables experiment orchestration and data acquisition code to operate above the specifics of particular devices and control systems. This document details the design goals and the differences with ophyd sync.

## Asynchronous Signal access

A fundamental part of ophyd-async is [](#asyncio). This allows lightweight and deterministic control of multiple signals, making it possible to do the "put 2 PVs in parallel, then get from another PV" logic that is common in fly scanning without the performance and complexity overhead of multiple threads.

For instance, the threaded version of the above looks something like this:
```python
def set_signal_thread(signal, value):
    t = Thread(signal.set, value)
    t.start()
    return

def run():
    t1 = set_signal_thread(signal1, value1)
    t2 = set_signal_thread(signal2, value2)
    t1.join()
    t2.join()
    value = signal3.get_value()
```
This gives the overhead of co-ordinating multiple OS threads, which requires events and locking for any more complicated example.

Compare to the asyncio version:
```python
async def run():
    await asyncio.gather(
        signal1.set(value1),
        signal2.set(value2)
    )
    value = await signal3.get_value()
```
This runs in a single OS thread, but has predictable interrupt behavior, allowing for a much more readable linear flow.

```{seealso}
[](../how-to/interact-with-signals.md) for examples of the helpers that are easier to write with asyncio.
```

## Support for CA, PVA, Tango

As well as the tradition EPICS Channel Access, ophyd-async was written to allow other Control system protocols, like EPICS PV Access and Tango. An ophyd-async [](#Signal) contains no control system specific logic, but takes a [](#SignalBackend) that it uses whenever it needs to talk to the control system. Likewise at the [](#Device) level, a [](#DeviceConnector) allows control systems to fulfil the type hints of [declarative devices](./declarative-vs-procedural.md).

```{seealso}
[](./devices-signals-backends.md) for more information on how these fit together, and [](../tutorials/implementing-devices.md) for examples of Devices in different control systems.
```

## Clean Device Definition

For highly customizable devices like [PandABox](https://quantumdetectors.com/products/pandabox) there are often different pieces of logic that can talk to the same underlying hardware interface. The Devices in ophyd-async are structured so that the logic and interface can be split, and thus can be cleanly organized via composition rather than inheritance. 

## Ease the implementation of fly scanning

One of the major drivers for ophyd-async was to ease the implementation of fly scanning. A library of fly scanning helpers is being developed to aid such strategies as:
- Definition of scan paths via [ScanSpec](https://github.com/dls-controls/scanspec)
- PVT Trajectory scanning in [Delta Tau motion controllers](https://github.com/dls-controls/pmac)
- Position compare and capture using a [PandABox](https://quantumdetectors.com/products/pandabox)

These strategies will be ported from DLS's previous fly scanning software [Malcolm](https://github.com/dls-controls/pymalcolm) and improved to take advantage of the flexibility of bluesky's plan definitions.

```{seealso}
[](../explanations/fly-scanning.md)
```

## Parity and interoperativity with ophyd sync

Devices from both ophyd sync and ophyd-async can be used in the same RunEngine and even in the same scan. This allows a per-device migration where devices are reimplemented in ophyd-async one by one. Eventually ophyd sync will gain feature parity with ophyd sync, supporting [the same set of devices as ophyd](https://blueskyproject.io/ophyd/user/reference/builtin-devices.html)
