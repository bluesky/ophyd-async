.. note::

   Ophyd async is included on a provisional basis until the v1.0 release and 
   may change API on minor release numbers before then

Make a StandardDetector
=======================

`StandardDetector` is an abstract class to assist in creating Device classes for hardware that writes its own data e.g. an AreaDetector implementation, or a PandA writing motor encoder positions to file.
The `StandardDetector` is a simple compound device, with 2 standard components: 

- `DetectorWriter` to handle data persistence, i/o and pass information about data to the RunEngine (usually an instance of :py:class:`HDFWriter`)
- `DetectorControl` with logic for arming and disarming the detector. This will be unique to the StandardDetector implementation.

Writing an AreaDetector StandardDetector
----------------------------------------

For an AreaDetector implementation of the StandardDetector, two entity objects which are subdevices of the `StandardDetector` are used to map to AreaDetector plugins:

- An NDPluginFile instance (for :py:class:`HDFWriter` an instance of :py:class:`NDFileHDF`)
- An :py:class:`ADBase` instance mapping to NDArray for the "driver" of the detector implementation


Define a :py:class:`FooDriver` if the NDArray requires fields in addition to those on :py:class:`ADBase` to be exposed. It should extend :py:class:`ADBase`.
Enumeration fields should be named to prevent namespace collision, i.e. for a Signal named "TriggerSource" use the enum "FooTriggerSource"

.. literalinclude:: ../examples/foo_detector.py
   :language: python
   :pyobject: FooDriver

Define a :py:class:`FooController` with handling for converting the standard pattern of :py:meth:`ophyd_async.core.DetectorControl.arm` and :py:meth:`ophyd_async.core.DetectorControl.disarm` to required state of :py:class:`FooDriver` e.g. setting a compatible "FooTriggerSource" for a given `DetectorTrigger`, or raising an exception if incompatible with the `DetectorTrigger`.

The :py:meth:`ophyd_async.core.DetectorControl.get_deadtime` method is used when constructing sequence tables for hardware controlled scanning. Details on how to calculate the deadtime may be only available from technical manuals or otherwise complex. **If it requires fetching from signals, it is recommended to cache the value during the StandardDetector `prepare` method.**

.. literalinclude:: ../examples/foo_detector.py
   :pyobject: FooController

:py:class:`FooDetector` ties the Driver, Controller and data persistence layer together. The example :py:class:`FooDetector` writes h5 files using the standard NDPlugin. It additionally supports the :py:class:`HasHints` protocol which is optional but recommended.

Its initialiser assumes the NSLS-II AreaDetector plugin EPICS address suffixes as defaults but allows overriding: **this pattern is recommended for consistency**.
If the :py:class:`FooDriver` signals that should be read as configuration, they should be added to the "config_sigs" passed to the super.

.. literalinclude:: ../examples/foo_detector.py
   :pyobject: FooDetector


Writing a non-AreaDetector StandardDetector
-------------------------------------------

A non-AreaDetector `StandardDetector` should implement `DetectorControl` and `DetectorWriter` directly.
Here we construct a `DetectorControl` that co-ordinates signals on a PandA PositionCapture block - a child device "pcap" of the `StandardDetector` implementation, analogous to the :py:class:`FooDriver`.

.. literalinclude:: ../../src/ophyd_async/panda/_panda_controller.py
   :pyobject: PandaPcapController

The PandA may write a number of fields, and the :py:class:`PandaHDFWriter` co-ordinates those, configures the filewriter and describes the data for the RunEngine.

.. literalinclude:: ../../src/ophyd_async/panda/writers/_hdf_writer.py
   :pyobject: PandaHDFWriter

The PandA StandardDetector implementation simply ties the component parts and its child devices together.

.. literalinclude:: ../../src/ophyd_async/panda/_hdf_panda.py
   :pyobject: HDFPanda
