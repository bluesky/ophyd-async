.. note::

   Ophyd async is included on a provisional basis until the v1.0 release and 
   may change API on minor release numbers before then

Create devices
==============

.. currentmodule:: ophyd_async.core

There are lots of ways to create ophyd-async devices, since an ophyd-async
device simply needs to subclass `Device` and obey certain protocols to work
with bluesky plans or plan stubs. By default, some utility classes and 
functions exist to simplify this process for you.

Make a simple device
--------------------

To make a simple device, you need to subclass from the `Device` class and
optionally create some `Signal` instances connecting to EPICS PVs in the 
constructor.

Because `Signal` instances require a backend to understand how to interface
with hardware over protocols like EPICS, you will need to either instantiate 
such a backend, or use factory functions within `ophyd_async.epics.signal` such
that these are automatically generated for you.

This can be as simple as:

.. code-block:: python

   from ophyd_async.core import Device
   from ophyd_async.epics.signal import epics_signal_rw

   class MyDevice(Device):
       def __init__(self, prefix, name = ""):
           self.my_pv = epics_signal_rw(float, prefix + ":Mode")
           super().__init__(name=name)

``self.my_pv`` is now an instance of ``SignalRW``. There are four variants of
these factory functions:

1. `ophyd_async.epics.signal.epics_signal_r` which produces a `SignalR`,
2. `ophyd_async.epics.signal.epics_signal_w` which produces a `SignalW`,
3. `ophyd_async.epics.signal.epics_signal_rw` which produces a `SignalRW`,
4. `ophyd_async.epics.signal.epics_signal_x` which produces a `SignalX`.

These variants of `Signal` will provide useful default methods, for example
`SignalW` implements ``.set`` which means it obeys the 
:class:`~bluesky.protocols.Movable` protocol, `SignalR` implements 
``.get_value``, `SignalRW` subclasses both of these and `SignalX` implements
``.trigger`` to execute a PV by setting it to ``None``.


Signals created in this way need to be passed a Python type that their value
can be converted to, and a string to connect to (i.e. fully qualified name to
reach the PV). The python type of all epics signals can be one of:

- A primitive (`str`, `int`, `float`)
- An array (`numpy.typing.NDArray` or ``Sequence[str]``)
- An enum (`enum.Enum`), which must also subclass `str`.

Some enum PV's can be coerced into a bool type, provided they have only two 
options.

Going back to the above example, ``super().__init__(name=name)`` ensures any 
child devices are correctly named. `Signal` objects subclass `Device`, which 
means ``self.my_pv`` is itself a child device. Such devices can be accessed 
through `Device.children`.

``MyDevice`` is not itself ``Movable`` although it has a signal that is, 
because it does not have a ``.set`` method. You can make it ``Movable`` by 
adding it:

.. code-block:: python

   from ophyd_async.core import Device, AsyncStatus
   from ophyd_async.epics.signal import epics_signal_rw
   from bluesky.protocols import Movable
   from typing import Optional
   import asyncio

   class MyDevice(Device, Movable):
       def __init__(self, prefix, name = ""):
           self.my_pv = epics_signal_rw(float, prefix + ":Mode")
           super().__init__(name=name)

       async def _set(self, value: float) -> None:
           await self.my_pv.set(value)

       def set(self, value: float, timeout: Optional[float] = None) -> AsyncStatus:
           coro = asyncio.wait_for(self._set(value), timeout=timeout)
           return AsyncStatus(coro, [])

There is some added complexity here, because the ``Movable`` protocol has to be
able to apply to both ophyd and ophyd-async, and only one of these leverages
asynchronous logic. Therefore the signature of ``set`` itself must be 
synchronous. In this case, we return an `AsyncStatus` which can be awaited on
to complete the coroutine it is wrapping.

You can follow this pattern with any protocol.

Make a simple device to be used in scans
----------------------------------------

Bluesky plans require devices to be stageable. In many cases, you will probably
be dealing with devices that are readable, that is, that they have some PV
whose value(s) are interesting to observe in a scan. For such a use case, you
can use `StandardReadable`, which provides useful default behaviour:

