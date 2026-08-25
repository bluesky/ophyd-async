# How to write a flying Device

A *flyer* is a Device that hardware-triggers a scan: bluesky prepares it, kicks it
off, then waits for it to complete while the hardware runs autonomously. Rather than
implement the `Preparable`, `Flyable`, and `Stageable` protocols by hand, compose a
[](#FlyableLogic) instance into a [](#StandardFlyable). `StandardFlyable` drives the
three phases in order and threads a context object between them:

- `prepare(value)` → `FlyableLogic.on_prepare(value)` moves to the start and arms the
  hardware, returning a context object.
- `kickoff()` → `FlyableLogic.on_kickoff(ctx)` starts the scan, returning the
  (possibly updated) context.
- `complete()` → `FlyableLogic.on_complete(ctx)` blocks until the scan is done.

`stage()`/`unstage()` run the logic's `on_stage`/`on_unstage`, which default to `stop`.

## Implementing FlyableLogic

Subclass [](#FlyableLogic) — it is generic over two types: `PrepareT`, the per-scan
info passed to `prepare()`, and `CtxT`, the context threaded between the phases (use
`None` if there is no state to carry). Fill in the hooks that your hardware needs:

| Method | Default behaviour | Override to… |
|--------|-------------------|--------------|
| `on_prepare(value)` | *abstract* | move to the start, arm the hardware, and return a context |
| `on_kickoff(ctx)` | *abstract* | start the scan and return the context for `on_complete` |
| `on_complete(ctx)` | *abstract* | block until the scan finishes |
| `stop()` | no-op | disarm the hardware and wait for it to stop |
| `on_stage()` | calls `stop()` | set the hardware up on `stage()` if it differs from stop |
| `on_unstage()` | calls `stop()` | clean the hardware up on `unstage()` if it differs from stop |

There are two ways to get a Device out of a `FlyableLogic`: mix `StandardFlyable` into
a Device class (for hardware that is always a flyer, like a motor), or call
[](#FlyableLogic.with_device) to wrap a bare logic object in an ephemeral flyer inside
a plan (for hardware configured per scan, like a PandA block).

## A movable device that also flies

An EPICS [](#Motor) is the first case: it is a [](#StandardMovable) *and* a
`StandardFlyable` (and a [](#StandardReadable)). A single logic object,
`MotorFlyableMovableLogic`, implements both [](#MovableLogic) and `FlyableLogic`, so
its fly hooks can reuse the same `move`/`check_move` methods as a normal `set()`. The
per-scan info is a [](#FlyMotorInfo) and the threaded context is a small dataclass that
carries the move status from `on_kickoff` to `on_complete`:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: MotorFlyCtx
```

`on_prepare` validates the requested velocity against the motor's limits, moves to the
run-up start position, and returns the context:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: MotorFlyableMovableLogic.on_prepare
```

`on_kickoff` starts the move to the far end of the run-down and stashes the resulting
status on the context so `on_complete` can await it:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: MotorFlyableMovableLogic.on_kickoff
```

`on_complete` simply blocks on that status:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: MotorFlyableMovableLogic.on_complete
```

Because the logic is also a `MovableLogic`, `complete()` reports progress to watchers
(e.g. progress bars) automatically by observing the readback — reusing the same
[](#WatcherUpdate) machinery as [](#StandardMovable.set). A flyer whose logic is *not*
movable (see the next section) just blocks with no progress updates. See
[](../explanations/when-to-extend-movable.md) for more on `MovableLogic`.

Wire the logic into the Device with a `@cached_property`. `Motor` builds one shared
instance and returns it from both `movable_logic` and `flyable_logic` so the move and
fly paths act on the same signals:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: Motor._logic
```

```python
@cached_property
def movable_logic(self) -> MotorFlyableMovableLogic:
    return self._logic

@cached_property
def flyable_logic(self) -> MotorFlyableMovableLogic:
    return self._logic
```

## An ephemeral flyer created in a plan

Some hardware is only a flyer for the duration of a scan and is configured differently
each time. The PandA position-compare block is an example: [](#StaticPcompFlyableLogic)
wraps a single `PcompBlock` and carries no state between phases, so it is a
`FlyableLogic[PcompInfo, None]`. Its `on_prepare` disarms then programs the block from
the per-scan [](#PcompInfo):

```{literalinclude} ../../src/ophyd_async/fastcs/panda/_fly_logic.py
:language: python
:pyobject: StaticPcompFlyableLogic.on_prepare
```

`on_kickoff` enables the block and waits for it to go active, while `on_complete` waits
for it to go inactive again (the context is `None`, so it is ignored):

```{literalinclude} ../../src/ophyd_async/fastcs/panda/_fly_logic.py
:language: python
:pyobject: StaticPcompFlyableLogic.on_kickoff
```

```{literalinclude} ../../src/ophyd_async/fastcs/panda/_fly_logic.py
:language: python
:pyobject: StaticPcompFlyableLogic.on_complete
```

`stop()` disarms the block; it is called by the default `on_stage`/`on_unstage`:

```{literalinclude} ../../src/ophyd_async/fastcs/panda/_fly_logic.py
:language: python
:pyobject: StaticPcompFlyableLogic.stop
```

Rather than declare this logic on a Device class, construct it in the plan from the
PandA block you want to drive and call [](#FlyableLogic.with_device) to get a ready
flyer to prepare, kickoff, and complete:

```python
flyer = StaticPcompFlyableLogic(panda.pcomp[1]).with_device(name="pcomp")
```

```{seealso}
[](./choose-right-baseclass.md) for how `StandardFlyable` fits alongside the other
base classes.
```
