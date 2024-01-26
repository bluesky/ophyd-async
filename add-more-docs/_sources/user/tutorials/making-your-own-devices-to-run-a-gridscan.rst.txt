.. note::

    Ophyd async is included on a provisional basis until the v1.0 release and 
    may change API on minor release numbers before then

Making your own devices to run a gridscan
=========================================

This tutorial will guide you through the process of making ophyd-async devices
to run bluesky plans on. It assumes you have some familiarity with Bluesky, and
that you have already run through the tutorial on `tutorial_run_engine_setup`.

We will be running EPICS IOCs, and writing devices to run *step scans* on them.
This means the triggering of PVs will be handled entirely by our software. 

Please see the :doc:`this tutorial<using-existing-devices>` if you don't
really care about how to make your own devices and just want to get started
with existing ones. The devices you will write by the end of this tutorial are
the same devices this tutorial manipulates.

Setting up the EPICS layer
--------------------------
First, lets set up some PVs that we can communicate with. We are going to
accomplish this by using the epicscorelibs_ python library, which is a 
dependency of ophyd-async. Make sure to follow the :doc:`installation tutorial
<installation>` first to ensure you have a virtual environment set up.
This tutorial will also make use of IPython, which should also be packaged in 
your virtual environment provided you have installed the dependencies.

Once you have activated the python virtual environment, open up an IPython REPL
and type:

.. code-block:: python

   import ophyd_async.epics.demo
   demo.start_ioc_subprocess("TEST")


This will start two IOCs - a sensor, and a motor with X and Y axes - and expose
their PVs via the EPICS protocol. If you have EPICS_ installed on your machine
you should now be able to type the following into a regular terminal:

.. code-block:: bash

   caget TEST:Mode
   caget TEST:X:Velocity
   caget TEST:Y:Readback

If this command doesn't work for you, it's probably because you don't have 
EPICS installed. For this tutorial, you don't have to have EPICS installed; you
can use ``aioca`` within an IPython terminal instead:

.. code-block:: python

   import aioca
   await aioca.caget("TEST:Mode")
   await aioca.caget("TEST:X:Velocity")
   await aioca.caget("TEST:Y:Readback")

The ``demo.start_ioc_subprocess`` function actually runs two .db files in the
background. These can be found in ``src/ophyd_async/epics/demo/`` in the 
``mover.db`` and ``sensor.db`` files. Here you can inspect all the PVs that are
exposed by each file, e.g. the sensor (prefixed by ``TEST:``) only has a 
``Mode`` and ``Value`` PV.

Notice the use of ``await``. Ophyd-async is an *asynchronous* hardware 
abstraction layer, which means it delegates control to python's asynchronous 
single-threaded event loop to run tasks concurrently. If any of these terms are
unfamiliar to you, you should consult the `official asyncio documentation`_. BBC
has a brilliant introduction into `Python's asynchronous logic`_, which is 
worth a read and accessible for beginners and more experienced programmers. 
Give it a look, and come back here when you are ready :)

What the demo EPICS IOCs actually do
------------------------------------
If you look at the ``mover.db`` and ``sensor.db`` files mentioned in the 
previous section, you can work out what each PV is actually doing. The sensor
has a ``Value`` PV which calculates some combinations of sine and cosine 
functions of ``X:Readback`` and ``Y:Readback`` PVs. Specifically, it outputs:

.. math::
   sin(x)^{10} + cos(E + xy)cos(x)

... where x and y represent the ``X:Readback`` and ``Y:Readback`` PVs 
respectively, and E is a value taken from the ``Mode`` PV. If the mode is set
to ``Low Energy`` (or 0), this is 10, and if it is set to ``High Energy`` (or 
1), it is 100.

Therefore, what we probably want to do with these PVs is move the X and Y
positions of the motor around in a grid scan, and get a heatmap of the
``Value`` PV to see the maxima and minima of this function.

Writing Devices to access PVs
-----------------------------
At this point, we have some PVs running in the background. By the end of this
section, we will encapsulate them in ophyd-async devices, and be able to 
control them without directly interacting with ``aioca`` as we have done above.

An ophyd-async ``Device`` is just a collection of PVs that can be coordinated 
to run plans. To connect an EPICS PV with such a device, we can use factory
functions that generate an ``ophyd_async.core.Signal`` which can have 4
flavours:

- ``SignalR`` which has the method ``.get_value()`` to get its value,
- ``SignalW`` which has the method ``.set(value)`` to set a value,
- ``SignalRW`` which subclasses both ``SignalR`` and ``SignalW`` and,
- ``SignalX`` which has a ``.trigger()`` method on to set the PV to None, which
  will execute it.

