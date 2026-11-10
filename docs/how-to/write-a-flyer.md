# How to write a flying Device

A *flyer* is a Device that hardware-triggers a scan: bluesky prepares it, kicks it
off, then waits for it to complete while the hardware runs autonomously. Rather than
implement the `Preparable`, `Flyable`, and `Stageable` protocols by hand, compose a
[](#FlyableLogic) instance into a [](#StandardFlyable). `StandardFlyable` drives the
phases in order and threads a context object between them:

- `prepare(value)` → `FlyableLogic.prepare_to_fly(name, value, previous_ctx)`, an async generator that works
  out the scan and yields a context object, then sets the hardware up and moves to the
  start. It may report progress.
- `kickoff()` → starts `FlyableLogic.fly(ctx)`, an async generator that `StandardFlyable`
  runs in the task of a status. `kickoff()` returns when it yields `KICKED_OFF`, once the
  scan is up to speed.
- `complete()` returns that status, which finishes when `fly` does and reports the
  progress it yields after `KICKED_OFF`.

The flyer must be staged first: `prepare()` is only allowed after `stage()`, `kickoff()`
only after `prepare()`, and `complete()` only after `kickoff()`; a verb called out of
order raises `TransitionError`. After `complete()` the flyer can `prepare()` again for the
next point without restaging. `stage()` raises unless the flyer is unstaged, as does a
second `prepare()` before `complete()`. If `fly` fails before yielding `KICKED_OFF`, `kickoff()`
fails; after it, `complete()` fails. Either leaves the flyer staged. Cancelling
`complete()`'s status cancels `fly`, and so does cancelling `kickoff()` before
`KICKED_OFF`.

`stage()` runs the logic's `ensure_ready`, which defaults to `ensure_stopped`.
`unstage()` works from any state: it cancels a `prepare()` or `fly` in flight (which sees
`CancelledError`) and waits for it, then always runs `ensure_stopped` to stop the
hardware. If the cancelled verb raised while being cancelled, `unstage()` raises it after `ensure_stopped`. On a device that also moves,
`stop()` ends only a `set()`: it does not end a `prepare()` or `fly`, but its
`ensure_stopped` halts the hardware, so a `stop()` during the run-up can leave
`prepare()` finishing short of the start. The hook names are deliberately not bluesky verbs, so a
logic passed to a plan stub does not look like a device.

## Implementing FlyableLogic

Subclass [](#FlyableLogic) — it is generic over two types: `PrepareT`, the per-scan
info passed to `prepare()`; and `CtxT`, the context `prepare_to_fly` passes to `fly`.
`StandardFlyable` holds the context until the next `stage()`, and passes it to the next
`prepare_to_fly` as `previous_ctx` (`None` for the first since `stage()`). It defaults
to `None`, so `FlyableLogic[PrepareT]` carries no state and its `prepare_to_fly` yields
`None` first. `prepare()` keeps the context only if `prepare_to_fly` finishes, so a
failed one leaves nothing to kick off. Fill in the hooks that your hardware needs:

| Method | Default behaviour | Override to… |
|--------|-------------------|--------------|
| `prepare_to_fly(name, value, previous_ctx)` | *abstract* | as an async generator: yield the context first, then set up the hardware, yielding any progress (see [](#flyer-progress)) |
| `fly(ctx)` | *abstract* | run the scan as an async generator: yield `KICKED_OFF` once up to speed, then any progress, and return when it is done |
| `ensure_stopped()` | *abstract* | stop the hardware and wait until it has stopped |
| `ensure_ready()` | calls `ensure_stopped()` | set the hardware up on `stage()` if it differs from stopping it |

`prepare_to_fly` and `fly` must not leave anything running that they do not wait for,
because `StandardFlyable` cancels them on `unstage()` and expects that to stop
everything they started. Own a status with `async with AsyncStatus(...) as status:`, which cancels it on
the way out, and run concurrent work with [](#watch_readback) or an
`asyncio.TaskGroup`.

There are two ways to get a Device out of a `FlyableLogic`: mix `StandardFlyable` into
a Device class (for hardware that is always a flyer, like a motor), or call
[](#FlyableLogic.with_device) to wrap a bare logic object in an ephemeral flyer inside
a plan (for hardware configured per scan, like a PandA block).

(flyer-progress)=
### Reporting progress

`prepare()` and `complete()` can report progress to watchers as [](#WatcherUpdate)s,
stamped with the flyer's name.

- `prepare_to_fly` yields `WatcherUpdate`s after the context, for example the progress
  of the move to the start. They go to the watchers of `prepare()`.
- `fly` yields `WatcherUpdate`s after `KICKED_OFF`. They go to the watchers of
  `complete()`, which also gets the latest one yielded before it was called.

## A movable device that also flies

An EPICS [](#Motor) is the first case: it is a [](#StandardMovable) *and* a
`StandardFlyable` (and a [](#StandardReadable)). A single logic object,
`MotorFlyableMovableLogic`, implements both [](#MovableLogic) and `FlyableLogic`, so
its fly hooks can reuse the same `move`/`check_move` methods as a normal `set()`. The
per-scan info is a [](#FlyMotorInfo) and the threaded context is a small frozen
dataclass of everything `prepare_to_fly` works out:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: MotorPrepareCtx
```

`prepare_to_fly` validates the requested velocity and the run-up and run-down positions
against the motor's limits and yields the context. It then owns the move to the run-up
start with `async with AsyncStatus(...)`, and yields its progress from
[](#watch_readback), which watches the readback of the logic until the move is done:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: MotorFlyableMovableLogic.prepare_to_fly
```

`fly` starts the move to the far end of the run-down, waits out the run-up so the motor
is at constant velocity when `kickoff()` returns, then yields the progress of the rest of
the move:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: MotorFlyableMovableLogic.fly
```

`ensure_stopped` is shared with `MovableLogic`, so it serves both `stop()` and
`unstage()`. It sends `.STOP` every time and waits for the motor to be done moving:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: MotorFlyableMovableLogic.ensure_stopped
```

Opting in to progress is up to each hook: the same [](#WatcherUpdate) machinery as
[](#StandardMovable.set) is used, but a flyer whose logic is *not* movable (see the next
section) just waits with no progress updates. See
[](../explanations/when-to-extend-movable.md) for more on `MovableLogic`.

Wire the logic into the Device with a `@cached_property`. `Motor` builds one shared
instance and returns it as its single `logic`, which both the movable and flyable
mix-ins declare (see [ADR 0021](../explanations/decisions/0021-single-logic-property.md) for why), so the move and fly paths act
on the same signals:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: Motor.logic
```

## An ephemeral flyer created in a plan

Some hardware is only a flyer for the duration of a scan and is configured differently
each time. The PandA position-compare block is an example: [](#StaticPcompFlyableLogic)
wraps a single `PcompBlock` and carries no state between phases, so it is a
`FlyableLogic[PcompInfo]`. Its `prepare_to_fly` yields its `None` context, then disarms
and programs the block from the per-scan [](#PcompInfo):

```{literalinclude} ../../src/ophyd_async/fastcs/panda/_fly_logic.py
:language: python
:pyobject: StaticPcompFlyableLogic.prepare_to_fly
```

`fly` enables the block, yields `KICKED_OFF` once it is active, then waits for it to go
inactive again. It reports no progress:

```{literalinclude} ../../src/ophyd_async/fastcs/panda/_fly_logic.py
:language: python
:pyobject: StaticPcompFlyableLogic.fly
```

`ensure_stopped` disarms the block and waits for it to go inactive; it is called on
`unstage()` and, through the default `ensure_ready`, on `stage()`:

```{literalinclude} ../../src/ophyd_async/fastcs/panda/_fly_logic.py
:language: python
:pyobject: StaticPcompFlyableLogic.ensure_stopped
```

Rather than declare this logic on a Device class, construct it in the plan from the
PandA block you want to drive and call [](#FlyableLogic.with_device) to get a flyer
to stage, prepare, kickoff, complete and unstage:

```python
flyer = StaticPcompFlyableLogic(panda.pcomp[1]).with_device(name="pcomp")
```

```{seealso}
[](./choose-right-baseclass.md) for how `StandardFlyable` fits alongside the other
base classes.
```
