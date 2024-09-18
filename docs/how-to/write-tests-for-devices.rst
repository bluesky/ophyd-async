.. note::

   Ophyd async is included on a provisional basis until the v1.0 release and
   may change API on minor release numbers before then

Write Tests for Devices
=======================

Testing ophyd-async devices using tools like mocking, patching, and fixtures can become complicated very quickly. The library provides several utilities to make it easier.

Async Tests
-----------

`pytest-asyncio <https://github.com/pytest-dev/pytest-asyncio>`_ is required for async tests. It is should be included as a dev dependency of your project. Tests can either be decorated with ``@pytest.mark.asyncio`` or the project can be automatically configured to detect async tests.

.. code:: toml

   # pyproject.toml

   [tool.pytest.ini_options]
   ...
   asyncio_mode = "auto"

Mock Backend
------------

Ophyd devices initialized with a mock backend behave in a similar way to mocks, without requiring you to mock out all the dependencies and internals. The `DeviceCollector` can initialize any number of devices, and their signals and sub-devices (recursively), with a mock backend.

.. literalinclude:: ../../tests/epics/demo/test_demo.py
   :pyobject: mock_sensor


Mock Utility Functions
----------------------

Mock signals behave as simply as possible, holding a sensible default value when initialized and retaining any value (in memory) to which they are set. This model breaks down in the case of read-only signals, which cannot be set because there is an expectation of some external device setting them in the real world. There is a utility function, ``set_mock_value``, to mock-set values for mock signals, including read-only ones.

In addition this example also utilizes helper functions like ``assert_reading`` and ``assert_value`` to ensure the validity of device readings and values. For more information see: :doc:`API.core<../_api/ophyd_async.core>`

.. literalinclude:: ../../tests/epics/demo/test_demo.py
   :pyobject: test_sensor_reading_shows_value


Given that the mock signal holds a ``unittest.mock.Mock`` object you can retrieve this object and assert that the device has been set correctly using ``get_mock_put``. You are also free to use any other behaviour that ``unittest.mock.Mock`` provides, such as in this example which sets the parent of the mock to allow ordering across signals to be asserted:

.. literalinclude:: ../../tests/epics/demo/test_demo.py
   :pyobject: test_retrieve_mock_and_assert

There are several other test utility functions:

Use ``callback_on_mock_put``, for hooking in logic when a mock value changes (e.g. because someone puts to it). This can be called directly, or used as a context, with the callbacks ending after exit.

.. literalinclude:: ../../tests/epics/demo/test_demo.py
   :pyobject: test_mover_stopped


Testing a Device in a Plan with the RunEngine
---------------------------------------------
.. literalinclude:: ../../tests/epics/demo/test_demo.py
   :pyobject: test_sensor_in_plan


This test verifies that the sim_sensor behaves as expected within a plan. The plan we use here is a ``count``, which takes a specified number of readings from the ``sim_sensor``. Since we set the ``repeat`` to two in this test, the sensor should emit two "event" documents along with "start", "stop" and "descriptor" documents. Finally, we use the helper function ``assert_emitted`` to confirm that the emitted documents match our expectations.