Each of these has a corresponding factory function to generate signals that
use the EPICS protocol, which can be imported from `ophyd_async.epics.signal` 
and includes ``epics_signal_$mode`` (where ``$mode`` is one of ``r``, ``w``, 
``rw`` or ``x``).

.. code-block:: python

   from ophyd_async.epics.signal import epics_signal_r
   signal = epics_signal_r(float, "TEST:Value")

Above, we call ``epics_signal_r`` with two arguments; the first describes the
type of value we are manipulating (in this case, a float). The second is the
PV name itself.

Notice the use of ``epics_signal_r`` instead of, e.g. ``epics_signal_rw``. This
is because the ``sensor.db`` file shows us the ``Value`` PV of our IOC is a
CALC record; we can ``caput`` to it, but it won't mean anything. So we should
only use this as a readable signal.

Try to read the value of this signal now:

.. code-block:: python

  await signal.get_value()

You should encounter an error telling you that you haven't connected it yet. 
To connect it, you should call ``signal.connect()`` in the bluesky event loop, 
which means the bluesky event loop should already be running. The easiest way 
to ensure this is to set up a RunEngine, ``RE = RunEngine()``.

.. code-block:: python

  from bluesky.run_engine import RunEngine, call_in_bluesky_event_loop

  RE = RunEngine()
  call_in_bluesky_event_loop(signal.connect())
  await signal.get_value()

So far, we have defined and connected a signal. Now try to write a device that
contains both ``TEST:Value`` and ``TEST:Mode`` PVs. To do this, you should make
a class that subclasses ``ophyd_async.core.Device``, and creates signals in its
constructor in a similar way to what has been demonstrated above.

To create a signal representing the ``TEST:Mode`` PV, the datatype will need to
be a defined Enum, containing both the ``Low Energy`` and ``High Energy``
values that this PV can accept. This Enum should subclass ``str`` as well.

.. code-block:: python

  from ophyd_async.core import Device
  from ophyd_async.epics.signal import epics_signal_rw
  from enum import Enum


  class EnergyMode(str, Enum):
      low = "Low Energy"
      high = "High Energy"


  class Sensor(Device):
      def __init__(self, prefix: str, name: str = "") -> None:
          self.mode = epics_signal_rw(EnergyMode, prefix + "Mode")
          self.value = epics_signal_r(float, prefix + "Value")
          super().__init__(name=name)


Note the call to ``super().__init__(self, name=name)`` in the ``Sensor``. This
is useful because a ``Device`` names itself and all of its children in its
constructor, and all devices (including ``Signal``-s) should be named to work
with Bluesky plans, as they will generate bluesky documents describing them.

As an exercise, try to write an ophyd device to describe the PVs in the
``mover.db`` file. You should include the ``Setpoint``, ``Velocity``, 
``Readback`` and ``Stop.PROC`` PVs, ensuring the last of these becomes a 
``SignalX``.

.. code-block:: python

  from ophyd_async.epics.signal import epics_signal_x

  class Mover(Device):
      def __init__(self, prefix: str, name: str = "") -> None:
          self.setpoint = epics_signal_rw(float, prefix + "Setpoint")
          self.readback = epics_signal_r(float, prefix + "Readback")
          self.velocity = epics_signal_rw(float, prefix + "Velocity")
          self.stop = epics_signal_x(prefix + "Stop.PROC")
          super().__init__(name=name)

As above, we can instantiate a ``Mover`` like so:

.. code-block:: python

   RE = RunEngine()
   mover_x = Mover("TEST:X:", "moverx")
   mover_y = Mover("TEST:Y:", "movery")
   call_in_bluesky_event_loop(mover_x.connect())
   call_in_bluesky_event_loop(mover_y.connect())
   await mover_x.velocity.get_value()
   await mover_y.readback.get_value()

It seems like a lot of effort to have to create the X and Y movers separately.
So, we can make a device that creates them together:

.. code-block:: python

  class SampleStage(Device):
      def __init__(self, prefix: str, name: str = "") -> None:
          self.x = Mover(prefix + "X:")
          self.y = Mover(prefix + "Y:")
          super().__init__(name=name)

... And use it:

.. code-block:: python


   from bluesky.run_engine import RunEngine, call_in_bluesky_event_loop

   RE = RunEngine()
   stage = SampleStage("TEST:", "stage")
   call_in_bluesky_event_loop(stage.connect())
   await stage.x.velocity.get_value()
   await stage.y.readback.get_value()

