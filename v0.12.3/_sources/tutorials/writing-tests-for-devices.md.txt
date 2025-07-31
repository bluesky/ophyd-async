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

```{literalinclude} ../../tests/epics/demo/test_epics_demo.py
:pyobject: mock_motor
```

This will use [](#init_devices) to call [](#Device.connect) with `mock=True`. This will recursively replace the real connection to hardware with a mock that allows us to change the Signal's value that our code will see and capture any attempts to set the value from our code. In this case we know our tests will expect `units="mm"` and `precision=3`, so we use [](#set_mock_value) to those here.

If we had any cleanup to do, we would do that after the yield statement.

:::{note}
This is an async fixture, and we will be using async tests, so we need to install and configure [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) in our projects's `pyproject.toml`:

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

```{literalinclude} ../../tests/epics/demo/test_epics_demo.py
:pyobject: test_read_motor
```

We write an `async` test method so we can `await` our calls to verbs. We include the fixture we defined earlier in the function arguments and pytest will automatically create it for us and pass it to the function call. We make use of the [](#assert_reading), [](#assert_value) and [](#assert_configuration) helpers to check that our motor gives the right output, then use [](#set_mock_value) to change the value of the read only Signal before checking the verbs give the right output.

```{note}
Some of our tests produce timestamps, instead of checking their values we use [](#unittest.mock.ANY) to say that the timestamp just has to be present to pass.
```

## Checking that signals were changed

Now let's call some verbs and check that they do the right thing. We want to check that `stop()` triggers the [](#SignalX) `stop_`, waiting for it to complete:

```{literalinclude} ../../tests/epics/demo/test_epics_demo.py
:pyobject: test_motor_stopped
```

This time we use [](#get_mock_put) to get a [](#unittest.mock.Mock) that will be called every time `stop_.trigger()` is called. We check it hasn't been called, then call our method, then check it has been called with `None` (what a SignalX sends to tell the backend to put the value needed to trigger). We also show that we can call [](#get_mock) on the parent to see all of the mock calls that have been made on all it's children, useful to check ordering.

## Checking for watcher updates

Now let's pretend to be a progress bar and check that we get the right outputs. We want to check that `set()` will call any progress watchers with appropriate updates, and also terminate when the readback value reaches the correct value:

```{literalinclude} ../../tests/epics/demo/test_epics_demo.py
:pyobject: test_motor_moving_well
```

Here we call the verb, but don't wait for it to complete (as that would wait forever). Instead we attach a [](#StatusWatcher) to the [](#WatchableAsyncStatus) that `set()` returns, and periodically call [](#set_mock_value) on the readback, checking that our watcher was called with the right values. When we give it a value that should make `set()` terminate, we call [](#wait_for_pending_wakeups) to make sure the background tasks get some time to finish correctly before checking the status completed successfully.

## Other test utilities

There are a few other things we may wish to do in tests:
- [](#set_mock_values) if you want to set a series of mock values, with repeated checks at each value
- [](#callback_on_mock_put) to allow setting a Signal to have side effects, like setting another Signal
- [](#set_mock_put_proceeds) to block or unblock `Signal.set(..., wait=True)` from completing
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

```{literalinclude} ../../tests/epics/demo/test_epics_demo.py
:pyobject: mock_point_detector
```

```{literalinclude} ../../tests/epics/demo/test_epics_demo.py
:pyobject: test_point_detector_in_plan
```

Here we create a [](#collections.defaultdict) and put the RunEngine produced documents in it. Then we use [](#set_mock_value) to set the channels of the detector to some known values. Finally we run the plan and use [](#assert_emitted) to check the correct numbers of documents have been produced. We can also inspect individual documents for more details.

## Conclusion

In this tutorial we have explored how to write tests for Devices without having the hardware available, by using connection in mock mode. 
