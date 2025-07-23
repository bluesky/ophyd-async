# Devices, Signals and their Backends

The [](#bluesky.run_engine.RunEngine) facing interface is defined by the [bluesky protocols](inv:bluesky#hardware) that a [](#Device) implements, but to implement that interface ophyd-async uses some helper classes. This document details how those helper classes fit together to provide particular `Device` behavior.

## Device and DeviceConnector

```{mermaid}
:config: { "theme": "neutral" }
:align: center
classDiagram
Device *-- DeviceConnector
Device : connect(mock)
Device <|-- EpicsDevice
Device <|-- TangoDevice
EpicsDevice *-- EpicsDeviceConnector
TangoDevice *-- TangoDeviceConnector
DeviceConnector <|-- EpicsDeviceConnector
DeviceConnector <|-- TangoDeviceConnector
```

The `Device` class is the base of all ophyd-async objects that are published to bluesky. It provides:
- a [](#Device.name) read-only property to read it's name
- a [](#Device.parent) read-write property to read it's parent Device if it exists
- a [](#Device.children) to iterate through the Device attributes, yielding the `(name, child)` child Devices
- a `setattr` override that detects whether the attribute is also a Device and sets its parent
- a [](#Device.set_name) method to set its name and also set the names of its children using the parent name as a prefix, called at init and also when a new child is attached to an already named Device
- a [](#Device.connect) method that connects it and its children

All the above methods are concrete, but `connect()` calls out to a [](#DeviceConnector) to actually do the connection, only handling caching itself. This enables plug-in behavior on connect (like the introspection of child Attributes in Tango or PVI, or the special case for `Signal` we will see later).

A `DeviceConnector` provides the ability to:
- [](#DeviceConnector.create_children_from_annotations) that is called during `__init__` to turn annotations into concrete child Devices
- [](#DeviceConnector.connect_mock) that is called if `connect(mock=True)` is called, and should connect the child Devices in mock mode for testing without a control system
- [](#DeviceConnector.connect_real) that is called if `connect(mock=False)` is called, and should connect the child Devices to the control system in parallel

The base `DeviceConnector` provides suitable methods for use with non-introspected Devices, but there are various control system specific connectors that handle filling annotations in [declarative Devices](./declarative-vs-procedural.md).

## Signal and SignalBackend

```{mermaid}
:config: { "theme": "neutral" }
:align: center
classDiagram
Device <|-- Signal
Signal : source
Signal <|-- SignalR
SignalR : read()
SignalR : subscribe()
SignalR : get_value()
Signal <|-- SignalW
SignalW : set()
SignalR <|-- SignalRW
SignalW <|-- SignalRW
SignalRW : locate()
Signal <|-- SignalX
SignalX : trigger()
Signal *-- SignalConnector
SignalConnector *-- SignalBackend
SignalBackend <|-- CaSignalConnector
SignalBackend <|-- PvaSignalConnector
SignalBackend <|-- TangoSignalConnector
```

If a `Device` with children is like a branch in a tree, a `Signal` is like a leaf. It has no children, but represents a single value or action in the control system. There are 4 types of signal:
- [](#SignalR) is a signal with a read-only value that supports the [Readable](#bluesky.protocols.Readable) and [Subscribable](#bluesky.protocols.Subscribable) protocols. It also adds the [](#SignalR.get_value) and [](#SignalR.subscribe_value) methods that are used to interact with the Signal in the parent Device.
- [](#SignalW) is a signal with a write-only value that supports the [Movable](#bluesky.protocols.Movable) protocol.
- [](#SignalRW) is a signal with a read-write value that inherits from SignalR and SignalW and adds the [Locatable](#bluesky.protocols.Locatable) protocol
- [](#SignalX) is a signal that performs an action, and supports the [Triggerable](#bluesky.protocols.Triggerable) protocol

These are all concrete classes, but delegate their actions to a [](#SignalBackend):
```{literalinclude} ../../src/ophyd_async/core/_signal_backend.py
:pyobject: SignalBackend
```

Each control system implements its own concrete `SignalBackend` subclass with those methods filled in. It is these subclasses that take control system specific parameters like EPICS PV or Tango TRL. The instance is passed to `Signal.__init__`, which passes it to a generic [](#SignalConnector).

At `connect()` time this `SignalConnector` does one of two things:
- if `mock==False` then it calls `SignalBackend.connect` to connect it to the control system, and wires all the `Signal` methods to use it
- if `mock==True` then it creates a [](#MockSignalBackend) for test purposes and wires all the `Signal` methods to use it

This means that to construct a `Signal` you need to do something like:
```python
my_signal = SignalR(MyControlSystemBackend(int, cs_param="something"))
```

This is a little verbose, so instead we provide helpers like [](#soft_signal_rw) to make it a little shorter. The above might look like:
```python
my_signal = my_cs_signal_r(int, "something")
```

## "Standard" Device subclasses

```{mermaid}
:config: { "theme": "neutral" }
:align: center
classDiagram
Device <|-- StandardReadable
Device <|-- StandardDetector
Device <|-- StandardFlyer
```

There are also some `Device` subclasses that provide helpers for implementing particular protocols, namely:
- [](#StandardReadable) that supports the [Readable](#bluesky.protocols.Readable) protocol using the values of its children
- [](#StandardDetector) that supports the [WritesStreamAssets](#bluesky.protocols.WritesStreamAssets) protocol using logic classes for the detector driver and writer
- [](#StandardFlyer) that supports the [Flyable](#bluesky.protocols.Flyable) protocol for motion and trigger systems

```{seealso}
[](../how-to/choose-right-baseclass.md)
```