Experiment with setting the X and Y values, and see how it changes the sensor.
For example, you can set both X and Y setpoints to 10:

.. code-block:: python

   await stage.x.setpoint.set(10)
   await stage.y.setpoint.set(10)

... and check that the sensor reads the correct value:

.. code-block:: python

   E = 10 if await sensor.mode.get_value() == EnergyMode.low else 100
   X = await stage.x.readback.get_value()
   Y = await stage.y.readback.get_value()

   sensor_value = await sensor.value.get_value()
   assert np.sin(X)**10 + np.cos(E + Y*X) * np.cos(X)


Using plans and plan stubs
--------------------------
So far, all manipulation of PVs has been done through the ophyd layer. However,
we can do a similar thing using bluesky, without interacting with the 
``.get_value`` and ``.set`` methods on our signals:

.. code-block:: python

   import bluesky.plan_stubs as bps

   RE(bps.mv(stage.x.setpoint, 12, stage.y.setpoint, 8))

``bluesky.plans`` and ``bluesky.plan_stubs`` introduce more complex scanning 
logic to manipulate devices, using either `partial or complete recipes`_ of 
generated messages that get sent to the RunEngine. For example, ``bps.mv`` in
the above example generates a ``Msg("set", ...)`` for each pair of values it
receives, where the first of these is a device and the second is a value to set
this to.

Upon receiving this message, the RunEngine tries to call ``.set`` on the object,
which we get for free because ``stage.x`` is not just a ``ophyd_async.core.
Device`` but also a ``ophyd_async.core.signal.SignalW``, meaning it has a 
``.set`` already.

You can see how this works if we pass in a signal that doesn't have a ``.set``
method, like for example ``sensor.value``, which is readonly:

.. code-block:: python

   RE(bps.mv(sensor.value, 12))


You will see an assertion error, ``<object> does not implement all Movable 
methods``. ``Movable`` refers to a `bluesky protocol`_ that needs to be obeyed 
by a device in order for ``bps.mv`` to be run on it - protocols_ are similar to
abstract classes as they only define signatures of methods, rather than
implementations.

You can usually inspect plans and plan stubs, as well as their logic in the
RunEngine, to figure out what protocols need to be obeyed by a device. You may
also be able to try running a plan or plan stub with a device, and read the
error message to diagnose which protocol it needs, such as in the example 
above.

Running a gridscan
------------------
A bluesky plan already exists to allow running a grid scan with our devices.
This is ``bluesky.plans.grid_scan``, and it's call signature looks something
like:

.. code-block:: python

   RE(grid_scan([det1, det2, ...], motor1, start1, stop1, num1, ...))

... where ``det1`` and ``det2`` are detectors similar to our ``sensor`` object,
and ``motor1`` is a motor similar to our ``mover`` object. ``start1``, 
``stop1`` and ``num1`` indicate the range of values this motor should be
driven to, so values of 0, 1 and 2 respectively means the motor will be
driven to 0, 0.5 and 1.

At each stage of motor motion, the detectors ``det1`` and ``det2`` will be 
triggered.

For this plan to work, the ophyd devices above, ``Sensor`` and ``Mover``, will
have to change to allow for the following protocols for the ``Sensor``:

1. Readable, so that we can get event documents each time we collect data,
2. Stageable, so that we can plan how to setup and teardown the device for the 
   scan.

Note that all plans require their corresponding devices to be ``Stageable``,
because all plans will try to stage and unstage devices around the actual plan
logic.

Similarly, the ``Mover`` should be:

1. Both of the above; we also want event documents describing what the mover is
   doing.
2. Movable, so we can drive it to move to specific motor values,

As an exercise, have a go at trying to expand your existing definitions of
``Sensor`` and ``Mover`` so that they have these protocols, too. Both of these
objects should delegate to the existing methods that their signals have.
You will want to make use of ``ophyd_async.core.AsyncStatus`` for the ``stage``
and ``unstage`` methods, which can be used to wrap around the methods to return
a status that can be awaited on. See ``ophyd_async.core.SignalR`` for an 
example of this.

