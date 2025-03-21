# How to derive one signal from others

Sometimes the low level Signal interface of a Device is not very user friendly. You may wish to provide a layer of Signals above that calculate their values from low level Signals, and are capable of setting their values too. We call this a Derived Signal. This article will show how they are constructed and how they can be used.

## Single Derived Signal

The simplest API involves mapping a single Derived Signal to many low level Signal. There are 3 helpers to create these Derived signals:
- [`derived_signal_r`](#ophyd_async.core.derived_signal_r)
- [`derived_signal_rw`](#ophyd_async.core.derived_signal_rw)
- [`derived_signal_w`](#ophyd_async.core.derived_signal_w)

If a signal is readable, then it requires a `raw_to_derived` function that maps the raw values of low level Signals into the datatype of the Derived Signal and the `raw_devices` that will be read/monitored to give those values.

If a signal is writeable, then it requires a `set_derived` async function that sets the raw signals based on the derived value.
 
In the below example we see all 3 of these helpers in action:

```{literalinclude} ../../src/ophyd_async/testing/_single_derived.py
:language: python
```

```{note}
These examples show the low level Signals and Derived Signals in the same Device, but they could equally be separated into different Devices
```

## Multi Derived Signal

The more general API involves a two way mapping between many Derived Signals and many low level Signals. This is done by implementing a `Raw` [](#typing.TypedDict) subclass with the names and datatypes of the low level Signals, a `Derived` [](#typing.TypedDict) subclass with the names and datatypes of the derived Signals, and [](#Transform) class with `raw_to_derived` and `derived_to_raw` methods to convert between the two. Some transforms will also require parameters which get their values from other Signals for both methods. These should be put in as type hints on the `Transform` subclass.

To create the derived signals, we make a [](#DerivedSignalFactory) instance that knows about the `Transform` class, the `raw_devices` that will be read/monitored to provide the raw values for the transform, and optionally the `set_derived` method to set them. The methods like [](#DerivedSignalFactory.derived_signal_rw) allow Derived signals to be created for each attribute in the `Derived` TypedDict subclass.

In the below example we see this is action:

```{literalinclude} ../../src/ophyd_async/testing/_multi_derived.py
:language: python
```

```{note}
We do the mapping of the publically accessible names (`x` and `roll`) to the transform names (`height` and `angle`) in the public `set()` method. If those names were the same we wouldn't need the `_set_mirror` method which took the transform names, we could both pass the `set()` method to `DerivedSignalFactory`, and use it as the public interface for moving multiple axes concurrently.
```
