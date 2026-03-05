(interact-with-signals)=
# How to interact with signals while implementing bluesky verbs

To implement bluesky verbs, you typically need to interact with Signals. This guide will show you how to do the following operations on a Signal:
- Get the value
- Set the value
- Observe every value change
- Wait for the value to match some expected value

## Get the value

To get a single signal value, you can call [](#SignalR.get_value), awaiting the response:
```python
value = await signal.get_value()
```

You can wrap these with [](#asyncio.gather) if you need to get multiple values at the same time:
```python
value1, value2 = await asyncio.gather(signal1.get_value(), signal2.get_value())
```

## Set the value

To set a single value and wait for it to complete (for up to a timeout) you can call [](#SignalW.set):
```python
await signal.set(value, timeout)
```
If you want to do something else while waiting for it to complete you can store the signal it returns and await it later:
```python
status = signal.set(value, timeout)
# do something else here
await status
```

## Observe every value change

To observe every value change and run a function on that value you can use [](#observe_value):
```python
async for value in observe_value(signal):
    do_something_with(value)
```
This will run until you `break` out of the loop.

You can pass `timeout` to specify the maximum time to wait for a single update.

If you want to wait for multiple signals you can use [](#observe_signals_value):
```python
async for signal, value in observe_value(signal1, signal2):
    if signal is signal1:
        do_something_with(value)
    if signal is signal2:
        do_something_else_with(value)
```

## Use AsyncStatus as a context manager to bound loop execution

If you want a loop to run until some operation completes, you can use [](#AsyncStatus) as a context manager. When the status completes, it will cancel the calling task, causing the loop to exit. This is useful when you want to process signal updates until another operation finishes:

```python
# Process updates while a motor is moving
async with motor.set(target_position):
    async for value in observe_value(detector):
        process_reading(value)
        # Loop automatically exits when motor reaches position
```

If the loop completes before the status, the status task is automatically cancelled:

```python
async with signal1.set(new_value):
    for i in range(3):
        value = await signal.get_value()
        process(value)
        # Loop completes after 3 iterations, cancelling the wait for signal1 to finishe being set
```

If an exception is raised in the loop body, it propagates out normally:

```python
async with signal1.set(new_value):
    async for value in observe_value(signal2):
        if value > threshold:
            raise ValueError("Threshold exceeded")
        # Exception propagates, status is cancelled and no longer waits for signal1 to finish being set
```

## Wait for the value to match some expected value

If you don't need to run code for every signal update, but just want to wait until the signal matches some expected value, you can use [](#wait_for_value):
```python
await wait_for_value(device.acquiring, 1, timeout=1)
```

Or you can pass a function that returns True if the value matches a given condition:
```python
await wait_for_value(device.num_captured, lambda v: v > 45, timeout=1)
```

Which you can use to implement a tolerance check using [](#numpy.isclose):
```python
await wait_for_value(device.temperature, lambda v: numpy.isclose(v, 32.79, atol=0.01), timeout=1)
```

Some control systems (like some EPICS StreamDevice implementations) return immediately when a signal is set, and require you to wait for that signal to match the value to know when it is complete. You can use [](#set_and_wait_for_value) and [](#set_and_wait_for_other_value) to do this:
```python
await set_and_wait_for_value(signal, value)
```
Or if you have to wait for another signal to match a value:
```python
await set_and_wait_for_other_value(signal1, value1, signal2, value2)
```
You can pass `timeout` to specify how long to wait for signal2 to match value2, and `set_timeout` to specify how long to wait 

Some control systems (like EPICS areaDetector) return when an operation is complete, rather than when the operation has started. To support this you can ask not to `wait_for_set_completion`, just wait until the signal reaches the required value:
```python
arm_status = await set_and_wait_for_value(driver.acquiring, 1, wait_for_set_completion=False)
# the detector is now armed, do something else
await arm_status
# the detector is now disarmed
```

This is better illustrated with a diagram:

```{raw} html
:file: ../images/set_and_wait_for_other_value.excalidraw.svg
```

- **If `wait_for_set_completion = True`:**  
    The function returns at **1** (see diagram below), which occurs when the "set operation" is complete.  

- **If `wait_for_set_completion = False`:**  
    The function returns at **2**, which occurs when the `match_signal` reaches the `match_value`.