.. code-block:: python

   from bluesky.protocols import Reading, Descriptor, Readable, Stageable
   from typing import Dict
   from ophyd_async.core import AsyncStatus

   class Sensor(Device, Readable, Stageable):
       def __init__(self, prefix: str, name: str = "") -> None:
           self.mode = epics_signal_rw(EnergyMode, prefix + "Mode")
           self.value = epics_signal_r(float, prefix + "Value")
           super().__init__(name=name)

       async def read(self) -> Dict[str, Reading]:
           return {**(await self.mode.read()), **(await self.value.read())}

       async def describe(self) -> Dict[str, Descriptor]:
           return {**(await self.mode.describe()), **(await self.value.describe())}

       @AsyncStatus.wrap
       async def stage(self) -> None: 
           await self.mode.stage()
           await self.value.stage()
       
       @AsyncStatus.wrap
       async def unstage(self) -> None: 
           await self.mode.unstage()
           await self.value.unstage()


In the above, ``Sensor.stage`` and ``Sensor.unstage`` simply delegate to each 
``SignalR``-s ``.stage`` and ``.unstage`` methods. In this case, both 
``self.mode`` and ``self.value`` are instances of this class (recall that 
``SignalRW`` subclasses ``SignalR``).

Our ``Mover`` doesn't just have ``SignalR`` devices, however. It has a 
``SignalX``, too. This doesn't have a ``.stage`` or a ``.unstage`` method, nor
does it have ``.read`` or ``.describe``. With this in mind, the ``Mover`` can
be written as,

.. code-block:: python

   from bluesky.protocols import Movable
   from typing import Optional
   import asyncio
   import numpy as np
   from ophyd_async.core import observe_value
   
   class Mover(Device, Readable, Stageable, Movable):
       def __init__(self, prefix: str, name: str = "") -> None:
           self.setpoint = epics_signal_rw(float, prefix + "Setpoint")
           self.readback = epics_signal_r(float, prefix + "Readback")
           self.velocity = epics_signal_rw(float, prefix + "Velocity")
           self._stop = epics_signal_x(prefix + "Stop.PROC")
           super().__init__(name=name)

       async def read(self) -> Dict[str, Reading]:
           return {
               **(await self.readback.read()),
               **(await self.velocity.read())
           }

       async def describe(self) -> Dict[str, Descriptor]:
           return {
               **(await self.readback.describe()),
               **(await self.velocity.describe())
           }

       @AsyncStatus.wrap
       async def stage(self) -> None: 
           await self.readback.stage()
           await self.velocity.stage()
       
       @AsyncStatus.wrap
       async def unstage(self) -> None: 
           await self.readback.unstage()
           await self.velocity.unstage()

       async def _set(self, value: float):
           await self.setpoint.set(value, wait=False)

           async for current_position in observe_value(self.readback):
               if np.isclose(current_position, value):
                   break

       def set(self, value: float, timeout: Optional[float] = None) -> AsyncStatus:
           coro = asyncio.wait_for(self._set(value), timeout=timeout)
           return AsyncStatus(coro, [])

Notice in the above, that I have renamed ``self.stop`` to ``self._stop``. This
is because ``self.stop`` is actually reserved by the ``Stoppable`` protocol;
during the grid scan the RunEngine will check if it can call ``self.stop``. 
However, because of the limitations of python runtime typing systems, the 
RunEngine doesn't recognise the difference between a property and a method on
a class attribute; it will think ``self.stop`` is a method, not a ``SignalX``.

Also notice that ``.read`` and ``.describe`` do not include ``self.setpoint``.
This is deliberate; we want to capture the readback value, not the setpoint, 
to ensure the motor is doing what we expect it to be doing. 

Finally, notice the use of ``observe_value`` in ``self._set``. This returns an
async iterator, which yields values whenever the signal changes. Therefore,
whenever ``self.readback`` has a change in its value, it is yielded in this for
loop. This bit of logic ensures we only return from ``self._set`` when the
motor's readback value is close enough to what we asked it to be.

We can now try running our grid scan. First, let's look at the messages that
``bluesky.plans.grid_scan`` will emit with our system, after creating and
connecting these devices:

.. code-block:: python

  import bluesky.plans as bp

  sensor = Sensor("TEST:", "sensor")
  stage = SampleStage("TEST:", "stage")

  call_in_bluesky_event_loop(stage.connect())
  call_in_bluesky_event_loop(sensor.connect())

  list(bp.grid_scan([sensor], stage.x, 0, 2, 4, stage.y, 0, 2, 4))

It should be noted here that each device you use in a plan must have a unique
name, which includes giving it a name in the first place. Bluesky documents use
device names to configure python dictionaries, and overlapping keys are 
forbidden. If no name is given for both of these devices (the default), the 
RunEngine will recognize there are two devices with the same name (i.e. "") and
complain.

