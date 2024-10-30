.. note::

   Ophyd async is included on a provisional basis until the v1.0 release and 
   may change API on minor release numbers before then

Compound Devices Together
=========================

Assembly
--------

Compound assemblies can be used to group Devices into larger logical Devices:

.. literalinclude:: ../../src/ophyd_async/epics/demo/_mover.py
   :pyobject: SampleStage

This applies prefixes on construction:

- SampleStage is passed a prefix like ``DEVICE:``
- SampleStage.x will append its prefix ``X:`` to get ``DEVICE:X:``
- SampleStage.x.velocity will append its suffix ``Velocity`` to get
  ``DEVICE:X:Velocity``

If SampleStage is further nested in another Device another layer of prefix nesting would occur

.. note::

   SampleStage does not pass any signals into its superclass init. This means
   that its ``read()`` method will return an empty dictionary. This means you
   can ``rd sample_stage.x``, but not ``rd sample_stage``.


Grouping by Index
-----------------

Sometimes, it makes sense to group devices by number, say an array of sensors:

.. literalinclude:: ../../src/ophyd_async/epics/demo/_sensor.py
   :pyobject: SensorGroup

:class:`~ophyd-async.core.DeviceVector` allows writing maintainable, arbitrary-length device groups instead of fixed classes for each possible grouping. A :class:`~ophyd-async.core.DeviceVector` can be accessed via indices, for example: ``my_sensor_group.sensors[2]``. Here ``sensors`` is a dictionary with integer indices rather than a list so that the most semantically sensible indices may be used, the sensor group above may be 1-indexed, for example, because the sensors' datasheet calls them "sensor 1", "sensor 2" etc. 

.. note::
   The :class:`~ophyd-async.core.DeviceVector` adds an extra level of nesting to the device tree compared to static components like ``sensor_1``, ``sensor_2`` etc. so the behavior is not completely equivalent.
