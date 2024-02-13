Create Detectors
================

.. currentmodule:: ophyd_async.core

Detectors often require standard bits of functionality to work with bluesky,
for this reason ophyd-async comes with a `StandardDetector` that can be
used or expanded upon
A StandardDetector needs two crucial components; a `DetectorControl` object and
a `DetectorWriter`.

The former is responsible for arming and disarming the detector, whereas the 
latter is responsible for handling any data writing, for example a HDF writer.

The `ophyd_async.epics.areadetector` module contains examples of common
detector controllers and writers.

Writing a detector controller
-----------------------------
The `DetectorControl` protocol contains three methods that must be defined for
any implementation of it:

.. literalinclude:: ../../../src/ophyd_async/core/detector.py
   :pyobject: DetectorControl

`DetectorControl.get_deadtime` should return a float, in seconds, of the 
detector deadtime. This will usually be restricted by the detector hardware you
are using.

`DetectorControl.arm` takes one argument, and two keyword arguments:

- ``num`` indicates the number of images that will be taken,
- ``trigger`` indicates the type of trigger which the detector will receive,
- ``exposure`` is the exposure time, i.e. time between frames.

.. literalinclude:: ../../../src/ophyd_async/core/detector.py
   :pyobject: DetectorTrigger

`DetectorTrigger.internal` is the default trigger mode, which aligns with
step-scanning methods (i.e. something pokes the PV from the software side, to
tell it to take pictures).

`DetectorControl.disarm` takes no arguments, and simply re-sets the state of
the detector.


:mod:`ophyd_async.epics.areadetector.controllers` contains some 
examples of how this class is implemented. Because a controller needs to be 
able to start and stop detector frame collection (although it is not 
responsible for how and where these frames are stored; that is the 
responsibility of the `detector writer <#writing-a-detector-writer>`_), in 
practice it should be passed a driver.
 
Below is an example of an implementation of a controller for an area detector.

.. literalinclude:: ../../../src/ophyd_async/epics/areadetector/controllers/ad_sim_controller.py
   :pyobject: ADSimController


Note:

- The use of `asyncio.gather`: this ensures some operations happen in parallel,
  or as close to parallel as python's asyncio logic allows.
- The driver is passed into the constructor. The next subsection contains
  details on how to write your own drivers.
- You should place assertions of `DetectorTrigger` in `DetectorControl.arm`, 
  especially if you only intend for your detector to be used in step or fly
  scans. If you can use them for both, ensure to write the logic as such.
- :mod:`ophyd_async.epics.areadetector.drivers.ad_base.start_acquiring_driver_and_ensure_status`
  starts scquiring the driver, and checks that the detector state is valid
  before completing (when it is awaited on).
- The disarm method uses :mod:`ophyd_async.epics.areadetector.utils.stop_busy_record` to stop the
  aquisition (without a caput callback) and wait for it to have stopped with a
  timeout.

When writing your own driver, make sure you start acquiring the driver and stop
it in exactly the same way as done in the above example; this will ensure the
RunEngine does not deadlock.

Writing a driver
^^^^^^^^^^^^^^^^

drivers are just ophyd-async `Device` instances that interface with detector
acquisition. In the above example for the areadetector, the driver used closely
follows the `areaDetector simulator`_ specification, which is why its
definition has a non trivial subclassing hierarchy. You are free to not do this
for your own devices: this is only included for extensibility of drivers in 
future and compatibility with Malcolm (Diamonds current internal fly-scanning
system).

Your driver just needs enough PVs to allow the controller to do it's job, that
is to start and stop acquiring frames. Create it like any regular device.


Writing a detector writer
-------------------------

Detector writers define how data is stored, that is, how files are opened and
closed, and how they keep track of the number of frames written. This becomes
especially important for fly scanning.

`DetectorWriter` implementations must have the following methods:

- `DetectorWriter.open`, to open a file for writing,
- `DetectorWriter.close` to open the file after writing has finished,
- `DetectorWriter.get_indices_written` to get the number of frames that have
  been written already by whichever plugin is being used (e.g. a hdf plugin)
- `DetectorWriter.wait_for_index` to wait for the number of frames to reach a
  certain value, and
- `DetectorWriter.collect_stream_docs` which should yield stream resource or
  stream datum documents, aggregating a certain number of frames together.

