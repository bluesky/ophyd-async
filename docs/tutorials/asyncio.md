(asyncio-primer)=
# A crash course on asyncio

Ophyd-async uses Python's [asyncio](inv:python#asyncio) library to communicate
with many pieces of hardware without blocking while any one of them responds.
This page gives you enough asyncio vocabulary to follow the ophyd-async
tutorials. It assumes that you can already write and call ordinary Python
functions.

By the end, you will be able to:

- recognize the async syntax used by ophyd-async;
- decide whether operations should happen in sequence or concurrently; and
- enter async code correctly from a script, IPython, a test, or a Bluesky plan.

## Why ophyd-async uses asyncio

Hardware control contains a lot of waiting: a network request is in flight, a
motor is moving, or a detector is acquiring. Threads can overlap those waits,
but coordinating many threads requires locks and other synchronization. Asyncio
instead makes the places where code may wait explicit. While one operation is
waiting, an **event loop** can let another operation make progress.

Ophyd-async normally gets this concurrency from one event-loop thread, so it
does not need one operating-system thread per device operation. This also makes
interruption and cleanup more predictable. For a direct comparison with threads,
see [](../explanations/design-goals.md).

Asyncio is best suited to this kind of input/output (I/O) concurrency. It does
not make long CPU-bound calculations run in parallel. A blocking function also
blocks the event-loop thread, so use async library calls inside async code.

## Define and await a coroutine

An `async def` statement defines a **coroutine function**. Calling it creates a
coroutine object, which represents work that can be run later. It does not run
the function immediately.

```python
import asyncio


async def read_sensor(name: str, delay: float) -> str:
    await asyncio.sleep(delay)
    return f"{name} ready"


async def main() -> None:
    result = await read_sensor("detector", 0.1)
    print(result)


asyncio.run(main())
```

The `await` expression waits for an **awaitable** such as a coroutine, an
`asyncio.Task`, or many ophyd-async status objects. If that operation needs to
wait, the current coroutine is suspended and the event loop can run other work.
When the operation finishes, `await` produces its result or raises its exception.

Calling `read_sensor(...)` without awaiting or scheduling the returned coroutine
would not run it. Python will normally warn that the coroutine was never awaited.
Except for environments that support top-level `await`, use `await` inside an
`async def` function.

## Call synchronous hardware APIs

Some third-party hardware libraries provide only blocking, synchronous methods.
Calling one directly from a coroutine stops every task on the event-loop thread
until it returns. [](#asyncio.to_thread) lets the function run in a separate
thread while the event loop continues:

```python
reading = await asyncio.to_thread(blocking_detector.read)
```

Pass the function itself to `to_thread()`, followed by any positional or keyword
arguments, rather than calling the function first:

```python
await asyncio.to_thread(blocking_motor.move, position, timeout=5)
```

Prefer an async API when the library provides one. Otherwise, use `to_thread()`
for blocking I/O after checking that the library supports calls from a worker
thread. It is not normally a way to parallelize CPU-bound Python code.

## Choose sequence or concurrency

Two `await` expressions in a row are sequential. The second operation starts
after the first has finished:

```python
temperature = await temperature_signal.get_value()
pressure = await pressure_signal.get_value()
```

When operations are independent, [](#asyncio.gather) can run them concurrently:

```python
temperature, pressure = await asyncio.gather(
    temperature_signal.get_value(),
    pressure_signal.get_value(),
)
```

On success, `gather()` returns results in the same order as its arguments, even
if the operations finish in a different order. An exception is raised to the
code awaiting `gather()`.

Use sequential awaits when one operation depends on the previous result. Use
`gather()` only when the operations are independent and the hardware supports
them happening at the same time. Concurrency changes ordering; it is not merely
a performance switch.

## Recognize the other async keywords

Async code has two more forms that allow waiting at points where ordinary Python
cannot:

- `async with` enters and exits an **asynchronous context manager**. Either step
  may await setup or cleanup. For example, `async with` lets [](#init_devices)
  connect devices when it is called from an async function:

  ```python
  async with init_devices():
      detector = MyDetector("DEVICE-PREFIX")
  ```

- `async for` consumes an **asynchronous iterator**. Each iteration may await the
  next value. Ophyd-async uses this pattern to observe signal updates:

  ```python
  async for value in observe_value(signal):
      print(value)
  ```

The ordinary `with` and `for` forms are still appropriate when entering,
exiting, or advancing cannot require an async wait.

## Enter async code in the right place

How you start async work depends on the environment:

- **Script:** define one outer `main()` coroutine and call
  `asyncio.run(main())`. This creates an event loop, runs `main()`, and closes the
  loop. Do not call `asyncio.run()` from code that is already inside a running
  event loop.
- **IPython:** use top-level `await`, such as
  `await detector.read()`. When an IPython session also has a Bluesky RunEngine,
  `autoawait_in_bluesky_event_loop()` makes top-level awaits use the RunEngine's
  event loop. The [](./using-devices.md) tutorial configures this for you.
- **Pytest:** write an `async def test_...` and await device methods inside it.
  The [](./writing-tests-for-devices.md) tutorial shows the required
  `pytest-asyncio` configuration.
- **Bluesky plan:** plans are generator functions driven by the RunEngine. Use
  `yield from` with Bluesky plan stubs rather than directly awaiting device
  methods. The RunEngine coordinates the plan with ophyd-async's async device
  operations.

## Avoid common mistakes

- If you see `coroutine was never awaited`, find the coroutine call and either
  await it or deliberately schedule and later await it.
- Do not use `time.sleep()` in async code; it blocks every task on the event-loop
  thread. Use `await asyncio.sleep()` when you need an async delay.
- Do not add `asyncio.run()` around a call in IPython or other code that already
  has a running event loop. Use `await` there.
- Do not make dependent or mutually exclusive hardware operations concurrent.
  Preserve their required order with separate `await` expressions.

You now have the asyncio concepts needed for [](./using-devices.md). For more
device-specific patterns, see [](../how-to/interact-with-signals.md). The
[Python asyncio documentation](inv:python#asyncio) covers the full standard
library.
