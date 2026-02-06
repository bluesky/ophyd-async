# How to implement a Device for an EPICS areaDetector

This document will walk through the steps taken to implement an ophyd-async Device that talks to an EPICS areaDetector

## Create a module to put the code in

The first stage is to make a module in the `ophyd-async` repository to put the code in:

- If you haven't already, `git clone git@github.com:bluesky/ophyd-async.git` and make a new branch to work in
- Create a new file under `src/ophyd_async/epics/` which is the lowercase version of the epics support module for the detector
  - For example, for [`ADAravis`](https://github.com/areaDetector/ADAravis) make a file `adaravis.py`

## Add an IO class for the PV interface

Now you need an IO class that subclasses [](#adcore.ADBaseIO). This should add the PVs that are detector driver specific that are required to setup triggering. 

For example for ADAravis this would include signals for trigger mode, trigger source, and any detector-specific settings.

## Add Trigger Logic for detector-specific triggering

Now you need a class that subclasses [](#DetectorTriggerLogic). This should implement methods for each trigger mode your detector supports:
- `prepare_internal(num, livetime, deadtime)` - Setup for internal triggering (detector generates its own triggers)
- `prepare_edge(num, livetime)` - Setup for external edge triggering (rising edge starts an internally-timed exposure)
- `prepare_level(num)` - Setup for external level/gate triggering (high level duration determines exposure time)

If the detector has configuration values that should be captured in the scan then implement:
- `config_sigs()` - Return the set of signals that should appear in read_configuration()

If you support external triggering you should also implement:
- `get_deadtime(config_values)` - Calculate the minimum time between exposures based on configuration values

Only implement the prepare methods for trigger modes your detector actually supports. The detector will automatically report which trigger types are available based on which methods are implemented.

For example, for ADAravis:
```{literalinclude} ../../src/ophyd_async/epics/adaravis.py
:language: python
:pyobject: AravisTriggerLogic
```

## Use ADArmLogic or create custom Arm Logic

Most areaDetectors can use the standard [](#adcore.ADArmLogic) which handles arming and disarming via the driver's `acquire` signal. If your detector requires custom arming behavior (e.g., waiting for a specific ready signal), create a [](#DetectorArmLogic) subclass with:
- `arm()` - Start acquisition
- `wait_for_idle()` - Wait until acquisition is complete
- `disarm()` - Stop acquisition

## Add a Detector that puts it all together

Now you need to make an [](#adcore.AreaDetector) subclass that uses your IO and Trigger Logic with the standard Arm Logic and Writer classes that come with ADCore. The `__init__` method should:
1. Create the driver IO instance
2. Create instances of your logic classes
3. Call `super().__init__()` passing the driver and logic instances to the baseclass

The constructor parameters should include:
- `prefix`: The PV prefix for the driver and plugins
- `path_provider`: A [](#PathProvider) that tells the detector where to write data (optional if `writer_type=None`)
- `driver_suffix`: A PV suffix for the driver, defaulting to `"cam1:"`
- `writer_type`: An [](#adcore.ADWriterType) enum value (HDF, TIFF, JPEG) or None to skip file writing
- `writer_suffix`: An optional PV suffix for the file writer plugin
- `plugins`: An optional mapping of {`name`: [](#adcore.NDPluginBaseIO)} for additional plugins
- `config_sigs`: Additional signals to report in configuration (beyond the standard acquire_time and acquire_period)
- `name`: An optional name for the device
- Any detector-specific override parameters for your trigger logic

For example, for ADAravis:
```{literalinclude} ../../src/ophyd_async/epics/adaravis.py
:language: python
:pyobject: AravisDetector
```

The `AreaDetector` baseclass will:
- Store the driver as `self.driver`
- Call `add_logics()` to register your trigger and arm logic
- Create and register a data logic for file writing if `writer_type` is not None
- Add configuration signals (driver.acquire_time, driver.acquire_period, and any you specify)
- Store any plugins as attributes on the detector

## Declare the public interface

Now you should take all the classes you've made and add them to the top level `__all__`. Typically you should export:
- The detector class (e.g., `AravisDetector`)
- The driver IO class (e.g., `AravisDriverIO`)
- The trigger logic class (e.g., `AravisTriggerLogic`)
- Any custom Enum types for PV values (e.g., `AravisTriggerSource`)

For example, for ADAravis:
```{literalinclude} ../../src/ophyd_async/epics/adaravis.py
:language: python
:start-at: __all__
:end-at: ]
```

## Add multiple data streams (optional)

The composition-based architecture makes it possible to add multiple data outputs to a detector. After creating the detector, you can call `add_logics()` to add additional data sources:

### Reading stats plugins alongside file writing
```python
from ophyd_async.epics.adcore import PluginSignalDataLogic

det = adaravis.AravisDetector(prefix, path_provider)
# Add stats total as a readable signal in events
det.add_logics(adcore.PluginSignalDataLogic(det.driver, det.stats.total))
```

### Multiple HDF writers for different ROIs
```python
# Don't create default writer
det = adaravis.AravisDetector(prefix, writer_type=None)  
# Add separate writers for each ROI
det.add_logics(
    adcore.ADHDFDataLogic(path_provider, det.driver, det.roi1_plugin, datakey_suffix="-roi1"),
    adcore.ADHDFDataLogic(path_provider, det.driver, det.roi2_plugin, datakey_suffix="-roi2"),
)
```

## Continuously acquiring detector

For detectors that acquire continuously, use [](#adcore.ADContAcqTriggerLogic) instead of creating custom trigger logic. This uses the builtin `areaDetector` [circular buffer plugin](https://areadetector.github.io/areaDetector/ADCore/NDPluginCircularBuff.html) to capture frames while the detector runs continuously.

Requirements:
- Your AD IOC must have a circular buffer plugin configured
- The plugin output should be fed to the file writer
- The detector should already be acquiring continuously before use

Example implementation:
```python
driver = adcore.ADBaseIO("PREFIX:DRV:")
cb_plugin = adcore.NDCircularBuffIO("PREFIX:CB1:")
det = adcore.AreaDetector(
    driver=driver,
    arm_logic=adcore.ADContAcqArmLogic(driver, cb_plugin),
    trigger_logic=adcore.ADContAcqTriggerLogic(driver, cb_plugin),
    path_provider=path_provider,
    plugins={"cb1": cb_plugin},
)
```

The [](#adcore.ADContAcqTriggerLogic) will:
- Validate that exposure time matches the detector's current acquisition period
- Configure the circular buffer plugin to capture the requested number of frames
- Use the circular buffer's trigger signal instead of the driver's acquire signal


## Write tests

Write unit tests to verify your detector implementation works correctly. You should test:

### Test fixture setup

Use a pytest fixture to initialize your detector in mock mode for testing:

```{literalinclude} ../../tests/unit_tests/epics/test_adaravis.py
:language: python
:pyobject: test_adaravis
```

This fixture:
- Initializes the detector with `mock=True` for unit testing
- Sets up required mock values (e.g., `file_path_exists`)
- Returns the detector for use in test functions

### Test PV correctness

Verify that your detector driver correctly maps to the expected PV names:

```{literalinclude} ../../tests/unit_tests/epics/test_adaravis.py
:language: python
:pyobject: test_pvs_correct
```

### Test deadtime calculation

If your detector supports external triggering, test the `get_deadtime()` method for different detector models and configurations:

```{literalinclude} ../../tests/unit_tests/epics/test_adaravis.py
:language: python
:pyobject: test_deadtime
```

### Test prepare methods

Test each trigger mode your detector supports by verifying that `prepare()` configures the detector with the correct PV values. Test external edge triggering:

```{literalinclude} ../../tests/unit_tests/epics/test_adaravis.py
:language: python
:pyobject: test_prepare_external_edge
```

And test internal triggering:

```{literalinclude} ../../tests/unit_tests/epics/test_adaravis.py
:language: python
:pyobject: test_prepare_internal
```

## Conclusion

You have now made a detector, and can import and create it like this:

```python
from ophyd_async.epics import adaravis

det = adaravis.AravisDetector("PREFIX:", path_provider)
```

The detector will now support:
- Querying supported trigger types with `get_trigger_deadtime()`
- Step scanning with `trigger()` 
- Fly scanning with `kickoff()` and `complete()`
- Automatic handling of file writing and StreamAsset document emission
- Configuration signal reporting based on your trigger logic
