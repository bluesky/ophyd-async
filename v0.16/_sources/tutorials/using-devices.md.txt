# Using Devices

In this tutorial we will create a bluesky RunEngine, instantiate some existing ophyd-async Devices, and use them in some bluesky plans. It assumes you have already run through the Bluesky tutorial on [](inv:bluesky#tutorial_run_engine_setup).

## Run the demo

Ophyd-async ships with some simulated devices and a demo script that will create them along with a RunEngine. Let's take a look at it now:
```{literalinclude} ../../src/ophyd_async/sim/__main__.py
:language: python
```

We will explain the contents in more detail later on, but for now let's run it in an interactive [ipython](https://ipython.org) shell:
```
$ ipython --matplotlib=qt6 -i -m ophyd_async.sim
Python 3.11.11 (main, Dec  4 2024, 20:38:25) [GCC 12.2.0]
Type 'copyright', 'credits' or 'license' for more information
IPython 8.30.0 -- An enhanced Interactive Python. Type '?' for help.

In [1]: 
```

This has launched an ipython shell, enabled live plotting, told it to import and run the demo script packaged inside `ophyd_async.sim`, then return to an interactive prompt.

## Investigate the Devices

We will look at the `stage.x` and `y` motors first. If we examine them we can see that they have a name:
```python
In [1]: stage.x.name
Out[1]: 'stage-x'
```

But if we try to call any of the other methods like `read()` we will see that it doesn't return the value, but a [coroutine](inv:python:std:label#coroutine):

```python
In [2]: stage.x.read()
Out[2]: <coroutine object StandardReadable.read at 0x7f9c5c105220>
```

This is because ophyd-async devices implement async versions of the bluesky [verbs](inv:bluesky#hardware). To get the value we can `await` it:
 ```python
In [3]: await stage.x.read()
Out[3]: 
{'x-user_readback': {'value': 0.0,
  'timestamp': 367727.615860209,
  'alarm_severity': 0}}
```

## Run some plans

Although it is useful to run the verbs using the `await` syntax for debugging, most of the time we will run them via plans executed by the [](#bluesky.run_engine.RunEngine). For instance we can read it using the [`bps.rd`](#bluesky.plan_stubs.rd) plan stub:
 ```python
In [4]: RE(bps.rd(stage.x))
Out[4]: RunEngineResult(run_start_uids=(), plan_result=0.0, exit_status='success', interrupted=False, reason='', exception=None)
```

and move it using the [`bps.mv`](#bluesky.plan_stubs.mv) plan sub:
 ```python
In [5]: RE(bps.mv(stage.x, 1.5))
Out[5]: RunEngineResult(run_start_uids=(), plan_result=(<WatchableAsyncStatus, device: x, task: <coroutine object WatchableAsyncStatus._notify_watchers_from at 0x7f9c71791940>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

In [6]: RE(bps.rd(stage.x))
Out[6]: RunEngineResult(run_start_uids=(), plan_result=1.5, exit_status='success', interrupted=False, reason='', exception=None)
```

(demo-grid-scan)=
## Run a grid scan

There is also a point detector that changes its 3 channels of output based on the positions of the `stage.x` and `stage.y` motors, so we can use it in a [`bp.grid_scan`](#bluesky.plans.grid_scan):

```{eval-rst}
.. ipython:: python
  :suppress:

  from ophyd_async.sim.__main__ import *
  # Make the moves faster so docs build don't take too long
  RE(bps.mv(stage.x.velocity, 1000, stage.y.velocity, 1000))

.. ipython:: python
  
  @savefig sim_grid_scan.png width=4in
  RE(bp.grid_scan([pdet], stage.x, 1, 2, 3, stage.y, 2, 3, 3))
```

This detector produces a single point of information for each channel at each motor value. This means that the [](inv:bluesky#best_effort_callback) is able to print a tabular form of the scan.

There is also a blob detector that produces a gaussian blob with intensity based on the positions of the `stage.x` and `stage.y` motors, writing the data to an HDF file. You can also use this in a grid scan, but there will be no data displayed as the `BestEffortCallback` doesn't know how to read data from file:

```{eval-rst}
.. ipython:: python
  :okwarning:
  
  RE(bp.grid_scan([bdet], stage.x, 1, 2, 3, stage.y, 2, 3, 3))
```

:::{seealso}
A more interactive scanning tutorial including live plotting of the data from file is in the process of being written in [the bluesky cookbook](https://github.com/bluesky/bluesky-cookbook/pull/22).
:::

## Examine the script

We will now walk through the script section by section and examine what each part does. First of all we import the bluesky and ophyd libraries:
```{literalinclude} ../../src/ophyd_async/sim/__main__.py
:language: python
:start-after: Import bluesky and ophyd
:end-before: Create a run engine
```

After this we create a RunEngine:
```{literalinclude} ../../src/ophyd_async/sim/__main__.py
:language: python
:start-after: Create a run engine
:end-before: Add a callback
```
We pass `call_returns_result=True` to the RunEngine so that we can see the result of `bps.rd` above. We call `autoawait_in_bluesky_event_loop()` so that when we `await bps.rd(x)` it will happen in the same event loop that the RunEngine uses rather than an IPython specific one. This avoids some surprising behavior that occurs when devices are accessed from multiple event loops.

We then setup plotting of the resulting scans:
```{literalinclude} ../../src/ophyd_async/sim/__main__.py
:language: python
:start-after: Add a callback
:end-before: Make a pattern generator
```
This subscribes to the emitted bluesky [](inv:bluesky#documents), and interprets them for plotting. In this case it made a table of points for the motors and each channel of the point detector, and plots of the point detector channels in a gridded pattern.

Just for the simulation we need something to produce the test data:
```{literalinclude} ../../src/ophyd_async/sim/__main__.py
:language: python
:start-after: X-ray scattering
:end-before: path provider
```
This is passed to all the Devices so they can tell it the X and Y positions of the motors and get simulated point and gaussian blob data from it. In production you would pass around references to the control system (EPICS PV prefixes or Tango Resource Locations) instead of creating an object here. This is explored in more detail in [](./implementing-devices.md).

Next up is the path provider:
```{literalinclude} ../../src/ophyd_async/sim/__main__.py
:language: python
:start-after: temporary directory
:end-before: All Devices created within this block
```
This is how we specify in which location file-writing detectors store their data. In this example we choose to write to a static temporary directory using the [](#StaticPathProvider), and to name each file within it with a UUID using the [](#UUIDFilenameProvider). [Other PathProviders](#PathProvider) allow this to be customized. In production we would chose a location on a filesystem that would be accessible by downstream consumers of the scan documents.

Finally we create and connect the Devices:
```{literalinclude} ../../src/ophyd_async/sim/__main__.py
:language: python
:start-after: connected and named at the end of the with block
```
The first thing to note is the `with` statement. This uses a [](#init_devices) as a context manager to collect up the top level `Device` instances created in the context, and run the following:

- If `set_name=True` (the default), then call [](#Device.set_name) passing the name of the variable within the context. For example, here we call
  ``pdet.set_name("pdet")``
- If ``connect=True`` (the default), then call [](#Device.connect) in parallel for all top level Devices, waiting for up to ``timeout`` seconds. For example, here we will connect `stage`, `pdet` and `bdet` at the same time. This parallel connect speeds up connection to the underlying control system.
- If ``mock=True`` is passed, then don't connect to the control system, but set Devices into mock mode for testing.

Within it the device creation happens, in this case the `stage` with `x` and `y` motors, and the two detectors.

## Conclusion

In this tutorial we have instantiated some existing ophyd-async devices, seen how they can be connected and named, and used them in some basic plans. Read on to see how to implement support for devices via a control system like EPICS or Tango.
