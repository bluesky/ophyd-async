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
- `StandardReadable` keeps one format per child, so registering a child again replaces its format. A subclass that added to the private `_describe_config_funcs`, `_read_config_funcs` or `_has_hints` adds a hook to `_describe_configuration_funcs`, `_read_configuration_funcs` or `_hints_funcs` instead.
- The deprecated `ConfigSignal` and `HintedSignal` are removed: use `StandardReadableFormat.CONFIG_SIGNAL` or `HINTED_SIGNAL`.

### Added

- `KICKED_OFF`, `TransitionError`, `StoppedError` and `Logic`, the base of `MovableLogic` and `FlyableLogic`.
- `watch_readback()` reports the progress of a move from a `FlyableLogic` hook. `SimMotor.prepare()` and `complete()` now report progress, as `Motor` does.
- `cancel_and_wait()` cancels tasks and waits for all of them to end, even through a cancel of its caller, then raises the error of the first task, in the order given, that ended with one. If its caller was cancelled, it raises `CancelledError` instead.
- `plugins_with_proc()` adds the process plugin made from a `proc_suffix` to a detector's `plugins`, and raises `ValueError` if `plugins` already has a `"proc"`. Every areaDetector vendor detector and `ContAcqDetector` uses it, so `"proc"` is reserved: pass `proc_suffix` instead.
- `StandardReadable.set_readable_format()` changes what a child contributes to `read()`, `read_configuration()` and `hints` at runtime, like `Kind` in ophyd v1, and replaces the now deprecated `add_readables()`. `store_snapshot()` and `retrieve_snapshot()` save and restore these changes, with the signal values, as a `DeviceSnapshot`, which resolves its paths against the Device when it is made. Apply one with `apply_settings(snapshot.settings)` then `apply_readable_formats(snapshot.device, snapshot.readable_formats)`.

### Deprecated

- `store_settings()` and `retrieve_settings()`: use `store_snapshot()`, and `(yield from retrieve_snapshot(...)).settings`. They now delegate to the snapshot plans, so `store_settings()` also writes `<READABLE_FORMATS>` when the tree has a `StandardReadable`, and files it writes cannot be read by older releases' `retrieve_settings()`. `retrieve_settings()` skips `<...>` sections such as `<READABLE_FORMATS>` and ignores `only_config`. dodal's `save_panda.py` and `load_panda_yaml.py` still use them.

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
