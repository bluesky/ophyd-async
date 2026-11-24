# 22. `fly` is a generator, and `ensure_stopped` waits

Date: 2026-10-20

## Status

Accepted

Amends ADR 0017: `MovableLogic.stop()` is now `ensure_stopped()`, and the fly hooks are different from the ones that ADR describes.

## Context

`FlyableLogic` had separate `on_kickoff` and `on_complete` hooks, and `stop()` returned as soon as it had asked the hardware to stop. This allowed three kinds of bug. A scan started in `on_kickoff` could outlive `unstage()`, because nothing owned it. A new `stage()` or `set()` could start while the previous motion was still decelerating. A `set()` caught by `stop()` before its move had started was not ended, and ran on after it.

## Decision

**`prepare_to_fly()` and `fly()` are async generators.** `prepare_to_fly` yields the context then any progress, and `fly` yields `KICKED_OFF` once flying then any progress. What a scan starts lives in the generator's scope, so closing or cancelling the generator stops it, and a failure maps on to the verb that was running. We rejected two hooks sharing state through the logic, and a hook returning a `(context, progress)` tuple, which leaked the progress iterator when `prepare()` failed.

**The hooks are not named after bluesky verbs.** `prepare_to_fly`, `fly`, `ensure_ready` and `ensure_stopped` do not collide with `prepare`, `kickoff`, `stage` and `unstage`, so a logic passed to a plan is not mistaken for a device.

**The fly runs in the status that `complete()` returns.** `kickoff()` makes a `WatchableAsyncStatus` that drives `fly` and returns at `KICKED_OFF`, and `complete()` returns that same status. It already replays the latest update to a late watcher, so no separate task, update forwarding or cleanup path is needed, and cancelling that status cancels the fly.

**`ensure_stopped()` waits until the motion has ended.** `unstage()` cancels `fly`, then calls `ensure_stopped()`, so when it returns nothing is running and the hardware is still. Returning early would leave the next `stage()` or `set()` racing the deceleration.

**One stop future ends a set.** Each `set()` passes a fresh future to its `WatchableAsyncStatus`, which races the move against it; the device keeps the latest one. `stop()` resolves it rather than cancelling the status, because `RunEngine.pause` calls `stop(success=True)` and expects the `set()` to finish cleanly, which a cancel cannot do. A new `set()` resolves the previous future too, so it supersedes the old move. `stop()` reaches only a `set()`: a `prepare()` or fly is ended by `unstage()` through the state machine.

**Only a flyer stages, and `unstage()` always stops.** `StandardFlyable` calls `ensure_ready()` on `stage()` and always calls `ensure_stopped()` on `unstage()`, a `set()` in progress included; a `StandardMovable` alone does nothing on either. Sparing a `set()` would only defer its stop, as the RunEngine stops every movable it set when a run ends or pauses. `Motor.ensure_stopped()` sends `.STOP` even if `.DMOV` reads 1, because `.DMOV` can still read 1 just after a move is requested, and flickers at standstill on some motors.

The resulting model:

| Verb | Mix-in | Does |
|------|--------|------|
| `stage()` | `StandardFlyable` | calls `logic.ensure_ready()` |
| `unstage()` | `StandardFlyable` | cancels a `prepare()` or fly in progress, then calls `logic.ensure_stopped()` |
| `stop()` | `StandardMovable` | ends the `set()` via the stop future, then calls `logic.ensure_stopped()` |
| `set()` | `StandardMovable` | supersedes the `set()` in progress |

## Consequences

- The `unstage()` of one plan and the `stage()` of the next may overlap; we accept this, assuming every plan uses the stage/unstage decorator.
- A `FlyableLogic` that also moves stops a `set()` in progress at `stage()`; override `ensure_ready()` if that is wrong.
- A `FailedStatus` that bluesky raises from `unstage()` can mask the plan's own error.
- A `stop()` during the run-up can leave `prepare()` finishing short of the start; a future `pause()` hook is the place to fix that.
- A failed verb needs `unstage()` before the device is used again, so the next `prepare()` starts from hardware that `ensure_stopped()` and `ensure_ready()` have settled.
