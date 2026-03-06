# 13. Preserve Hardware State in Implicit Step-Scan Trigger

Date: 2026-03-06

## Status

Accepted

## Context

When a `StandardDetector` has not been explicitly prepared with a `TriggerInfo` before the first call
to `trigger()` (e.g. in a `bp.count` or `bps.trigger_and_read` without a preceding `bps.prepare`),
`StandardDetector.trigger()` performs an *implicit prepare* using a default `TriggerInfo()`.

Before this decision the implicit prepare always used `TriggerInfo()` — a bare default with
`collections_per_event=1` and `number_of_events=1`. For EPICS areaDetector (AD) drivers this meant
that `num_images` was unconditionally reset to 1 on the driver before every step-scan point,
even if a preceding fly scan had left `num_images` set to a larger value.

This had two undesirable consequences:

1. **Surprising behaviour after manual setup.** If an operator sets `acquire_time`, then runs a
   `count` plan (which calls `trigger()` without a `prepare()`), then the detector will not
   change it. However if they set `num_images` then it will be overridden with 1, 
   discarding the operator's hardware configuration without warning.

2. **Inconsistency with ophyd-sync.** ophyd-sync devices do not alter detector hardware state
   that the user did not explicitly request changing. ophyd-async should be a drop-in replacement.

## Decision

### Opt-in `default_trigger_info()` on `DetectorTriggerLogic`

Add an optional `default_trigger_info(self) -> TriggerInfo` method to
`DetectorTriggerLogic`. If it doesn't exist then keep the existing behaviour of using `TriggerInfo()`

### `trigger_info_from_num_images()` free function for AD detectors

A free async helper function is provided in `ophyd_async.epics.adcore`:

```python
async def trigger_info_from_num_images(driver: ADBaseIO) -> TriggerInfo:
    num = await driver.num_images.get_value()
    return TriggerInfo(collections_per_event=max(1, num))
```

All EPICS areaDetector `TriggerLogic` subclasses implement `default_trigger_info` by delegating
to this function, reading back the current `num_images` value from the driver and returning it
as `collections_per_event`. This preserves the hardware state rather than resetting it.

## Consequences

- **Step scans no longer reset `num_images`** on AD detectors when no explicit `prepare()` is
  called, making ophyd-async a closer drop-in replacement for ophyd-sync.

- A fly scan that leaves `num_images=500` on the driver will cause a subsequent implicit step
  scan to capture 500 frames per trigger point instead of 1. This is the *correct* behaviour
  (honour the hardware state) but may surprise users who expected the scan to reset the detector.
  Plans that care about `num_images` should call `bps.prepare(det, TriggerInfo(...))` explicitly.
