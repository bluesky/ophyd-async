# Changelog

## Unreleased

### Breaking changes

- `StandardMovable.movable_logic` and `StandardFlyable.flyable_logic` are replaced by one `logic` property: rename your `@cached_property`. A Device that moves and flies has one logic inheriting both `MovableLogic` and `FlyableLogic`. For an ephemeral flyer use `FlyableLogic.with_device()`.
- `FlyableLogic` hooks are replaced, and defining an old one raises `TypeError` naming its replacement:
  - `on_prepare(value)` becomes `prepare_to_fly(name, value, previous_ctx)`, an async generator that yields its context first, then optionally `WatcherUpdate`s.
  - `on_kickoff(ctx)` and `on_complete(ctx)` become one `fly(ctx)`, an async generator that yields `KICKED_OFF` once up to speed, then optionally `WatcherUpdate`s.
  - `stop()` becomes `ensure_stopped()`, which must wait until the hardware has stopped, and `on_stage()` becomes `ensure_ready()`.
- `MovableLogic.stop()` becomes `ensure_stopped()`; the old name still works with a `DeprecationWarning`.
- A flyer must be staged before `prepare()`, and a verb called out of order raises `TransitionError`. `bp.fly` does not stage, so wrap it in `bpp.stage_wrapper`.
- Staging an already-staged Standard device raises `TransitionError`, as ophyd raises `RedundantStaging`.
- A `set()` ended by `stop()` or by a new `set()` raises `StoppedError`, a `RuntimeError`.
- `SimMotor` is now a flyer, so it must be staged before `prepare()`.
- Renamed `MotorFlyCtx` to `MotorPrepareCtx`, `PmacFlyCtx` and `PmacPrepareContext` to `PmacPrepareCtx`, and `SimMotorMoveLogic` to `SimMotorLogic`.
- `Motor` writes `.STOP` and waits for `.DMOV` on every `unstage()`, even when it looks stopped.
- Needs `typing-extensions>=4.14`.

### Added

- `KICKED_OFF`, `TransitionError`, `StoppedError` and `Logic`, the base of `MovableLogic` and `FlyableLogic`.
- `watch_readback()` reports the progress of a move from a `FlyableLogic` hook. `SimMotor.prepare()` and `complete()` now report progress, as `Motor` does.
- `cancel_and_wait()` cancels tasks and waits for all of them to end, even through a cancel of its caller, then raises the error of the first task, in the order given, that ended with one. If its caller was cancelled, it raises `CancelledError` instead.
- `plugins_with_proc()` adds the process plugin made from a `proc_suffix` to a detector's `plugins`, and raises `ValueError` if `plugins` already has a `"proc"`. Every areaDetector vendor detector and `ContAcqDetector` uses it, so `"proc"` is reserved: pass `proc_suffix` instead.

### Changed

- Breaking: `WatchableAsyncStatus` and `WatchableAsyncStatus.wrap` accept only async generators. A class that implements only `__aiter__` and `__anext__` is no longer accepted.
- On Python 3.11, awaiting a signal's `get_value()`, `read()`, `describe()` or `locate()` no longer lets other tasks run when the value is already available, as with soft and mock signals. This matches Python 3.12 and later. Code that relied on it, such as a test that checks `status.done` straight after awaiting a signal, should `await status` instead.

### Fixed

- `unstage()` now cancels a running `prepare()` or fly, so nothing it started (PMAC trajectory appends, a PandA `complete()`) is left running.
- A failed or cancelled `prepare()` stops the move to the run-up start, and leaves nothing to kick off.
- `prepare()` progress now comes from the logic, not from watching setpoint writes (#1448).
- `observe_value()` and the `wait_for_value()` and `set_and_wait_*()` helpers unsubscribe before they return, not when garbage collected.
- `StandardReadable.add_children_as_readables()` registers the children it adds in the order they were declared, so `hints`, `read()` and `describe()` no longer vary from run to run.
- `set_and_wait_for_other_value()` cancelled before the first value arrives, such as by `stop()` during a move, no longer leaves its value-watching task running.
- A signal `get_value()`, `set()` or `trigger()` cancelled just as it finishes no longer swallows the cancellation on Python 3.11.
- Leaving an `async with AsyncStatus(...)` block, `set_and_wait_for_other_value()` and the sim `BlobAcquireLogic.ensure_stopped()` no longer swallow a cancellation of the caller that arrives while they wait for the task they cancelled: they wait for that task to end, then raise the cancellation.
- A `WatchableAsyncStatus` whose watcher raises closes the async generator it drives straight away, rather than when the generator is collected.
