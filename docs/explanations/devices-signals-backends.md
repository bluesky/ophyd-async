# Devices, Signals and their Backends

The [](#RunEngine) facing interface is defined by the [bluesky protocols](inv:bluesky#hardware) that a [](#Device) implements, but to implement that interface ophyd-async uses some helper classes. This document details how those helper classes fit together to provide particular Device behaviour.

## Device and DeviceConnector

The Device class is the base of all ophyd-async objects that are published to bluesky. It provides:
- a [](#~Device.name) read-only property to read it's name
- a [](#~Device.parent) read-write property to read it's parent Device if it exists
- a [](#~Device.children) iterator to get the `(name, child)` child Devices, populated when an attribute is set on the Device that is a Device
- a [](#~Device.set_name) method to set its name, and also set the names of its children
- a [](#~Device.connect) method that connects it and its children

All the above methods are concrete, but `connect()` calls out to a [](#DeviceConnector) to actually do the connection, only handling caching itself. This enables plug-in behaviour on connect (like the introspection of child Attributes in Tango or PVI, or the special case for Signal we will see later).

A DeviceConnector provides the ability to:
- [](#~DeviceConnector.create_children_from_annotations) that is called during `__init__` to turn annotations into concrete child Devices
- [](#~DeviceConnector.connect_mock) that is called if `connect(mock=True)` is called, and should connect the child Devices in mock mode for testing without a control system
- [](#~DeviceConnector.connect_real) that is called if `connect(mock=False)` is called, and should connect the child Devices to the control system in parallel

The base DeviceConnector provides suitable methods for use with non-introspected Devices, but there are various control system specific connectors that handle filling annotations in [declarative Devices](./declarative-vs-procedural.md).

## Signal and SignalBackend

If a Device with children is like a branch in a tree, a Signal is like a leaf. It has no children, but represents a single value or action in the control system. There are 4 types of signal:
- [](#SignalR) is a signal with a read-only value that supports the [](#Readable) and [](#Subscribable) protocols. It also adds the [](#SignalR.get_value) and [](#SignalR.subscribe_value) methods that are used to interact with the Signal in the parent Device.
- [](#SignalW) is a signal with a write-only value that supports the [](#Movable) protocol.
- [](#SignalRW) is a signal with a read-write value that inherits from SignalR and SignalW and adds the [](#Locatable) protocol
- [](#SignalX) is a signal that performs an action, and supports the [](#Triggerable) protocol

These are all concrete classes, but delegate their actions to a [](#SignalBackend):
```{literalinclude} ../../src/ophyd_async/core/_signal_backend.py
:pyobject: SignalBackend
```

Each control system implements its own concrete SignalBackend subclass with those methods filled in. It is these subclasses that take control system specific parameters like EPICS PV or Tango TRL. The instance is passed to `Signal.__init__`, which passes it to a generic [](#SignalConnector).

At `connect()` time this SignalConnector does one of two things:
- if `mock==False` then it calls `SignalBackend.connect` to connect it to the control system, and wires all the `Signal` methods to use it
- if `mock==True` then it creates a [](#MockSignalBackend) for test purposes and wires all the `Signal` methods to use it

This means that to construct a Signal you need to do something like:
```python
my_signal = SignalR(MyControlSystemBackend(int, cs_param="something"))
```

This is a little verbose, so instead we provide helpers like [](#soft_signal_rw) to make it a little shorter. The above might look like:
```python
my_signal = my_cs_signal_r(int, "something")
```

## "Standard" Device subclasses

There are also some Device subclasses that provide helpers when making Device subclasses, namely:
- [](#StandardReadable) that supports the [](#Readable) protocol using the values of its children
- [](#StandardDetector) that supports the [](#WritesStreamAssets) protocol using logic classes for the detetector driver and writer
- [](#StandardFlyer) that supports the [](#Flyable) protocol for motion and trigger systems
