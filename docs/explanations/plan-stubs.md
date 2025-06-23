# What plan stubs will do to Devices

Plan authors will typically compose [plan stubs](inv:bluesky#stub_plans) together to define the behaviour they expect from their Device. When the plan is executed by the RunEngine it will `yield from` each plan stub, producing [`Msg` objects](inv:bluesky#msg) giving instructions to the RunEngine, many of which call methods on the Device. This document lists some commonly used plan stubs, what Devices will do when they are called, and what order they should be called inside the plan.

```{seealso}
[](./flyscanning.md) for more information on the differences between software driven scans and hardware driven flyscans
```

## Plan stubs

### [`bps.stage`](#bluesky.plan_stubs.stage) and [`bps.unstage`](#bluesky.plan_stubs.unstage)

These are typically the first and last Messages in the plan:
- `stage` gets the Device into an idle state then makes it ready for data collection:
  - For Devices that read from Signals this will start monitoring those Signals
  - For detectors that write to a resource (e.g. an HDF file) this will indicate that any captured data (e.g. a detector frame) should be stored in a fresh resource
- `unstage` returns the Device to an idle state:
  - For Devices that read from Signals this will stop monitoring those Signals
  - For detectors that write to a resource this will close that resource

It is recommended that the [`bpp.stage_decorator`](#bluesky.preprocessors.stage_decorator) is applied to the plan to yield these Messages as they do the appropriate error handling.

### [`bps.open_run`](#bluesky.plan_stubs.open_run) and [`bps.close_run`](#bluesky.plan_stubs.close_run)

These are typically the second and second last Messages in the plan:
- `open_run` indicates to downstream consumers the start of a data collection
   - For detectors this may be used by specific implentations of `PathProvider` to calculate a new filename to write into
- `close_run` indicates the end of a data collection

It is recommended that the [`bpp.run_decorator`](#bluesky.preprocessors.run_decorator) is applied to the plan to yield these Messages as they do the appropriate error handling. It should be placed after the `stage_decorator`.

### [`bps.prepare`](#bluesky.plan_stubs.prepare)

Prepares the device for a `trigger` or `kickoff`, after `stage` and `open_run`:
- For detectors this will set parameters on the hardware such as exposure time and number of frames. If hardware triggering is requested it will also arm the detector so it is ready to receive those triggers.
- For motors this will move to the run up position and setup the requested motion velocity or trajectory.

### [`bps.abs_set`](#bluesky.plan_stubs.abs_set) or [`bps.mv`](#bluesky.plan_stubs.mv)

Set the device to a target setpoint:
- For motors this will move the motor to the desired position, returning when it is complete and erroring if it fails to move. 



### [`bps.trigger`](#bluesky.plan_stubs.trigger)

Ask the detector to take a single exposure. 

### [`bps.read`](#bluesky.plan_stubs.read)

Collect the data from a detector after `trigger`. 

### [`bps.kickoff`](#bluesky.plan_stubs.kickoff)

Begin a flyscan:
- For motors this will start motion and return once the motor has completed its run up and is moving at the desired velocity
- For detectors prepared for software triggering this will start the acquisition

```{note}
The plan should ensure that `kickoff` on the motors has finished before `kickoff` on the detectors in started so that software triggered detectors don't start too early. Hardware triggered detectors will already be armed from `prepare`.
```

### [`bps.complete`](#bluesky.plan_stubs.collect) and [`bps.collect`](#bluesky.plan_stubs.collect)

Wait for flyscanning to be done, collecting data from detectors periodically while that happens:
- `complete` waits for a flyscan to be done:
  - For motors this will wait until motion including ramp down is complete
  - For detectors this will wait until the requested number of frames has been written
- `collect` collects the data that has been written so far by a detector during a flyscan.

Typically called via [`bps.collect_while_completing`](#bluesky.plan_stubs.collect_while_completing), after `kickoff`.

## Ordering

Some scans only have a software driven component, some only have hardware driven components, and some mix both together. This section lists the ordering of these scans.

### Purely software driven scan

After `stage` and `open_run`, `prepare` can be called to set up detectors for a given exposure time if this has been specified in the plan. The inner loop `set`s motors, then `trigger`s and `read`s detectors for each point. Finally `close_run` and `unstage` do the cleanup.

```{mermaid}
:config: { "theme": "neutral" }
:align: center
flowchart TD
    stage["stage dets, motors"] --> open_run
    open_run --> prepare["(opt) prepare dets"]
    prepare --> set["set motors"]
    set --> trigger["trigger dets"]
    trigger --> read["read dets"]
    read --> set
    read --> close_run
    close_run --> unstage["unstage dets, motors"]

```

### Purely hardware driven scan

After `stage` and `open_run`, `prepare` sets up detectors for hardware triggering and motors for a trajectory and `kickoff` starts the prepared motion. Then `complete` is called on motors and detectors. While this is in progress the detectors will be `collect`ed repeatedly. Finally `close_run` and `unstage` do the cleanup.

```{mermaid}
:config: { "theme": "neutral" }
:align: center
flowchart TD
    stage["stage dets, motors"] --> open_run
    open_run --> prepare["prepare dets, motors"]
    prepare --> kickoff["kickoff dets, motors"]
    kickoff --> complete["complete dets, motors"]
    complete --> collect["collect dets"]
    collect --> collect
    collect ----> close_run
    close_run --> unstage["unstage dets, motors"]
```

### Mixed software and hardware driven scan

After `stage` and `open_run` the detectors are `prepare`d for the entire scan. The inner loop `set`s the slow (software) motors to each point, followed by the hardware driven section of the scan. Just like the [](#purely-hardware-driven-scan), this consists of `prepare`, then `kickoff`, then `complete` of the fast (hardware) motors, `collect`ing from the detectors repeatedly until they are finished. Finally `close_run` and `unstage` do the cleanup.

```{mermaid}
:config: { "theme": "neutral" }
:align: center
flowchart TD
    stage["stage dets, motors"] --> open_run
    open_run --> prepare_d["prepare dets"]
    prepare_d --> set["set slow motors"]
    set --> prepare_m["prepare fast motors"]
    prepare_m --> kickoff["kickoff dets, fast motors"]
    kickoff --> complete["complete dets, fast motors"]
    complete --> collect["collect dets"]
    collect --> collect
    collect --> set
    collect ----> close_run
    close_run --> unstage["unstage dets, motors"]
```