As for the `detector controller <#writing-a-detector-controller>`_, the
detector writer should not directly poke PVs in these methods but instead
delegate this role to a `hdf plugin <#writing-a-hdf-plugin-or-equivalent>`_.

Here is an example of a detector writer for creating HDF files:

.. literalinclude:: ../../../src/ophyd_async/epics/areadetector/writers/hdf_writer.py
   :pyobject: HDFWriter

Note:

- Just as with the `driver <#writing-a-driver>`_ for a `DetectorControl`
  instance, writers should delegate all PV poking logic to a plugin which does
  the file writing on the EPICS side. That is, the `DetectorWriter` itself
  should not perform any file I/O but instead understand how the underlying 
  EPICS layer does it, and delegate to this instead. In the above case, this is
  a hdf plugin since we are writing a HDF file.
- A directory provider is passed into the constructor, which is used to
  configure the plugin with the correct path to write data to. This is an
  optional step, but recommended.
- A name provider is passed into the constructor, which is used to generate a
  unique name for each dataset in the descriptor document,
- A shape provider is passed into the constructor, which is used to determine
  the ``dtype`` for each entry in the generated descriptor document.

Writing a hdf plugin or equivalent
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To write a plugin, simply make an ophyd-async device which contains all the
PVs necessary for the `DetectorWriter` to handle opening and closing files,
as well as keeping track of the number of frames written. 

:mod:`ophyd_async.epics.areadetector.writers.hdf_writer.HDFWriter`, uses the 
:mod:`ophyd_async.epics.areadetector.writers.nd_file_hdf.NDFileHDF` plugin:


.. literalinclude:: ../../../src/ophyd_async/epics/areadetector/writers/nd_file_hdf.py
   :pyobject: NDFileHDF


Instantiating a detector
------------------------

An example of a simple detector looks like the following:

.. literalinclude:: ../../../src/ophyd_async/epics/demo/demo_ad_sim_detector.py
   :pyobject: DemoADSimDetector

Note:

- a driver and plugin are passed into the constructor, which only creates the
  `DetectorWriter` and `DetectorControl` instances as it's passing them to the
  superclass.
- directory provider, name provider and shape provider are optional, that is
  they don't have to be passed through the constructor. As an example, the
  shape provider in this instance is always 
  :mod:`ophyd_async.epics.areadetector.drivers.ADBaseShapeProvider`.

`DetectorWriter` and `DetectorControl` are just bits of logic that should 
exist in a `StandardDetector`, and are not themselves ophyd-devices. Because
connecting (and naming) a top level device means all the children of the device
get named and connected also, it is preferred to only create these objects when
calling ``super().__init__`` as done above, and make the driver and plugin 
attributes of the `StandardDetector`. This way, when the instance of 
``DemoADSimDetector`` gets connected and named, all underlying child devices in
the driver and plugin are correctly connected and named also. If we missed this
step we would have to individually name and connect them, which is a faff.

That is, to instantiate this detector:

.. code-block:: python

   from bluesky.run_engine import RunEngine, call_in_bluesky_event_loop

   from ophyd_async.epics.areadetector.drivers import ADBase
   from ophyd_async.epics.areadetector.writers import NDFileHDF
   from ophyd_async.epics.demo.demo_ad_sim_detector import DemoADSimDetector
   
   from ophyd_async.core import StaticDirectoryProvider

   RE = RunEngine()

   driver = ADBase("PREFIX:Driver", name="driver")
   plugin = NDFileHDF("PREFIX:Plugin", name="plugin")

   dp = StaticDirectoryProvider("/some/path", "some_filename")

   detector = DemoADSimDetector(driver, plugin, dp, name="detector")
   call_in_bluesky_event_loop(detector.connect(sim=True))

Note that in the above, the directory provider used is a 
`StaticDirectoryProvider`, which requires a path and filename to be used
for storing data from the hdf plugin. Recall that the `DetectorWriter` itself
does nothing with this information; it instead passes this to the plugin, which
updates epics PVs. This means the validation happens at an EPICS level - it is 
good practise to ensure your `DetectorWriter` has some way of checking that the
file you passed to it is valid, perhaps by watching another PV as is done in
the ``HDFWriter``.

It also means if you run the above code, nothing will actually get written, as
we have specified ``sim=True`` which means no connections to EPICS PVs will
be established.

.. _areaDetector simulator: https://millenia.cars.aps.anl.gov/software/epics/simDetectorDoc.html
