# Environment Variables

(OPHYD_ASYNC_PRESERVE_DETECTOR_STATE)=

## `OPHYD_ASYNC_PRESERVE_DETECTOR_STATE`

Controls the implicit prepare performed by
[`StandardDetector.trigger()`](#ophyd_async.core.StandardDetector.trigger) when
[`prepare()`](#ophyd_async.core.StandardDetector.prepare) has not been called since
the last [`stage()`](#ophyd_async.core.StandardDetector.stage).

| Value | Behaviour |
|-------|-----------|
| `YES` | Calls [`DetectorTriggerLogic.default_trigger_info()`](#ophyd_async.core.DetectorTriggerLogic.default_trigger_info) to read current hardware state before the implicit prepare. Raises `RuntimeError` if `default_trigger_info()` is not implemented on the trigger logic. |
| anything else (default) | Uses a bare [`TriggerInfo()`](#ophyd_async.core.TriggerInfo), resetting detector state to defaults. |

See [ADR 0013](../explanations/decisions/0013-preserve-hardware-state-in-step-scan.md)
for rationale.
