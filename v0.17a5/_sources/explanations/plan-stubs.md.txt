# What plan stubs will do to Devices

Plan authors will typically compose [plan stubs](inv:bluesky#stub_plans) together to define the behaviour they expect from their Devices. When the plan is executed, the RunEngine will consume the [`Msg` objects](inv:bluesky:std:doc#msg) `yield from` each plan stub as a series of instructions, many of which call methods on the Device. This document lists some commonly used plan stubs, what Devices will do when they are called, and what order they should be called inside the plan.

```{seealso}
[](./fly-scanning.md) for more information on the difference between step scans (typically software driven) and flyscans (typically hardware driven)
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
- For motors, `bps.mv` will move the motor to the desired position, returning when it is complete and erroring if it fails to move. **`bps.abs_set`, however, does not wait for completion by default unless the `wait` option is explicitly set to `True`.**

### [`bps.trigger`](#bluesky.plan_stubs.trigger)

Ask the device to trigger a data collection:
- For detectors this will take a single exposure. 
- For motors this will do nothing as the readback position is always valid.

### [`bps.read`](#bluesky.plan_stubs.read)

Collect the data from a device after `trigger`:
- For detectors that write to a resource this will be a reference to the data written, for other detectors this will be the actual data
- For motors this is the readback value


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

Plan stubs can be mixed together to form arbitrary plans, but there are certain patterns that are common in specific categories of plan. This section lists the ordering of these stubs for step scans (typically software driven), fly scans (typically hardware driven), and scans that nest a fly scan within a step scan.

### Pure step scan

After `stage` and `open_run`, `prepare` can be called to set up detectors for a given exposure time if this has been specified in the plan. The inner loop `set`s motors, then `trigger`s and `read`s detectors for each point. Finally `close_run` and `unstage` do the cleanup.

::::{tab-set}
:sync-group: diagram-code

:::{tab-item} Diagram
:sync: diagram

```{mermaid}
:config: { "theme": "neutral" }
:align: center
flowchart TD
    stage["stage dets, motors"] --> open_run
    open_run --> prepare["(opt) prepare dets"]
    prepare --> set["set motors"]
    set --> trigger["trigger dets"]
    trigger --> read["read dets, motors"]
    read --> set
    read --> close_run
    close_run --> unstage["unstage dets, motors"]

```
:::

:::{tab-item} Code
:sync: code

```python
@stage_decorator([detector, motor])
@run_decorator()
def pure_step(positions: Sequence[float], exposure_time: float | None) -> MsgGenerator:
    if exposure_time is not None:
        yield from bps.prepare(detector, TriggerInfo(livetime=exposure_time), wait=True)
    for position in positions:
        yield from bps.abs_set(motor, position, wait=True)
        yield from bps.trigger_and_read(detector, motor)
```

```{seealso}
This code is just to aid understanding, normally you would call [](#bluesky.plans.scan) in production
```
:::

::::


(pure-fly-scan)=
### Pure fly scan

After `stage` and `open_run`, `prepare` sets up detectors for hardware triggering and motors for a trajectory and `kickoff` starts the prepared motion. Then `complete` is called on motors and detectors. While this is in progress the detectors will be `collect`ed repeatedly. Finally `close_run` and `unstage` do the cleanup.

::::{tab-set}
:sync-group: diagram-code

:::{tab-item} Diagram
:sync: diagram

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
:::

:::{tab-item} Code
:sync: code

```python
@stage_decorator([detector, motor])
@run_decorator()
def pure_fly(
    start_position: float,
    end_position: float,
    num_exposures: float,
    exposure_time: float,
    readout_time: float,
) -> MsgGenerator:
    yield from bps.prepare(
        detector,
        TriggerInfo(
            livetime=exposure_time,
            deadtime=readout_time,
            number_of_events=num_exposures,
        ),
    )
    yield from bps.prepare(
        motor,
        FlyMotorInfo(
            start_position=start_position,
            end_position=end_position,
            time_for_move=(exposure_time + readout_time) * num_exposures,
        ),
    )
    yield from bps.wait()
    yield from bps.kickoff_all(motor)
    yield from bps.kickoff_all(detector)
    yield from bps.collect_while_completing(
        flyers=[motor],
        detectors=[detector],
        flush_period=0.5,
    )
```

```{seealso}
This code is to aid understanding rather than for copying. This will be documented further in <https://github.com/bluesky/ophyd-async/issues/939>
```
:::

::::


### Fly scan nested within a step scan

After `stage` and `open_run` the detectors are `prepare`d for the entire scan. The inner loop `set`s the slow (software) motors to each point, followed by the hardware driven section of the scan. Just like the [](#pure-fly-scan), this consists of `prepare`, then `kickoff`, then `complete` of the fast (hardware) motors, `collect`ing from the detectors repeatedly until they are finished. Finally `close_run` and `unstage` do the cleanup.

::::{tab-set}
:sync-group: diagram-code

:::{tab-item} Diagram
:sync: diagram

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
:::

:::{tab-item} Code
:sync: code

```python
@stage_decorator([detector, column_motor, row_motor])
@run_decorator()
def fly_inside_step(
    columns: Sequence[float],
    row_start: float,
    row_end: float,
    exposures_per_row: int,
    exposure_time: float,
    readout_time: float,
) -> MsgGenerator:
    yield from bps.prepare(
        detector,
        TriggerInfo(
            livetime=exposure_time,
            deadtime=readout_time,
            number_of_events=exposures_per_row * len(columns),
        ),
    )
    for column in columns:    
        yield from bps.abs_set(column_motor, column)
        yield from bps.prepare(
            row_motor,
            FlyMotorInfo(
                start_position=row_start,
                end_position=row_end,
                time_for_move=(exposure_time + readout_time) * exposures_per_row,
            ),
        )
        yield from bps.wait()
        yield from bps.kickoff_all(row_motor)
        yield from bps.kickoff_all(detector)
        yield from bps.collect_while_completing(
            flyers=[row_motor],
            detectors=[detector],
            flush_period=0.5,
        )
```

```{seealso}
This code is to aid understanding rather than for copying. This will be documented further in <https://github.com/bluesky/ophyd-async/issues/939>
```
:::

::::



## Conclusion

The following table summarized what each plan stub does to each class of device:


```{list-table}
:header-rows: 1

* - Verb
  - Behavior if Motor
  - Behavior if Detector
  - Step / Fly
* - `stage`
  - Starts monitoring Signals
  - Ensures idle; flags next frame should go in a new resource
  - Both
* - `unstage`
  - Stops monitoring signals
  - Closes resources
  - Both
* - `open_run`
  - No effect
  - May compute new resource ID for writing
  - Both
* - `close_run`
  - No effect
  - Signals the end of data capture
  - Both
* - `prepare`
  - Moves to run-up position; sets velocity/trajectory
  - Sets acquisition parameters; arms hardware-triggered detectors
  - Both
* - `abs_set` / `mv`
  - Moves motor to a target position
  - N/A
  - Step
* - `trigger`
  - N/A
  - Captures a single exposure
  - Step
* - `read`
  - Reads current position
  - Reads triggered data
  - Step
* - `kickoff`
  - Starts motion and returns once stable velocity is reached
  - Starts acquisition (software-triggered); hardware-triggered detectors already armed in `prepare`
  - Fly
* - `complete`
  - Waits for motion (including ramp down) to finish
  - Waits for acquisition to finish (e.g. number of frames)
  - Fly
* - `collect`
  - N/A
  - Retrieves data already acquired during the scan
  - Fly
```
