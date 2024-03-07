Device Collector Event-Loop Choice
----------------------------------

In a sync context, the ophyd-async :python:`DeviceCollector` requires the bluesky event-loop
to connect to devices. In an async context, it does not.

Sync Context
============

In a sync context the run-engine must be initialized prior to connecting to devices.
We enfore usage of the bluesky event-loop in this context.

The following will fail if :python:`RE = RunEngine()` has not been called already:

.. code:: python

  with DeviceCollector():
      device1 = Device1(prefix)
      device2 = Device2(prefix)
      device3 = Device3(prefix)

The :python:`DeviceCollector` connects to devices in the event-loop created in the run-engine.


Async Context
=============

In an async context device connection is decoupled from the run-engine.
The following attempts connection to all the devices in the :python:`DeviceCollector`
before or after run-engine initialization.

.. code:: python

  async def connection_function() :
      async with DeviceCollector():
          device1 = Device1(prefix)
          device2 = Device2(prefix)
          device3 = Device3(prefix)

  asyncio.run(connection_function())

The devices will be unable to be used in the run-engine unless they share the same event-loop.
When the run-engine is initialised it will create a new background event-loop to use if one
is not passed in with :python:`RunEngine(loop=loop)`.

If the user wants to use devices in the async :python:`DeviceCollector` within the run-engine
they can either:

* Run the :python:`DeviceCollector` first and pass the event-loop into the run-engine.
* Initialize the run-engine first and run the :python:`DeviceCollector` using the bluesky event-loop.


