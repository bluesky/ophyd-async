(implementing-devices)=
# Implementing Devices

In [](./using-devices.md) we learned how to instantiate some existing ophyd-async Devices. These Devices were ophyd level simulations, so did not talk to any underlying control system. In this tutorial we will instantiate some demo Devices that talk to underlying control system implementations, then explore how the Devices themselves are implemented.

## Pick your control system

Most bluesky users will be interfacing to an underlying control system like EPICS or Tango. The underlying control system will provide functionality like Engineering display screens and historical archiving of control system data. It is possibly to use ophyd-async with multiple control systems, so this tutorial is written with tabbed sections to allow us to only show the information relevant to one particular control system.

To summarize what each control system does:

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics

[EPICS](https://epics-controls.org) is a set of software tools and applications which provide a software infrastructure for use in building distributed control systems to operate devices such as Particle Accelerators, Large Experiments and major Telescopes. Such distributed control systems typically comprise tens or even hundreds of computers, networked together to allow communication between them and to provide control and feedback of the various parts of the device from a central control room.

EPICS uses Client/Server and Publish/Subscribe techniques to communicate between the various computers. Most servers (called Input/Output Controllers or IOCs) perform real-world I/O and local control tasks, and publish this information to clients using robust, EPICS specific network protocols Channel Access and pvAccess. Clients use a process variable (PV) as an identifier to get, put or monitor the value and metadata of a particular control system variable without knowing which server hosts that variable.

EPICS has a flat architecture where any client can request the PV of any server. Sites typically introduce hierarchy by imposing a naming convention on these PVs.
:::

:::{tab-item} Tango
:sync: tango

[Tango](https://www.tango-controls.org/) is an Open Source solution for SCADA and DCS. Open Source means you get all the source code under an Open Source free licence (LGPL and GPL). Supervisory Control and Data Acquisition (SCADA) systems are typically industrial type systems using standard hardware. Distributed Control Systems (DCS) are more flexible control systems used in more complex environments. Sardana is a good example of a Tango based Beamline SCADA.

Tango is typically deployed with a central database, which provides a nameserver to lookup which distributed server provides access to the Device. Once located, the Device server can be introspected to see what Attributes of the Device exist.

:::

:::{tab-item} FastCS
:sync: fastcs

[FastCS](https://diamondlightsource.github.io/FastCS) is a control system agnostic framework for building Device support in Python that will work for both EPICS and Tango without depending on either. It allows Device support to be written once in a declarative way, then at runtime the control system can be selected. It also adds support for multi-device introspection to both EPICS and Tango, which allows the same ophyd-async Device and the same FastCS Device to use either EPICS or Tango as a transport layer.

FastCS is currently in an early phase of development, being used for [PandA](https://github.com/PandABlocks/fastcs-PandABlocks) and [Odin](https://github.com/DiamondLightSource/fastcs-odin) Devices within ophyd-async.
:::

::::

## Run the demo

Ophyd-async ships with some demo devices that do the same thing for each control system, and a script that will create them along with a RunEngine. Let's run it in an interactive [ipython](https://ipython.org) shell:

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics

```
$ ipython --matplotlib=qt6 -i -m ophyd_async.epics.demo
Python 3.11.11 (main, Dec  4 2024, 20:38:25) [GCC 12.2.0]
Type 'copyright', 'credits' or 'license' for more information
IPython 8.30.0 -- An enhanced Interactive Python. Type '?' for help.

In [1]: 
```
:::

:::{tab-item} Tango
:sync: tango

TODO

:::

:::{tab-item} FastCS
:sync: fastcs

TODO
:::

::::

We can now go ahead and run the same grid scan [we did in the previous tutorial](#demo-grid-scan):

```python
In [1]: RE(bp.grid_scan([pdet], stage.x, 1, 2, 3, stage.y, 2, 3, 3))

Transient Scan ID: 1     Time: 2025-01-14 11:29:05
Persistent Unique Scan ID: '2e0e75d8-33dd-430f-8cd8-6d6ae053c429'
New stream: 'primary'
+-----------+------------+------------+------------+----------------------+----------------------+----------------------+
|   seq_num |       time |    stage-x |    stage-y | pdet-channel-1-value | pdet-channel-2-value | pdet-channel-3-value |
+-----------+------------+------------+------------+----------------------+----------------------+----------------------+
|         1 | 11:29:05.7 |      1.000 |      2.000 |                  921 |                  887 |                  859 |
|         2 | 11:29:06.6 |      1.000 |      2.500 |                  959 |                  926 |                  898 |
|         3 | 11:29:07.5 |      1.000 |      3.000 |                  937 |                  903 |                  875 |
|         4 | 11:29:08.3 |      1.500 |      2.000 |                  976 |                  975 |                  974 |
|         5 | 11:29:09.1 |      1.500 |      2.500 |                  843 |                  843 |                  842 |
|         6 | 11:29:09.8 |      1.500 |      3.000 |                  660 |                  660 |                  659 |
|         7 | 11:29:10.6 |      2.000 |      2.000 |                  761 |                  740 |                  722 |
|         8 | 11:29:11.4 |      2.000 |      2.500 |                  537 |                  516 |                  498 |
|         9 | 11:29:12.2 |      2.000 |      3.000 |                  487 |                  467 |                  448 |
+-----------+------------+------------+------------+----------------------+----------------------+----------------------+
generator grid_scan ['2e0e75d8'] (scan num: 1)

Out[1]: RunEngineResult(run_start_uids=('2e0e75d8-33dd-430f-8cd8-6d6ae053c429',), plan_result='2e0e75d8-33dd-430f-8cd8-6d6ae053c429', exit_status='success', interrupted=False, reason='', exception=None)
```

## See how Devices are instantiated

Now we will take a look at the demo script and see how it is instantiated. The beginning section with imports is the same as in the first tutorial, but then the control system specific differences appear.

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics

```{literalinclude} ../../src/ophyd_async/epics/demo/__main__.py
:language: python
:emphasize-lines: 18-
```

EPICS PVs are normally broadcast to your entire network subnet. To avoid PV name clashes, we pick a random prefix, then start the demo IOC using this PV  prefix. Starting an IOC here is done just for the demo, in production the IOC would already be running before you started bluesky.

We then pass the PV prefix for each Device down using prior knowledge about the PVs that this particular IOC creates. For example, we know that there will be a `DemoStage`, and all its PVs will start with `prefix + "STAGE:"`.

```{note}
There is no introspection of PVs in a device in EPICS, if we tell the IOC to make 3 channels on the point detector, we must also tell the ophyd-async device that the point detector has 3 channels.
```

:::

:::{tab-item} Tango
:sync: tango

TODO

:::

:::{tab-item} FastCS
:sync: fastcs

TODO
:::

::::

## Look at the Device implementations

The demo creates the following structure of Devices:
```{mermaid}
:config: { "theme": "neutral" }
:align: center
flowchart LR
    DemoPointDetector-- channel ---DeviceVector
    DeviceVector-- 1 ---pdet.1(DemoPointDetectorChannel)
    DeviceVector-- 2 ---pdet.2(DemoPointDetectorChannel)
    DeviceVector-- 3 ---pdet.3(DemoPointDetectorChannel)
    DemoStage-- x ---stage.x(DemoMotor)
    DemoStage-- y ---stage.y(DemoMotor)
```
The `DemoStage` contains two `DemoMotor`s, called `x` and `y`. The `DemoPointDetector` contains a `DeviceVector` called `channel` that contains 3 `DemoPointDetectorChannel`s, called `1`, `2` and `3`.

We will now inspect the `Demo` classes in the diagram to see how they talk to the underlying control system.

### `DemoPointDetectorChannel`

Let's start with the lowest level sort of Device, a single channel of our point detector. It contains Signals, which are the smallest sort of Device in ophyd-async, with a current value of a given datatype. In this case, there are two:
- `value`: the current value of the channel in integer counts
- `mode`: a configuration enum which varies the output of the channel

We specify to the Device baseclass that we would like a Signal of a given type (e.g. `SignalR[int]`) via a type hint, and it will create that signal for us in a control system specific way. The type of `value` is the python builtin `int`, and the type of `mode` is an [enum](#StrictEnum) we have declared ourselves, where the string values must exactly match what the control system produces.

```{seealso}
[](#SignalDatatypeT) defines the list of all possible datatypes you can use for Signals
```

We can optionally [annotate](#typing.Annotated) this type hint with some additional information, like [`Format`](#StandardReadableFormat). This will tell the [](#StandardReadable) baseclass which Signals are important in a plan like `bp.grid_scan`. In this case we specify that `mode` should be reported as a [configuration parameter](#StandardReadableFormat.CONFIG_SIGNAL) once at the start of the scan, and `value` should be [fetched without caching and plotted](#StandardReadableFormat.HINTED_UNCACHED_SIGNAL) at each point of the scan.

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics

```{literalinclude} ../../src/ophyd_async/epics/demo/_point_detector_channel.py
:language: python
```

When the Device is instantiated, the [](#EpicsDevice) baseclass will look at all the type hints for annotations with a [](#PvSuffix). It will append that to the PV prefix that is passed into the device. In this case if we made a `DemoPointDetectorChannel(prefix="PREFIX:")`, then `value` would have PV `PREFIX:Value`. [](#PvSuffix) also allows you to specify different suffixes for the read and write PVs if they are different.

:::

:::{tab-item} Tango
:sync: tango

TODO

:::

:::{tab-item} FastCS
:sync: fastcs

TODO
:::

::::

### `DemoPointDetector`

Moving up a level, we have the point detector itself. This also has some Signals to control acquisition which are created in the same way as above:
- `acquire_time`: a configuration float saying how long each point should be acquired for
- `start`: an executable to start a single acquisition
- `acquiring`: a boolean that is True when acquiring
- `reset`: an executable to reset the counts on all channels

We also have a [](#DeviceVector) called `channel` with `DemoPointDetectorChannel` instances within it. These will all contribute their configuration values at the start of scan, and their values at every point in the scan.

Finally, we need to communicate to bluesky that it has to `trigger()` and acquisition before it can `read()` from the underlying channels. We do this by implementing the [`Triggerable`](#bluesky.protocols.Triggerable) protocol. This involves writing a `trigger()` method with the logic that must be run, calling [](#SignalX.trigger), [](#SignalW.set) and [](#SignalR.get_value) to manipulate the values of the underlying Signals, returning when complete. This is wrapped in an [](#AsyncStatus), which is used by bluesky to run this operation in the background and know when it is complete.

```{seealso}
[](../how-to/interact-with-signals)
```

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics

```{literalinclude} ../../src/ophyd_async/epics/demo/_point_detector.py
:language: python
```

Although the Signals are declared via type hints, the DeviceVector requires explicit instantiation in an `__init__` method. This is because it requires the `num_channels` to be passed in to the constructor to know how many channels require creation. This means that we also need to do the PV concatenation ourselves, so if the PV prefix for the device as `PREFIX:` then the first channel would have prefix `PREFIX:CHAN1:`. We also register them with `StandardReadable` in a different way, adding them within a [](#StandardReadable.add_children_as_readables) context manager which adds all the children created within its body.

Whilst it is not required for the call to `super().__init__` to be after all signals have been created it is more efficient to do so. However, there may be some edge cases where signals need to be created after this e.g. for [derived signals](../how-to/derive-one-signal-from-others.md) that depend on their parent.
:::

:::{tab-item} Tango
:sync: tango

TODO

:::

:::{tab-item} FastCS
:sync: fastcs

TODO
:::

::::

```{seealso}
For more information on when to construct Devices declaratively using type hints, and when to construct them procedurally with an `__init__` method, see [](../explanations/declarative-vs-procedural)
```

### `DemoMotor`

Moving onto the motion side, we have `DemoMotor`. This has a few more signals:
- `readback`: the current position of the motor as a float
- `velocity`: a configuration parameter for the velocity in units/s
- `units`: the string units of the position
- `setpoint`: the position the motor has been requested to move to as a float, it returns as soon as it's been set
- `precision`: the number of points after the decimal place of the position that are relevant
- `stop_`: an executable to stop the move immediately

At each point in the scan it will report the `readback`, but we override the `set_name()` method so that it reports its position as `stage.x` rather than `stage.x.readback`.

If we consider how we would use this in a scan, we could `bp.scan(stage.x.setpoint, ...)` directly, but that would only start the motor moving, not wait for it to complete the move. To do this, we need to implement another protocol: [`Movable`](#bluesky.protocols.Movable). This requires implementing a `set()` method (again wrapped in an [](#AsyncStatus)) that does the following:
- Work out where to move to
- Start the motor moving
- Optionally report back updates on how far the motor has moved so bluesky can provide a progress bar
- Wait until the motor is at the target position

Finally, we implement [`Stoppable`](#bluesky.protocols.Stoppable) which tells bluesky what to do if the user aborts a plan. This requires implementing `stop()` to execute the `stop_` signal and tell `set()` whether the move should be reported as successful completion, or if it should raise an error.

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics

```{literalinclude} ../../src/ophyd_async/epics/demo/_motor.py
:language: python
```


:::

:::{tab-item} Tango
:sync: tango

TODO

:::

:::{tab-item} FastCS
:sync: fastcs

TODO
:::

::::


### `DemoStage`

Finally we get to the `DemoStage`, which is responsible for instantiating two `DemoMotor`s. It also inherits from [](#StandardReadable), which allows it to be used in plans that `read()` devices. It ensures that the output of `read()` is the same as if you were to `read()` both the `DemoMotor`s, and merge the result:

::::{tab-set}
:sync-group: cs

:::{tab-item} EPICS
:sync: epics

```{literalinclude} ../../src/ophyd_async/epics/demo/_stage.py
:language: python
```
Like `DemoPointDetector`, the PV concatenation is done explicitly in code, and the children are added within a [](#StandardReadable.add_children_as_readables) context manager.

:::

:::{tab-item} Tango
:sync: tango

TODO

:::

:::{tab-item} FastCS
:sync: fastcs

TODO
:::

::::

## Conclusion

In this tutorial we have seen how to create some Devices that are backed by a Control system implementation. Read on to see how we would write some tests to ensure that they behave correctly.
