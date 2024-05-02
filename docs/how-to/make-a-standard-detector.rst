.. note::

   Ophyd async is included on a provisional basis until the v1.0 release and 
   may change API on minor release numbers before then

Make a StandardDetector
=======================

.. currentmodule:: ophyd_async.core

`StandardDetector` is an abstract class to assist in creating devices to control EPICS AreaDetector implementations.
The `StandardDetector` is a simple compound device, with 2 standard components: 

- `DetectorWriter` to handle data persistence, i/o and pass information about data to the RunEngine (usually an instance of `HDFWriter`)
- `DetectorControl` with logic for arming and disarming the detector. This will be unique to the StandardDetector implementation.

These standard components are not devices, and therefore not subdevices of the `StandardDetector`, typically they are enabled by the use of two other components which are:

- An implementation of `NDPluginBase`, an entity object mapping to an AreaDetector NDPluginFile instance (for `HDFWriter` an instance of `NDFileHDF`)
- `ADBase`, or an class which extends it, an entity object mapping to an AreaDetector "NDArray" for the "driver" of the detector implementation

Writing a StandardDetector implementation
-----------------------------------------

Define a `FooDriver` if the NDArray requires fields in addition to those on `ADBase` to be exposed. It should extend `ADBase`.
Enumeration fields should be named to prevent namespace collision, i.e. for a Signal named "TriggerSource" use the enum "FooTriggerSource"

.. literalinclude:: ../examples/foo_detector.py
   :pyobject: FooDriver

Define a `FooController` with handling for converting the standard pattern of `arm` and `disarm` to required state of `FooDriver` e.g. setting a compatible `FooTriggerSource` for a given `DetectorTrigger`, or raising an exception if incompatible with the `DetectorTrigger`.
The `get_deadtime` method is used when constructing sequence tables for hardware controlled scanning. Details on how to calculate the deadtime may be only available from technical manuals or otherwise complex. **In the case that it requires fetching values from signals, it is recommended to cache the value during the StandardDetector `prepare` method.**

.. literalinclude:: ../examples/foo_detector.py
   :pyobject: FooController

Assembly
--------

Define a `FooDetector` implementation to tie the Driver, Controller and data persistence layer together. The example `FooDetector` writes h5 files using the standard NDPlugin. It additionally supports the `HasHints` protocol which is optional but recommended.
Its initialiser assumes the NSLS-II AreaDetector plugin EPICS address suffixes as defaults but allows overriding: **this pattern is recommended for consistency**.
If the `FooDriver` exposed any `Signal`s that should be read as configuration, they should be added to the `config_sigs`.

.. literalinclude:: ../examples/foo_detector.py
   :pyobject: FooDetector
