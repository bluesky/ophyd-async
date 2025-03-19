# How to implement a Device for an EPICS areaDetector

This document will walk through the steps taken to implement an ophyd-async Device that talks to an EPICS areaDetector

## Create a module to put the code in

The first stage is to make a module in the `ophyd-async` repository to put the code in:

- If you haven't already, `git clone git@github.com:bluesky/ophyd-async.git` and make a new branch to work in
- Create a new directory under `src/ophyd_async/epics/` which is the lowercase version of the epics support module for the detector
  - For example, for [`ADAravis`](https://github.com/areaDetector/ADAravis) make a directory `adaravis`
- Make an empty `__init__.py` within that directory

## Add an IO class for the PV interface

Now you need an IO class that subclasses [](#adcore.ADBaseIO). This should add the PVs that are detector driver specific that are required to setup triggering. 

For example for ADAravis this is in the file `_aravis_io.py`:
```{literalinclude} ../../src/ophyd_async/epics/adaravis/_aravis_io.py
:language: python
```

## Add a Controller that knows how to setup the driver

Now you need a class that subclasses [](#adcore.ADBaseController). This should implement at least:
- `get_deadtime()` to give the amount of time required between triggers for a given exposure
- `prepare()` to set the camera up for a given trigger mode, number of frames and exposure 

For example for ADAravis this is in the file `_aravis_controller.py`:
```{literalinclude} ../../src/ophyd_async/epics/adaravis/_aravis_controller.py
:language: python
```

## Add a Detector that puts it all together

Now you need to make a [](#StandardDetector) subclass that uses your IO and Controller with the standard file IO and Writer classes that come with ADCore. The `__init__` method should take the following:
- `prefix`: The PV prefix for the driver and plugins
- `path_provider`: A [](#PathProvider) that tells the detector where to write data
- `drv_suffix`: A PV suffix for the driver, defaulting to `"cam1:"`
- `writer_cls`: An [](#adcore.ADWriter) class to instantiate, defaulting to [](#adcore.ADHDFWriter)
- `fileio_suffix`: An optional PV suffix for the fileio, if not given it will default to the writer class default
- `name`: An optional name for the device
- `config_sigs`: Optionally the signals to report as configuration
- `plugins`: An optional mapping of {`name`: [](#adcore.NDPluginBaseIO)} for each additional plugin that might contribute data to the resulting file

For example for ADAravis this is in the file `_aravis.py`:
```{literalinclude} ../../src/ophyd_async/epics/adaravis/_aravis.py
:language: python
```

## Make it importable

Now you should take all the classes you've made and add it to the top level `__init__.py` to declare the public interface for this module. Typically you should also include any Enum types you have made to support the IO.

For example for ADAravis this is:
```{literalinclude} ../../src/ophyd_async/epics/adaravis/__init__.py
:language: python
```

## Write tests

TODO

## Conclusion

You have now made a detector, and can import and create it like this:

```python
from ophyd_async.epics import adaravis, adcore


det = adaravis.AravisDetector(
   "PREFIX:", 
   path_provider, 
   drv_suffix="DRV:", 
   writer_cls=adcore.ADHDFWriter, 
   fileio_suffix="HDF:",
)
```

## Continuously acquiring detector

In the event that you need to be able to collect data from a detector that is continuously acquiring, you should use the `ContAcqAreaDetector` class.
This uses the builtin `areaDetector` [circular buffer plugin](https://areadetector.github.io/areaDetector/ADCore/NDPluginCircularBuff.html) to act as the acquisition start/stop replacement, while the detector runs continuously.

Your AD IOC will require at least one instance of this plugin to be configured, and the output of the plugin should be fed to the file writer of your choosing.
The expectation is that the detector is already acquiring in continuous mode with the expected exposure time prior to using an instance of `ContAcqAreaDetector`.

To instantiate a detector instance, import it and create it like this:

```python
from ophyd_async.epics import adcore

det = adcore.ContAcqAreaDetector(
   "PREFIX:", 
   path_provider, 
   drv_cls=adcore.ADBaseIO,
   drv_suffix="DRV:", 
   cb_suffix="CB:",
   writer_cls=adcore.ADHDFWriter, 
   fileio_suffix="HDF:",
)
```

Note that typically the only changes from a typical detector are the additional `cb_suffix` kwarg, which is used to identify the prefix to use when instantiating the circular buffer (CB) plugin instance, and the `drv_cls` kwarg, which allows you to specify the driver to use, with the default being the `ADBaseIO` class.
