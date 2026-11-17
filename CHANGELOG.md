# Changelog

## Unreleased

### Added

- `cancel_and_wait()` cancels tasks and waits for all of them to end, even through a cancel of its caller, then raises the error of the first task, in the order given, that ended with one. If its caller was cancelled, it raises `CancelledError` instead.

### Changed

- Breaking: `WatchableAsyncStatus` and `WatchableAsyncStatus.wrap` accept only async generators. A class that implements only `__aiter__` and `__anext__` is no longer accepted.

### Fixed

- `StandardReadable.add_children_as_readables()` registers the children it adds in the order they were declared, so `hints`, `read()` and `describe()` no longer vary from run to run.
- `set_and_wait_for_other_value()` cancelled before the first value arrives, such as by `stop()` during a move, no longer leaves its value-watching task running.
- A signal `get_value()`, `set()` or `trigger()` cancelled just as it finishes no longer swallows the cancellation on Python 3.11.
- Leaving an `async with AsyncStatus(...)` block, `set_and_wait_for_other_value()` and the sim `BlobAcquireLogic.ensure_stopped()` no longer swallow a cancellation of the caller that arrives while they wait for the task they cancelled: they wait for that task to end, then raise the cancellation.
- A `WatchableAsyncStatus` whose watcher raises closes the async generator it drives straight away, rather than when the generator is collected.
