.. note::

   Ophyd async is included on a provisional basis until the v1.0 release and 
   may change API on minor release numbers before then

Write Tests for Devices
=======================

Testing ophyd-async devices using tools like mocking, patching, and fixtures can become complicated very quickly. The library provides several utilities to make it easier.

Sim Backend
-----------

Ophyd devices initialized with a sim backend behave in a similar way to mocks, without requiring you to mock out all the dependencies and internals. The :class:`~ophyd-async.core.DeviceCollector` can initialize any number of devices, and their signals and sub-devices (recursively), with a sim backend.

.. literalinclude:: ../../../tests/epics/demo/test_demo.py
   :pyobject: sim_sensor

Sim signals behave as simply as possible, holding a sensible default value when initialized and retaining any value (in memory) to which they are set. This model breaks down in the case of read-only signals, which cannot be set because there is an expectation of some external device setting them in the real world. There is a utility function, ``set_sim_value``, to mock-set values for sim signals, including read-only ones.

.. literalinclude:: ../../../tests/epics/demo/test_demo.py
   :pyobject: test_sensor_reading_shows_value


There is another utility function, ``set_sim_callback``, for hooking in logic when a sim value changes (e.g. because someone puts to it).

.. literalinclude:: ../../../tests/epics/demo/test_demo.py
   :pyobject: test_mover_stopped
