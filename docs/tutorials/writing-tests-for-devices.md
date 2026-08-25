# Writing Tests for Devices

In this tutorial we will explore how to write tests for ophyd-async Devices that do not require the real hardware. This allows us to catch bugs in our logic by inspecting what it would send to the hardware, and once it is working gives us confidence that it will stay working. Python provides some standard tools like [mocking, patching](#unittest.mock) and [fixtures](inv:pytest#fixtures), and ophyd-async provides some utility methods to help too.

There are two categories of test that will typically be written for a Device:
- Tests that call the bluesky verbs (like `set()` or `read()`) directly
- Tests that execute a bluesky plan (like `bp.count()`) under a RunEngine

The first category are generally for low level tests like checking a motor will pass the correct units up to the progress bar or that it times out if the move is too short. The second category is for higher level tests like checking a detector will produce the correct files when used in a standard plan. Both will be needed at some point, so this tutorial will cover how to write the tests and when to use them.

## Tests that call the bluesky verbs directly

If we need to add a feature to a particular Device, or fix a bug, and it only affects a single verb, then we will probably test the device outside the bluesky RunEngine, calling the verbs directly. This means we need to:
- Create the Device
- Set some mock values for the Signals on it
- Call the verb
- Inspect the results
- Possibly do some cleanup

### Create a fixture and set signal values

We will be writing a test using the pytest framework which encourages fixtures to setup and teardown the Devices we wish to test. In this case we will create the `DemoMotor` from the previous tutorial:

```{literalinclude} ../../tests/unit_tests/epics/demo/test_epics_demo.py
:pyobject: mock_motor
```

This fixture opts out of the [automatic mock behaviour](../explanations/when-to-extend-movable.md) by connecting with a plain [](#LazyMock), giving the tests control over when the readback updates mid-move. [](#set_mock_units) and [](#set_mock_precision) inject units and precision metadata directly on the readback signal, without needing dedicated child signals on the device.

If we had any cleanup to do, we would do that after the yield statement.

### Automatic mock behavior injection

If you find yourself repeatedly using [](#callback_on_mock_put) to set up the same mock
behavior for a Device type across many tests, you can define a [](#DeviceMock) subclass
to automatically inject that behavior when the Device is connected in mock mode. This is
especially useful for defining standard mock behavior alongside your Device definitions.

For example:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:pyobject: InstantMotorMock
```

Then decorate the original class with [](#default_mock_class) so it is automatically
used when connected in mock mode:

```{literalinclude} ../../src/ophyd_async/epics/motor.py
:language: python
:start-at: default_mock_class(
:end-at: class Motor
```

Now whenever a `Motor` is connected using [](#init_devices)`(mock=True)`, it will
automatically use `InstantMotorMock` without any fixture setup. You can still override
the automatic mock for specific tests by passing an explicit [](#DeviceMock) instance
or a plain [](#LazyMock) directly to `connect()`, as the `mock_motor` fixture above does.

### pytest-asyncio setup

:::{note}
Fixtures and tests for async Devices must be `async`. To enable this, install and configure [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) in your project's `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "pytest-asyncio",
    # other dependencies
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
# other options
```
:::

### Checking the output of verbs in tests

Let's test some verbs. We want to check that we can `read()` and `read_configuration()` on a `DemoMotor` while staged, and that we can still call them when unstaged:

```{literalinclude} ../../tests/unit_tests/epics/demo/test_epics_demo.py
:pyobject: test_read_motor
```

We write an `async` test method so we can `await` our calls to verbs. We include the fixture we defined earlier in the function arguments and pytest will automatically create it for us and pass it to the function call. We make use of the [](#assert_reading), [](#assert_value) and [](#assert_configuration) helpers to check that our motor gives the right output, then use [](#set_mock_value) to change the value of the read only Signal before checking the verbs give the right output.

```{note}
Some of our tests produce timestamps, instead of checking their values we use [](#unittest.mock.ANY) to say that the timestamp just has to be present to pass.
```

## Checking that commands and signals were called

Now let's call some verbs and check that they do the right thing. We want to check that `stop()` triggers the [](#TriggerableCommand) `stop_`, waiting for it to complete:

```{literalinclude} ../../tests/unit_tests/epics/demo/test_epics_demo.py
:pyobject: test_motor_stopped
```

This time we use [](#get_mock_execute) to get an [](#unittest.mock.AsyncMock) that will be called every time `stop_.trigger()` is called. We check it hasn't been called, then call our method, then check it has been called with no arguments. We also show that we can call [](#get_mock) on the parent to see all of the mock calls that have been made on all its children, useful to check ordering.

For [](#Signal)s, the equivalent is [](#get_mock_put), which returns an `AsyncMock` that records every `Signal.set()` / `put()` call.

## Checking for watcher updates

Now let's pretend to be a progress bar and check that we get the right outputs. We want to check that `set()` will call any progress watchers with appropriate updates, and also terminate when the readback value reaches the correct value:

```{literalinclude} ../../tests/unit_tests/epics/demo/test_epics_demo.py
:pyobject: test_motor_moving_well
```

Here we call the verb, but don't wait for it to complete (as that would wait forever). Instead we attach a [](#StatusWatcher) to the [](#WatchableAsyncStatus) that `set()` returns, and periodically call [](#set_mock_value) on the readback, checking that our watcher was called with the right values. When we give it a value that should make `set()` terminate, we call [](#wait_for_pending_wakeups) to make sure the background tasks get some time to finish correctly before checking the status completed successfully.

(mocking-put)=
## Setting side effects on mocks

By default, a [](#Signal) connected in mock mode records all `put()` calls and stores the put value as the readback. Use [](#callback_on_mock_put) to inject side effects — for example, to propagate a setpoint write through to a readback:

```python
with callback_on_mock_put(motor.setpoint, lambda v: set_mock_value(motor.readback, v)):
    await motor.setpoint.set(10.0)
# motor.readback is now 10.0
```

The callback is cleared automatically when the context exits. For a persistent side effect across a whole test, call it as a plain function (without `with`).

The callback may be **either a sync function or an `async def` coroutine function**. An async callback is awaited before the `put()` completes, so use one when the side effect itself needs to `await` — for instance setting another Signal via its `set()`:

```python
async def on_put(value: float) -> None:
    await motor.velocity.set(value / 2)

with callback_on_mock_put(motor.setpoint, on_put):
    await motor.setpoint.set(10.0)
```

Either way, the value the callback returns (if not `None`) becomes the readback; returning `None` leaves the readback as the value that was put.

For a [](#Command) backed by [](#soft_command) and connected in mock mode, the original Python function is called by default — mock mode behaves identically to real mode unless you intervene. Use [](#get_mock_execute) to assert the call was made, or use [](#callback_on_mock_execute) to suppress the real function and return something else. Like [](#callback_on_mock_put), it takes a sync or async callback, and its return value becomes the result of `execute()`.

For hardware-backed [](#Command)s (e.g. EPICS), there is no underlying Python function to call: mock mode returns a manufactured "empty" default for the declared return type (e.g. 0 for ints, [] for arrays). The same `callback_on_mock_execute` override applies.

## Mocking out a verb

Sometimes a test wants to intervene at the level of a whole verb — for example to
check that `kickoff()` calls `set()` with the right target without actually running
the move. There are three ways to do this, in order of preference:

1. **Make the underlying mock Signals behave so the real verb "just works."** Drive
   the Signals the verb reads and writes with [](#set_mock_value) and
   [](#callback_on_mock_put) (see [above](#mocking-put)) so the verb completes
   against mock hardware and you assert on its effects. This is the closest thing to
   the real device, so prefer it — the trade-off is that it won't let you easily
   exercise what a plan does when a verb *fails*, since the real logic still runs.
2. **Replace the verb with a mock using [](#set_mock_attr).** Reach for this when you
   specifically want to bypass the verb's logic — e.g. to assert it was called with
   the right argument, or to make it fail on demand:

   ```python
   mock_set = set_mock_attr(motor, "set", MagicMock())
   await motor.kickoff()
   mock_set.assert_called_once_with(-3.0)
   ```

   A plain `motor.set = MagicMock()` raises `NameError`, because [](#Device) reserves
   the bluesky protocol method names (`set`, `read`, `trigger`, ...) to stop a Signal
   accidentally shadowing a verb. [](#set_mock_attr) sets the attribute anyway and
   returns the mock, so the override and the assertion fit in one expression.
3. **Disable the check globally with [](#OPHYD_ASYNC_ALLOW_RESERVED_ATTRS)`=YES`.**
   This is a migration escape hatch only: if you are bringing an existing test suite
   onto a version of ophyd-async that adds this check, set it to turn the suite green
   before migrating each `motor.set = ...` call site over to `set_mock_attr`.

## Other test utilities

There are a few other things we may wish to do in tests:
- [](#set_mock_attr) to override a verb (or any reserved-name attribute) on a Device with a mock
- [](#set_mock_values) if you want to set a series of mock values, with repeated checks at each value
- [](#set_mock_units) and [](#set_mock_precision) to set units and precision metadata on a Signal without needing dedicated child signals
- [](#callback_on_mock_put) to allow setting a Signal to have side effects, like setting another Signal (sync or async callback)
- [](#callback_on_mock_execute) to override the function called when a Command is executed (sync or async callback)
- [](#get_mock_put) to get the `AsyncMock` tracking `put()` calls on a Signal
- [](#get_mock_execute) to get the `AsyncMock` tracking `execute()` calls on a Command
- [](#set_mock_put_proceeds) to block or unblock `Signal.set()` from completing
- [](#mock_puts_blocked) a context manager that blocks put proceeds at the start, and unblocks at the end

## Tests that execute a bluesky plan

If we need to check that our Device performs correctly within a plan that calls multiple verbs, it is best to test it under an actual RunEngine. This allows you to check that when the verbs are called in the order that they are in the plan, the correct behavior occurs.

(run-engine-fixture)=
### Create a RunEngine in a fixture

First you need to define a RunEngine that could be used in any test. If you don't already have one in your project you could define one like this:

```python
@pytest.fixture(scope="function")
def RE():
    RE = RunEngine(call_returns_result=True)
    yield RE
    if RE.state not in ("idle", "panicked"):
        RE.halt()
```

### Run a plan and inspect the documents it produces

Now you can run a plan, and check that it produces the correct bluesky documents. Let's go back to the demo and test the `DemoPointDetector` in a `bp.count` plan:

```{literalinclude} ../../tests/unit_tests/epics/demo/test_epics_demo.py
:pyobject: mock_point_detector
```

```{literalinclude} ../../tests/unit_tests/epics/demo/test_epics_demo.py
:pyobject: test_point_detector_in_plan
```

Here we create a [](#collections.defaultdict) and put the RunEngine produced documents in it. Then we use [](#set_mock_value) to set the channels of the detector to some known values. Finally we run the plan and use [](#assert_emitted) to check the correct numbers of documents have been produced. We can also inspect individual documents for more details.

## Conclusion

In this tutorial we have explored how to write tests for Devices without having the hardware available, by using connection in mock mode. 