.. code-block:: python

   from ophyd_async.core import Device, AsyncStatus
   from ophyd_async.epics.signal import epics_signal_rw
   from bluesky.protocols import Movable
   from typing import Optional
   import asyncio

   class MyDevice(StandardReadable, Movable):
       def __init__(self, prefix, name = ""):
           self.my_pv = epics_signal_rw(float, prefix + ":Mode")
           self.my_interesting_pv = epics_signal_rw(float, prefix + ":Interesting")
           self.my_changing_pv = epics_signal_rw(float, prefix + ":ChangesOften")
           
           self.set_readable_signals(
               read=[self.my_interesting_pv],
               config=[self.my_pv], 
               read_uncached=[self.my_changing_pv]
           )

           super().__init__(name=name)

       async def _set(self, value: float) -> None:
           await self.my_pv.set(value)

       def set(self, value: float, timeout: Optional[float] = None) -> AsyncStatus:
           coro = asyncio.wait_for(self._set(value), timeout=timeout)
           return AsyncStatus(coro, [])


Above, `StandardReadable.set_readable_signals` is called with:

- ``read`` signals: Signals that should be output to ``read()``
- ``config`` signals: Signals that should be output to ``read_configuration()``
- ``read_uncached`` signals: Signals that should be output to ``read()`` but 
  whose values should not be cached, for example if they change so frequently 
  that caching their values will not be useful.

All signals passed into this init method will be monitored between ``stage()``
and ``unstage()`` and their cached values returned on ``read()`` and 
``read_configuration()`` for perfomance, unless they are specified as uncached.

Make a compound device
----------------------

`Signal` instances subclass `Device`, so you can make your own `Device` classes
and instantiate them in a `Device` constructor to nest devices:


.. code-block:: python

   from ophyd_async import Device
   from ophyd_async.epics.signal import epics_signal_rw

   class Motor(Device):
       def __init__(self, prefix, name = ""):
           self.motion = epics_signal_rw(float, prefix + ":Motion")
           super().__init__(name=name)
   
   class SampleTable(Device):
       def __init__(self, prefix, name=""):
           self.x_motor = Motor(prefix + ":X")
           self.y_motor = Motor(prefix + ":Y")
           super().__init__(name=name)

Make a device vector
--------------------

Sometimes signals logically belong in a dictionary, or a vector:

.. code-block:: python

   from ophyd_async.core import Device
   from ophyd_async.epics.signal import epics_signal_rw

   class Motor(Device):
       def __init__(self, prefix, name = ""):
           self.motion = epics_signal_rw(float, prefix + ":Motion")
           super().__init__(name=name)

   motors = DeviceVector({1: Motor("Motor1", name="motor-1"), 2: Motor("Motor2", name="motor-2")})

Alternatively, you can create the devices that will go into your device vector
before passing them through to a `DeviceVector`:

.. code-block:: python

   from ophyd_async.core import DeviceVector

   motor1 = Motor("Motor1", name="motor-1")
   motor2 = Motor("Motor2", name="motor-2")
   motors = DeviceVector({1:motor1, 2:motor2})

Instantiate a device
--------------------
The process of instantiating a device, regardless of exactly how it subclasses
a `Device`, is the same:

1. Start the RunEngine,
2. Create an instance of the desired device(s)
3. Connect them in the RunEngine event loop

.. code-block:: python

   from bluesky.run_engine import RunEngine, call_in_bluesky_event_loop

   RE = RunEngine()
   my_device = MyDevice("SOME:PREFIX:", name="my_device")
   call_in_bluesky_event_loop(my_device.connect())

Connecting the device is optional, however if it is not done any signals will
be unusable, meaning you will not be able to run bluesky scans with it.

Devices must **always** be defined to at least call ``super().__init__(name=
name)`` in their constructors, preferably by the end. This means that if a name
is passed to the device upon instantiation, `Device.set_name` gets called
which will name all of the child devices using the python variable names.

Devices must **always** be named at the top level, as in the above example,
so that each `Device` instance (including `Signal`) has a unique name. If this
step is omitted, you may see unexpected RunEngine errors when it tries to
collect event documents, as it uses the `Device.name` property to collect this
data into a dictionary. Python dictionaries cannot support multiple keys with
the same value, so **each device name must be unique**.

`Device.connect` can accept a ``sim`` keyword argument, to indicate if
the Device should be started in simulation mode. In this mode, no connection to
any underlying hardware is established.
