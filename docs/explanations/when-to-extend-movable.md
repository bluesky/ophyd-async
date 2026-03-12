# When should a device extend movable

The [`Movable`](#bluesky.protocols.Movable) protocol indicates that a device has a `set` method which can be called in bluesky through the plan stubs [`bps.abs_set`](#bluesky.plan_stubs.abs_set) and [`bps.mv`](#bluesky.plan_stubs.mv). The [RunEngine](#bluesky.run_engine.RunEngine) treats this `set` as an atomic operation. A `Movable` device is appropriate when:

- The `set` involves changing multiple signals in parallel alongside a desired ordering of the setting of signals - having this logic inside an asyncio function can provide speedup.

- The `RunEngine` should not be altering any other devices while this `set` is taking place.

- There is only one clear interpretation of what it means to set the device. For example, setting a motor is fairly unambiguous whereas setting a detector could mean a number of different things.

- You are doing some logic that a user will almost always want to do with this device.

The `set` method, in general, should be used with primitive values rather than more complex types, for example, dataclasses. Using the latter here leads to extra boilerplate at the plan level. An exception to this is where using `set` will provide speedup - in this case it could be worth the extra boilerplate.

## What to use instead

If the device doesn't satisfy the above criteria, it is generally more suitable to use combinations of [`bps.mv`](#bluesky.plan_stubs.mv) and [`bps.abs_set`](#bluesky.plan_stubs.abs_set) on individual signals of a plan's devices. This avoids adding unnecessary complexity to the device whilst giving the plan more flexibility.

## Using StandardMovable

If your device moves to a target value and waits for a readback signal to confirm it
has arrived, use [](#StandardMovable) rather than implementing `Movable` directly.
This covers a wide range of hardware:

- Motor-like stages that use a non-motor IOC (e.g. piezo stages, hexapods)
- Temperature controllers, beam attenuators, and similar "set value, wait for readback" devices
- Simulation motors
- Any Tango or EPICS device that follows the same setpoint/readback pattern

`StandardMovable` handles the full bluesky protocol surface (`Locatable`, `Stoppable`,
`Subscribable`) as well as the `WatcherUpdate` machinery for progress bars. You only
need to describe what is device-specific.

### Implementing MovableLogic

Create a `@dataclass` subclass of [](#MovableLogic) that adds any extra signals your
device needs, and override the hook methods that differ from the defaults:

```{literalinclude} ../../src/ophyd_async/epics/demo/_motor.py
:pyobject: DemoMotorMoveLogic
```

The available hooks are:

| Method | Default behaviour | Override to… |
|--------|-------------------|--------------|
| `stop()` | no-op | trigger a stop signal or cancel an in-flight command |
| `check_move(old, new)` | no-op | validate soft limits before the move begins |
| `calculate_timeout(old, new)` | `DEFAULT_TIMEOUT` | derive a velocity-based or distance-based timeout |
| `get_units_precision()` | reads from `readback.describe()` | supply units and precision from dedicated signals |
| `move(new_position, timeout)` | `set_and_wait_for_other_value` | write the setpoint and wait in a device-specific way |

### Wiring it into the Device

Attach the logic via a `@cached_property` in the Device subclass. Multiple inheritance
with [](#StandardReadable) is supported and is the normal pattern:

```{literalinclude} ../../src/ophyd_async/epics/demo/_motor.py
:pyobject: DemoMotor
```

[](#StandardMovable.set_name) automatically renames the readback signal to match the
device name, so `read()` reports `stage.x` rather than `stage.x.readback`.

### Testing a StandardMovable

Connecting a `StandardMovable` subclass with `mock=True` automatically installs
[](#InstantMovableMock), which mirrors every setpoint write immediately to the
readback. This means most tests work without any extra setup:

```python
async with init_devices(mock=True):
    motor = MyMotor("PREFIX:")

await motor.set(10.0)
assert (await motor.locate())["readback"] == 10.0
```

```{seealso}
[](../tutorials/writing-tests-for-devices.md) for how to write tests against a
`StandardMovable` device, including how to define custom automatic mock behaviour and
how to opt out of the default mock for fine-grained control.
```
