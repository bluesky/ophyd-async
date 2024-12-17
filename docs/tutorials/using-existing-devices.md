# Using existing Devices

In this tutorial we will create a bluesky RunEngine, instantiate some existing ophyd-async Devices, and use them in some bluesky plans. It assumes you have already run through the Bluesky tutorial on `tutorial_run_engine_setup`.

## Run the demo

Ophyd-async ships with some simulated devices and a demo script that will create them along with a RunEngine. Let's take a look at it now:
```{literalinclude} ../../src/ophyd_async/sim/demo/__main__.py
:language: python
```

We will explain the contents in more detail later on, but for now let's run it in an interactive [ipython](https://ipython.org) shell:
```
$ ipython -i -m ophyd_async.sim.demo
Python 3.11.11 (main, Dec  4 2024, 20:38:25) [GCC 12.2.0]
Type 'copyright', 'credits' or 'license' for more information
IPython 8.30.0 -- An enhanced Interactive Python. Type '?' for help.

In [1]: 
```

This has launched an ipython shell, told it to import and run the demo script packaged inside `ophyd_async.sim.demo`, then return to an interactive prompt.

## Investigate the Devices

We will look at the `x` and `y` motors first. If we examine them we can see that they have a name:
```python
In [1]: x.name
Out[1]: 'x'
```

But if we try to call any of the other methods like `read()` we will see that it doesn't return the value, but a [coroutines](inv:python:std:label#coroutine):

```python
In [2]: x.read()
Out[2]: <coroutine object StandardReadable.read at 0x7f9c5c105220>
```

This is because ophyd-async devices implement async versions of the bluesky [verbs](inv:bluesky#hardware). To get the value we can `await` it:
 ```python
In [3]: await x.read()
Out[3]: 
{'x-user_readback': {'value': 0.0,
  'timestamp': 367727.615860209,
  'alarm_severity': 0}}
```

## Run some plans

Although it is useful to run the verbs using the `await` syntax for debugging, most of the time we will run them via plans executed by the [](#bluesky.run_engine.RunEngine). For instance we can read it using the [`bps.rd`](#bluesky.plan_stubs.rd) plan stub:
 ```python
In [4]: RE(bps.rd(x))
Out[4]: RunEngineResult(run_start_uids=(), plan_result=0.0, exit_status='success', interrupted=False, reason='', exception=None)
```

and move it using the [`bps.mv`](#bluesky.plan_stubs.mv) plan sub:
 ```python
In [5]: RE(bps.mv(x, 1.5))
Out[5]: RunEngineResult(run_start_uids=(), plan_result=(<WatchableAsyncStatus, device: x, task: <coroutine object WatchableAsyncStatus._notify_watchers_from at 0x7f9c71791940>, done>,), exit_status='success', interrupted=False, reason='', exception=None)

In [6]: RE(bps.rd(x))
Out[6]: RunEngineResult(run_start_uids=(), plan_result=1.5, exit_status='success', interrupted=False, reason='', exception=None)
```

There is also a detector that changes its output based on the positions of the `x` and `y` motor, so we can use it in a [`bp.grid_scan`](#bluesky.plans.grid_scan):
```python
In [7]: RE(bp.grid_scan([det], x, -10, 10, 10, y, -8, 8, 9))
Out[7]: RunEngineResult(run_start_uids=('63dc35b7-e4b9-46a3-9bcb-c64d8106cbf3',), plan_result='63dc35b7-e4b9-46a3-9bcb-c64d8106cbf3', exit_status='success', interrupted=False, reason='', exception=None)
```

:::{seealso}
A more interactive scanning tutorial including live plotting of the data is in the process of being written in [the bluesky cookbook](https://github.com/bluesky/bluesky-cookbook/pull/22)
:::

## Examine the script

We will now walk through the script section by section and examine what each part does. First of all we import the bluesky and ophyd libraries:
```{literalinclude} ../../src/ophyd_async/sim/demo/__main__.py
:language: python
:start-after: Import bluesky and ophyd
:end-before: Create a run engine
```

After this we create a RunEngine:
```{literalinclude} ../../src/ophyd_async/sim/demo/__main__.py
:language: python
:start-after: Create a run engine
:end-before: Define where test data should be written
```
We pass `call_returns_result=True` to the RunEngine so that we can see the result of `bps.rd` above. We call `autoawait_in_bluesky_event_loop()` so that when we `await bps.rd(x)` it will happen in the same event loop that the RunEngine uses rather than an IPython specific one. This avoids some surprising behaviour that occurs when devices are accessed from multiple event loops.

Next up is the path provider:
```{literalinclude} ../../src/ophyd_async/sim/demo/__main__.py
:language: python
:start-after: Define where test data should be written
:end-before: All Devices created within this block
```
This is how we specify in which location file-writing detectors store their data. In this example we choose to write to a static directory `/tmp` using the [](#StaticPathProvider), and to name each file within it with a unique UUID using the [](#UUIDFilenameProvider). [Other PathProviders](#PathProvider) allow this to be customized.

Finally we create and connect the Devices:
```{literalinclude} ../../src/ophyd_async/sim/demo/__main__.py
:language: python
:start-after: connected and named at the end of the with block
```
The first thing to note is the `with` statement. This uses a [](#init_devices) as a context manager to collect up the top level `Device` instances created in the context, and run the following:

- If `set_name=True` (the default), then call [](#Device.set_name) passing the name of the variable within the context. For example, here we call
  ``det.set_name("det")``
- If ``connect=True`` (the default), then call [](#Device.connect) in parallel for all top level Devices, waiting for up to ``timeout`` seconds. For example, here we will connect `x`, `y` and `det` at the same time. This parallel connect speeds up connection to the underlying control system.
- If ``mock=True`` is passed, then don't connect to the control system, but set Devices into mock mode for testing.

Within it the device creation happens, in this case the `x` and `y` motors and a `det` detector that gives different data depending on the position of the motors.

## Conclusion

In this tutorial we have instantiated some existing ophyd-async devices, seen how they can be connected and named, and used them in some basic plans. Read on to see how to implement support for devices via a control system like EPICS or Tango.
