# 13. Create StandardMovable with Composition-Based Logic

Date: 2026-03-10

## Status

Accepted

## Context

Several device types share a common movement pattern: write a setpoint, then observe a
readback until it converges to the target. Before this change, each such device —
`Motor`, `DemoMotor`, `SimMotor`, and any future device of the same kind — had to
independently implement:

- gathering current position, calculating a timeout, and watching the readback
- emitting `WatcherUpdate` progress events
- handling a `stop()` that marks the move as failed
- the `Locatable`, `Stoppable`, and `Subscribable` bluesky protocols

`Motor` also interleaved motor-record-specific logic (soft limits, velocity-based
timeout, STOP PV) with generic setpoint/readback logic, making neither reusable.

`StandardReadable` and `StandardDetector` (ADR 0012) established the precedent: a base
class provides the bluesky protocol surface, and a composed logic object provides
device-specific behaviour.

Three design choices were resolved:

**How should logic be attached?** An initial design provided an `add_movable_logic()`
method, mirroring `add_children_as_readables`. A `StandardMovable` with no logic has no
sensible `set()` behaviour, so an abstract `@cached_property` was chosen: it requires
subclasses to supply logic at class-definition time and is checkable by static analysis.

**Should the logic class hold a back-reference to the device?** An early prototype
passed the parent device into the logic class, creating a circular dependency. The
decision was to pass individual signals as `@dataclass` fields, making the wiring
visible at construction time and keeping the logic class reusable.

**Where should `DeviceMock` logic live?** Options were a mock hierarchy mirroring the
class hierarchy, a single mock at the topmost class, or one mock per concrete class.
One mock per concrete class was chosen: it keeps mock logic next to the device it mocks
and is easiest to read.

## Decision

`StandardMovable[T]` is added to `ophyd_async.core`. Subclasses must implement:

```python
@cached_property
def movable_logic(self) -> MovableLogic: ...
```

`MovableLogic[T]` is a `@dataclass` with two required fields and five async hook
methods with safe defaults:

| Field / Method | Default |
|---|---|
| `setpoint: SignalRW[T]` | required |
| `readback: SignalR[T]` | required |
| `stop()` | no-op |
| `check_move(old, new)` | no-op |
| `calculate_timeout(old, new)` | `DEFAULT_TIMEOUT` |
| `get_units_precision()` | reads from `readback.describe()` |
| `move(new_position, timeout)` | `set_and_wait_for_other_value(setpoint, new_position, readback)` |

`StandardMovable` inherits `Device` and implements `Locatable[T]`, `Stoppable`, and
`Subscribable[T]`. Its `set()` reads the current position and units/precision in
parallel, calls `check_move`, resolves the timeout, runs `movable_logic.move()` inside
an `AsyncStatus`, emits `WatcherUpdate` events as the readback changes, and raises
`RuntimeError` if `stop(success=False)` was called.

`InstantMovableMock` is registered as the default mock class via `@default_mock_class`.
It installs a `callback_on_mock_put` on the setpoint that immediately mirrors any
written value to the readback, giving every subclass a working simulated move when
connected with `mock=True`.

`Motor` is updated to inherit from `StandardMovable` and `StandardReadable`, with a
`MotorMoveLogic` dataclass overriding all five hooks with motor-record-specific logic.
`DemoMotor` and `SimMotor` are updated the same way.

`set_mock_units` and `set_mock_precision` are added to `ophyd_async.core` so tests can
inject readback metadata without needing dedicated signal children.

## Consequences

- Any device that moves to a target value can now inherit `StandardMovable` and provide
  a `MovableLogic` subclass, rather than reimplementing the bluesky protocol surface.
- `Motor`, `DemoMotor`, and `SimMotor` lose their duplicated `set()`, `stop()`,
  `locate()`, `subscribe_reading()`, and `clear_sub()` implementations.
- The `units` and `precision` `SignalR` children of `DemoMotor` are removed; they no
  longer appear in `read_configuration()` (minor breaking change).
- Error messages from `Motor` now include the motor name.
- `set_mock_units` and `set_mock_precision` are added to the public API of
  `ophyd_async.core`.
