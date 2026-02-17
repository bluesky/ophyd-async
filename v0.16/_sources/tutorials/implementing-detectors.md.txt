# Implementing File Writing Detectors

In [](./implementing-devices.md) we learned how to create Devices that talk to a control system to implement a particular behavior in bluesky plans. This behavior was based around the verbs from the [](#bluesky.protocols.Movable) and [](#bluesky.protocols.Readable) protocols, allowing us to use these Devices in a typical scan: moving them to a position, then acquiring data via the control system. We will now explore the [](#bluesky.protocols.WritesExternalAssets) protocol, and how it would be implemented for a File Writing Detector.

## Run the demo

We will return to our [](#ophyd_async.sim) devices we saw in [](./using-devices.md) for this tutorial, and dig a little deeper into what [Event Model Documents](inv:event-model#data_model) they produce. Let's run up our ipython shell again:

```
$ ipython --matplotlib=qt6 -i -m ophyd_async.sim
Python 3.11.11 (main, Dec  4 2024, 20:38:25) [GCC 12.2.0]
Type 'copyright', 'credits' or 'license' for more information
IPython 8.30.0 -- An enhanced Interactive Python. Type '?' for help.

In [1]: 
```

## Run a grid scan and investigate the documents

Now let's run a grid scan on the point detector, and pass a callback to the RunEngine so it prints the documents that are emitted:
```{eval-rst}
.. ipython:: python
    :suppress:

    from ophyd_async.sim.__main__ import *
    # Make the moves faster so docs build don't take too long
    RE(bps.mv(stage.x.velocity, 1000, stage.y.velocity, 1000))

.. ipython:: python
  
    RE(bp.grid_scan([pdet], stage.x, 1, 2, 2, stage.y, 2, 3, 2), print)
```
We see a series of documents being emitted:
- A [](#event_model.RunStart) document that tells us a scan is starting and what sort of scan it is, along with the names of the motors that will be moved.
- An [](#event_model.EventDescriptor) document that tells us that the motor readbacks and detector channels will be all be read together in a single stream. It is used to make the column headings, but it contains more metadata about the Devices too, like their configuration.
- For each point in the scan:
  - An [](#event_model.Event) document, containing the motor readbacks and detector channels with their timestamps. It is used to make each row of the table.
- A [](#event_model.RunStop) document that tells us the scan has stopped, and gives us its status.

Now let's try the same thing, but this time with the blob detector:

```{eval-rst}
.. ipython:: python
    :okwarning:
    
    RE(bp.grid_scan([bdet], stage.x, 1, 2, 2, stage.y, 2, 3, 2), print)
```
This time we see some different documents:
- The same [](#event_model.RunStart) document
- A similar [](#event_model.EventDescriptor) document, but with `'external': 'STREAM:'` on the detector column headings.
- A couple of [](#event_model.StreamResource) documents for each of those detector column headings giving an HDF file name and dataset within it where data will be written.
- For each point in the scan:
  - A couple of [](#event_model.StreamDatum) documents with a range of indices that have been written to an HDF dataset referenced in the StreamResource document.
  - An [](#event_model.Event) document, containing the motor readbacks and timestamps. It is used to make each row of the table.
- The same [](#event_model.RunStop) document

And we can run the plan with both detectors to see a document stream that combines both the previous example:

```{eval-rst}
.. ipython:: python
    :okwarning:
    
    RE(bp.grid_scan([bdet, pdet], stage.x, 1, 2, 2, stage.y, 2, 3, 2), print)
```

## Simplify the plan to just use the detector

The above examples show what happens if you `trigger()` a detector at each point of a scan, in this case taking a single frame each time. Let's write our own simple plan that only triggers and reads from the detector, using the utility [`bps` (`bluesky.plan_stubs`)](inv:bluesky#stub_plans) and [`bpp` (`bluesky.preprocessors`)](inv:bluesky#preprocessors):

```{eval-rst}
.. ipython:: python

    @bpp.stage_decorator([bdet])
    @bpp.run_decorator()
    def my_count_plan():
        for i in range(2):
            yield from bps.trigger_and_read([bdet])

.. ipython:: python
    :okwarning:

    RE(my_count_plan(), print)
```

Here we see the same sort of documents as above, but with only detector information in it.

Note that on each trigger, only a single image is taken, at the default exposure of `0.1s`. If we would like a different exposure time, we can specify with a [](#TriggerInfo):

```{eval-rst}
.. ipython:: python

    from ophyd_async.core import TriggerInfo
  
    @bpp.stage_decorator([bdet])
    @bpp.run_decorator()
    def my_count_plan_with_prepare():
        yield from bps.prepare(bdet, TriggerInfo(livetime=0.001), wait=True)
        for i in range(2):
            yield from bps.trigger_and_read([bdet])

.. ipython:: python
    :okwarning:

    RE(my_count_plan_with_prepare(), print)
```

This also moves the work of setting up the detector from the first call of `trigger()` to the `prepare()` call. We can also move the creation of the descriptor earlier, so there is no extra work to do on the first call to `trigger()`:

```{eval-rst}
.. ipython:: python

    from ophyd_async.core import TriggerInfo
  
    @bpp.stage_decorator([bdet])
    @bpp.run_decorator()
    def my_count_plan_with_prepare():
        yield from bps.prepare(bdet, TriggerInfo(), wait=True)
        yield from bps.declare_stream(bdet, name="primary")
        for i in range(2):
            yield from bps.trigger_and_read([bdet])

.. ipython:: python
    :okwarning:

    RE(my_count_plan_with_prepare(), print)
```

## Run a fly scan and investigate the documents

The above demonstrates the detector portion of a step scan, letting the things you want to scan settle before taking data from the detector, and doing this at every point of the scan. Our filewriting detector also supports the ability to fly scan it, taking data while you are scanning other things. To do this, it implements the [](#bluesky.protocols.Flyable) protocol, which allows us to `kickoff()` a series of images, then wait until it is `complete()`:

```{eval-rst}
.. ipython:: python
  
    @bpp.stage_decorator([bdet])
    @bpp.run_decorator()
    def fly_plan():
        yield from bps.prepare(bdet, TriggerInfo(number_of_events=7), wait=True)
        yield from bps.declare_stream(bdet, name="primary")
        yield from bps.kickoff(bdet, wait=True)
        yield from bps.collect_while_completing(flyers=[bdet], dets=[bdet], flush_period=0.5)

.. ipython:: python
    :okwarning:

    RE(fly_plan(), print)
```

As before, we see the start, descriptor, and pair of stream resources, but this time we don't see any event documents. Also, even though we asked for 7 frames from each of the 2 streams, we only got 2 stream datums for each stream. 

What is happening is that instead of triggering, waiting, and publishing a single frame, we are setting up the detector to take 7 frames without stopping, then at the `flush_period` of 0.5s emitting a stream datum with the frames that have been captured. If we inspect the stream datum documents for each stream we see that:
- The first has `'indices': {'start': 0, 'stop': 4}`
- The second has `'indices': {'start': 4, 'stop': 7}`

This behavior allows us to scale up the framerate of the detector without scaling up the number of documents emitted: whether the detector goes at 10Hz or 10MHz it still only emits one stream datum per stream per flush period, just with different numbers in the `indices` field.

## Look at the Device implementations

Now we'll have a look at the code to see how we implement one of these detectors:

### `SimBlobDetector`

```{literalinclude} ../../src/ophyd_async/sim/_blob_detector.py
:language: python
```

It derives from [](#StandardDetector) which is a utility baseclass that implements the protocols we have mentioned so far in this tutorial. It uses a pair of logic classes to provide behavior for each protocol verb:
- [](#DetectorController) to setup the exposure and trigger mode of the detector, arm it, and wait for it to complete
- [](#DetectorWriter) to tell the detector to open a file, describe the datasets it will write, and wait for it to have written a given number of frames

In this case, we have a Controller and Writer class written just for this simulation, both taking a reference to the pattern generator that provides methods for both detector control and file writing. In other cases the detector control and filewriting may be handled by different sub-devices that talk to different parts of the control system. The job of the top level detector class is to take the arguments that the controller and writer need and distribute them, passing the instances to the superclass init.

Now let's look at the underlying classes that define the detector behavior:

### `BlobDetectorControl`

First we have `BlobDetectorController`, a [](#DetectorController) subclass:

```{literalinclude} ../../src/ophyd_async/sim/_blob_detector_controller.py
:language: python
```

It's job is to control the acquisition process on the detector, starting and stopping the collection of data:
- `prepare()` takes a [](#TriggerInfo) which details everything the detector needs to know about the upcoming acquisition. In this case we just store it for later use.
- `arm()` starts the acquisition process that has been prepared. In this case we create a background task that will write our simulation images to file.
- `wait_for_idle()` waits for that acquisition process to be complete.
- `disarm()` interrupts the acquisition process, and then waits for it to complete.

### `BlobDetectorWriter`

Then we have `BlobDetectorWriter`, a [](#DetectorWriter) subclass:

```{literalinclude} ../../src/ophyd_async/sim/_blob_detector_writer.py
:language: python
```

Its job is to control the file writing process on the detector, which may or may not be coupled to the acquisition process:
- `open()` tells the detector to open a file, and returns information about the datasets that it will write
- `hints` gives a list of the datasets that are interesting to plot
- `get_indices_written()` returns the last index written
- `observe_indices_written()` repeatedly yields the last index written then waits for the next one to be written
- `collect_stream_docs()` uses the [](#HDFDocumentComposer) to publish a document per dataset that says which frames have been written since the last call
- `close()` tells the detector to close the file

## Conclusion

We have seen how to make a [](#StandardDetector) and how the [](#DetectorController) and [](#DetectorWriter) allow us to customise its behavior.

```{seealso}
[](../how-to/implement-ad-detector.md) for writing an implementation of `StandardDetector` for an EPICS areaDetector
```
