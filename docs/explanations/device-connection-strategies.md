# Device connection strategies

There are various ways you can connect an ophyd-async Device, depending on whether you are running under a RunEngine or not. This article details each of those modes and why you might want to connect in that mode

## Connections without a RunEngine

It's unlikely that ophyd-async Devices will be used without a RunEngine in production, so connections without a RunEngine should be confined to tests. Inside an async test or fixture you will see code that calls [](#Device.connect):
```python
@pytest.fixture
async def my_device():
    device = MyDevice(name="device")
    await device.connect(mock=True)
    return device
```
or equivalently uses [](#init_devices) as an async context manager:
```python
@pytest.fixture
async def my_device():
    async with init_devices():
        device = MyDevice()
    return device
```
The second form will be used when there are multiple devices to create as the connect is done in parallel. Both of these will run tasks in the current running event loop.

## Connections with a RunEngine

In tests and in production, ophyd-async Devices will be connected in the RunEngine event-loop. This runs in a background thread, so the fixture or test will be synchronous.

Assuming you have [created an RE fixture](#run-engine-fixture), then you can still use [](#init_devices), but as a sync context manager:
```python
@pytest.fixture
def my_device(RE):
    with init_devices():
        device = MyDevice()
    return device
```
This will use the RunEngine event loop in the background to connect the Devices, relying on the fact the RunEngine is a singleton to find it: if you don't create a RunEngine or use the RE fixture this will fail.

Alternatively you can use the [](#ensure_connected) plan to connect the Device:
```python
@pytest.fixture
def my_device(RE):
    device = MyDevice(name="device")
    RE(ensure_connected(device))
    return device
```

Both are equivalent, but you are more likely to use the latter directly in a test case rather than in a fixture.