The above code snippet will generate all the messages ``bp.grid_scan`` would 
yield to the RunEngine, which can be useful to identify any errors in the plan 
itself.

For example, try doing:

.. code-block:: python

  list(bp.grid_scan([sensor], stage.x, 0, 2, 0.5, stage.y, 0, 2, 0.5))

... and you will see an error complaining because we have asked for a non-
integer number of images to be taken. Now, we are ready to run the grid scan!

.. code-block:: python

  RE(bp.grid_scan([sensor], stage.x, 0, 2, 4, stage.y, 0, 2, 4))

... did you see that? The result of this command should be a single output,
of the uid of the scan. We ran a grid scan! But how do we get information out
of it?

Subscriptions and documents
---------------------------
We can add subscriptions to the RunEngine which will give us more information
about the scan that is being run. For example, we can make a class that stores
all the documents produced, and subscribe to a bluesky utility, 
``BestEffortCallback``.

.. code-block:: python

   from bluesky.callbacks.best_effort import BestEffortCallback

   bec = BestEffortCallback()

   class DocHolder:
       def __init__(self):
           self.docs = []

       def __call__(self, name, doc):
           self.docs.append({"name": name, "doc": doc})

   holder = DocHolder()
   bec_subscription = RE.subscribe(bec)
   holder_subscription = RE.subscribe(holder)
   
   RE(bp.grid_scan([sensor], stage.x, 0, 2, 4, stage.y, 0, 2, 4))


You can now inspect the documents produced, by inspecting ``holder.docs``, and
should see a table of the results along each point in the grid scan. You can
write whatever subscriptions you want, including ones that make a live plot as
the scan progresses.


Using the StandardReadable
--------------------------

Congratulations! You have successfully made some ophyd devices to abstract 
EPICS IOCs, and run bluesky plans with them. However, I deliberately left out
some finer details that you may now care about. The attentive reader may have
noticed that any motor or detector they write will want to be ``Readable`` and
``Stageable``, and may think it's a bit of a chore to have to re-write this
every time they make a new device. Any readers more familiar with bluesky will
notice we haven't made any use of the concept of configuration signals, or the
``Configurable`` protocol. To help with this, ophyd-async comes with a class
called ``StandardReadable`` which subclasses these, and makes it easy to
produce the correct documents from each scan by grouping signals into readable
or configurable ones. Using this class, the Sensor can be re-written as:

.. code-block:: python

  class Sensor(StandardReadable):
      """A demo sensor that produces a scalar value based on X and Y Movers"""

      def __init__(self, prefix: str, name="") -> None:
          # Define some signals
          self.value = epics_signal_r(float, prefix + "Value")
          self.mode = epics_signal_rw(EnergyMode, prefix + "Mode")
          # Set name and signals for read() and read_configuration()
          self.set_readable_signals(
              read=[self.value],
              config=[self.mode],
          )
          super().__init__(name=name)

The only difference between this and the Sensor as we defined previously, is
now we have the ``Mode`` PV attached to a a configurational signal, instead
of a readable one. This just changes how it appears in documents - try this
definition out instead and notice the difference.

There are a few more enhancements that could be made ontop of the existing
``Mover`` device. First of all, we can also make this subclass 
``StandardReadable`` to get the same benefits of staging/unstaging behaviour,
and read/configuration signals. Secondly, we could include more PVs, for
example to describe the units we're working with - at the moment, we just have
a 'velocity' PV without knowing its units. We could also make our device
``Stoppable``, so that we could technically kill the motor motion if anything
goes wrong (and finally make use of the ``self.stop_`` PV...).

All of that and more is done in the ``ophyd_async.epics.demo`` module, in the
``__init__.py`` file, so have a look through that to observe the differences 
and experiment with what each of them do.


.. _epicscorelibs: https://github.com/mdavidsaver/epicscorelibs
.. _bluesky framework: https://blueskyproject.io/
.. _EPICS: https://epics-controls.org/resources-and-support/documents/getting-started/
.. _Python's asynchronous logic: https://bbc.github.io/cloudfit-public-docs/asyncio/asyncio-part-1.html
.. _protocols: https://mypy.readthedocs.io/en/stable/protocols.html
.. _bluesky protocol: https://github.com/bluesky/bluesky/blob/master/bluesky/protocols.py
.. _partial or complete recipes: https://blueskyproject.io/bluesky/plans.html
.. _official asyncio documentation: https://docs.python.org/3/library/asyncio.html
