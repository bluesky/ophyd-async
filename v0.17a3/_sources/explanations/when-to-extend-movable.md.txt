# When should a device extend movable

The [`Movable`](#bluesky.protocols.Movable) protocol indicates that a device has a `set` method which can be called in the bluesky through the plan stubs [`bps.abs_set`](#bluesky.plan_stubs.abs_set) and [`bps.mv`](#bluesky.plan_stubs.mv). The [RunEngine](#bluesky.run_engine.RunEngine) treats this `set` as an atomic operation. A `Movable` device is appropriate when:

- The `set` involves changing multiple signals in parallel alongside a desired ordering of the setting of signals - having this logic inside an asyncio function can provide speedup.

- The `RunEngine` should not be altering any other devices while this `set` is taking place.

- There is only one clear interpretation of what it means to set the device. For example, setting a motor is fairly unambiguous whereas setting a detector could mean a number of different things.

- You are doing some logic that a user will almost always want to do with this device.

The `set` method, in general, should be used be used with primitive values rather than more complex types, for example, dataclasses. Using the latter here leads to extra boilerplate at the plan level. An exception to this is where using `set` will provide speedup - in this case it could be worth the extra boilerplate.

## What to use instead

If the device doesn't satisfy the above criteria, it is generally more suitable to be using combinations of [`bps.mv`](#bluesky.plan_stubs.mv) and [`bps.abs_set`](#bluesky.plan_stubs.abs_set) on individual signals of a plan's devices. This avoids adding unnecessary complexity to the device whilst giving the plan more flexability.
