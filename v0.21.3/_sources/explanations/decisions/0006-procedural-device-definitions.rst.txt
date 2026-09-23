6. Procedural Device Definitions
================================

Date: 2023-09-11

Status
------

Accepted

Context
-------

Ophyd creates devices in a declarative way:

.. code-block:: python

    class Sensor(Device):
        mode = Component(EpicsSignal, "Mode", kind="config")
        value = Component(EpicsSignalRO, "Value", kind="hinted")

This means when you make ``device = OldSensor(pv_prefix)`` then some metaclass
magic will call ``EpicsSignal(pv_prefix + "Mode", kind="config")`` and make it
available as ``device.mode``.

ophyd-async could convert this approach to use type hints instead of metaclasses:

.. code-block:: python

    from typing import Annotated as A

    class Sensor(EpicsDevice):
        mode: A[SignalRW, CONFIG, pv_suffix("Mode")]
        value: A[SignalR, READ, pv_suffix("Value")]

The superclass init could then read all the type hints and instantiate them with
the correct SignalBackends. 

Alternatively it could use a procedural approach and be explicit about where the
arguments are passed at the cost of greater verbosity:

.. code-block:: python

    class Sensor(StandardReadable):
        def __init__(self, prefix: str, name="") -> None:
            self.value = epics_signal_r(float, prefix + "Value")
            self.mode = epics_signal_rw(EnergyMode, prefix + "Mode")
            # Set name and signals for read() and read_configuration()
            self.set_readable_signals(read=[self.value], config=[self.mode])
            super().__init__(name=name)

The procedural approach to creating child Devices is:

.. code-block:: python

    class SensorGroup(Device):
        def __init__(self, prefix: str, num: int, name: Optional[str]=None):
            self.sensors = DeviceVector(
                {i: Sensor(f"{prefix}:CHAN{i}" for i in range(1, num+1))}
            )
            super().__init__(name=name)

We have not been able to come up with a declarative approach that can describe
the ``SensorGroup`` example in a succinct way.

Decision
--------

Type safety and readability are regarded above velocity, and magic should be
minimized. With this in mind we will stick with the procedural approach for now.
We may find a less verbose way of doing ``set_readable_signals`` by using a
context manager and overriding setattr in the future:

.. code-block:: python

    with self.signals_added_to(READ):
        self.value = epics_signal_r(float, prefix + "Value")
    with self.signals_added_to(CONFIG):
        self.mode = epics_signal_rw(EnergyMode, prefix + "Mode")

If someone comes up with a way to write ``SensorGroup`` in a declarative
and readable way then we may revisit this.

Consequences
------------

Ophyd and ophyd-async Devices will look less alike, but ophyd-async should be
learnable for beginners.
