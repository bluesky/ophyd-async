import os

import pytest

from ophyd_async.core import (
    Device,
    DeviceMap,
    DeviceVector,
    NotConnectedError,
    SignalRW,
)
from ophyd_async.epics.testing import (
    IOC,
    EpicsTestPviAgreeingPvSuffixDevice,
    EpicsTestPviDisagreeingDeviceDevice,
    EpicsTestPviLeafDevice,
    EpicsTestPviMapDevice,
    EpicsTestPviMapOverVectorDevice,
    EpicsTestPviNestedDevice,
    EpicsTestPviNestedDeviceMissingChild,
    generate_random_pv_prefix,
    start_ioc,
)

TIMEOUT = 30.0 if os.name == "nt" else 3.0


@pytest.fixture(scope="module")
def nested_ioc_and_prefix():
    # The fixed test IOC catalog serves _pvi_nested_records.db under a
    # nested: sub-prefix of whatever prefix it's started with - see
    # ophyd_async.epics.testing._ioc._testing_ioc_args.
    prefix = generate_random_pv_prefix()
    process = start_ioc(IOC, prefix)
    yield process, f"{prefix}nested:"
    process.stop()
    print(process.output)


@pytest.fixture
async def nested_device(nested_ioc_and_prefix) -> EpicsTestPviNestedDevice:
    _, prefix = nested_ioc_and_prefix
    # Explicit name: constructing outside init_devices() doesn't auto-name
    # from the assigned variable, unlike the mocked with_pvi_connector tests.
    device = EpicsTestPviNestedDevice(prefix, with_pvi=True, name="nested_device")
    await device.connect(timeout=TIMEOUT)
    return device


@pytest.fixture
async def map_device(nested_ioc_and_prefix) -> EpicsTestPviMapDevice:
    _, prefix = nested_ioc_and_prefix
    # The DeviceMap structure is served under its own "mapd:" group (see
    # _pvi_nested_records.db) so it doesn't perturb EpicsTestPviNestedDevice.
    device = EpicsTestPviMapDevice(f"{prefix}mapd:", with_pvi=True, name="map_device")
    await device.connect(timeout=TIMEOUT)
    return device


@pytest.mark.timeout(TIMEOUT)
async def test_structure_naming_and_parenting(nested_device: EpicsTestPviNestedDevice):
    assert isinstance(nested_device.child, EpicsTestPviLeafDevice)
    assert isinstance(nested_device.device_vector, DeviceVector)
    assert set(nested_device.device_vector) == {1, 2}
    assert isinstance(nested_device.device_vector[1], EpicsTestPviLeafDevice)
    assert isinstance(nested_device.device_vector[2], EpicsTestPviLeafDevice)

    assert nested_device.child.parent is nested_device
    assert nested_device.device_vector.parent is nested_device
    assert nested_device.device_vector[1].parent is nested_device.device_vector
    assert nested_device.device_vector[2].parent is nested_device.device_vector

    assert nested_device.device_vector.name == f"{nested_device.name}-device_vector"
    assert (
        nested_device.device_vector[1].name == f"{nested_device.name}-device_vector-1"
    )
    assert (
        nested_device.device_vector[2].name == f"{nested_device.name}-device_vector-2"
    )


@pytest.mark.timeout(TIMEOUT)
async def test_flat_signal_and_command(nested_device: EpicsTestPviNestedDevice):
    assert await nested_device.signal_rw.get_value() == 1
    await nested_device.signal_rw.set(100)
    assert await nested_device.signal_rw.get_value() == 100
    await nested_device.signal_x.trigger()


@pytest.mark.timeout(TIMEOUT)
async def test_plain_sub_device_signal_and_command(
    nested_device: EpicsTestPviNestedDevice,
):
    assert await nested_device.child.signal_rw.get_value() == 2
    await nested_device.child.signal_rw.set(200)
    assert await nested_device.child.signal_rw.get_value() == 200
    await nested_device.child.signal_x.trigger()


@pytest.mark.timeout(TIMEOUT)
async def test_device_vector_children_are_distinct(
    nested_device: EpicsTestPviNestedDevice,
):
    # Prove index 1 and index 2 are backed by genuinely different PVs, not
    # the same one twice.
    assert await nested_device.device_vector[1].signal_rw.get_value() == 10
    assert await nested_device.device_vector[2].signal_rw.get_value() == 20
    await nested_device.device_vector[1].signal_rw.set(11)
    assert await nested_device.device_vector[1].signal_rw.get_value() == 11
    assert await nested_device.device_vector[2].signal_rw.get_value() == 20
    await nested_device.device_vector[1].signal_x.trigger()
    await nested_device.device_vector[2].signal_x.trigger()


@pytest.mark.timeout(TIMEOUT)
async def test_device_vector_of_signals(nested_device: EpicsTestPviNestedDevice):
    assert isinstance(nested_device.signal_vector, DeviceVector)
    assert set(nested_device.signal_vector) == {1, 2}
    assert await nested_device.signal_vector[1].get_value() == 1.5
    assert await nested_device.signal_vector[2].get_value() == 2.5
    await nested_device.signal_vector[1].set(15.5)
    assert await nested_device.signal_vector[1].get_value() == 15.5
    assert await nested_device.signal_vector[2].get_value() == 2.5


@pytest.mark.timeout(TIMEOUT)
async def test_device_vector_of_commands(nested_device: EpicsTestPviNestedDevice):
    assert isinstance(nested_device.command_vector, DeviceVector)
    assert set(nested_device.command_vector) == {1, 2}
    await nested_device.command_vector[1].trigger()
    await nested_device.command_vector[2].trigger()


@pytest.mark.timeout(TIMEOUT)
async def test_optional_signal_absent_from_tree_is_none(
    nested_device: EpicsTestPviNestedDevice,
):
    assert nested_device.optional_signal is None


@pytest.mark.timeout(TIMEOUT)
async def test_required_field_missing_from_pvi_raises(nested_ioc_and_prefix):
    _, prefix = nested_ioc_and_prefix
    device = EpicsTestPviNestedDeviceMissingChild(
        prefix, with_pvi=True, name="missing_child_device"
    )
    with pytest.raises(RuntimeError, match="missing_child"):
        await device.connect(timeout=TIMEOUT)


@pytest.mark.timeout(TIMEOUT)
async def test_undeclared_device_vector_of_devices(
    nested_device: EpicsTestPviNestedDevice,
):
    # extra_devices has a PVI entry but is not an annotation on
    # EpicsTestPviNestedDevice -- PviDeviceConnector should still add it
    # dynamically as a generic DeviceVector[Device], mirroring PandA's real
    # ttlout/extra vectors.
    extra_devices = nested_device.extra_devices  # type: ignore[attr-defined]
    assert isinstance(extra_devices, DeviceVector)
    assert set(extra_devices) == {1, 2}
    assert isinstance(extra_devices[1], Device)
    assert await extra_devices[1].signal_rw.get_value() == 30
    assert await extra_devices[2].signal_rw.get_value() == 40


@pytest.mark.timeout(TIMEOUT)
async def test_device_map_of_signals(map_device: EpicsTestPviMapDevice):
    # A DeviceMap is filled from its node's normal named entries (a, b), keyed
    # by name, each type-checked against the map's SignalRW[float] element type.
    assert isinstance(map_device.signal_map, DeviceMap)
    assert set(map_device.signal_map) == {"a", "b"}
    assert isinstance(map_device.signal_map["a"], SignalRW)
    assert await map_device.signal_map["a"].get_value() == 1.5
    assert await map_device.signal_map["b"].get_value() == 2.5
    await map_device.signal_map["a"].set(15.5)
    assert await map_device.signal_map["a"].get_value() == 15.5
    assert await map_device.signal_map["b"].get_value() == 2.5


@pytest.mark.timeout(TIMEOUT)
async def test_device_map_naming_and_parenting(map_device: EpicsTestPviMapDevice):
    assert map_device.signal_map.name == "map_device-signal_map"
    assert map_device.signal_map["a"].name == "map_device-signal_map-a"
    assert map_device.signal_map.parent is map_device
    assert map_device.signal_map["a"].parent is map_device.signal_map


@pytest.mark.timeout(TIMEOUT)
async def test_device_map_of_devices(map_device: EpicsTestPviMapDevice):
    # A DeviceMap of Devices: each named entry (one, two) is created as the
    # map's EpicsTestPviLeafDevice element type and recursed into.
    assert isinstance(map_device.device_map, DeviceMap)
    assert set(map_device.device_map) == {"one", "two"}
    assert isinstance(map_device.device_map["one"], EpicsTestPviLeafDevice)
    assert await map_device.device_map["one"].signal_rw.get_value() == 11
    assert await map_device.device_map["two"].signal_rw.get_value() == 22
    await map_device.device_map["one"].signal_x.trigger()


@pytest.mark.timeout(TIMEOUT)
async def test_device_map_over_vector_children_raises(nested_ioc_and_prefix):
    # device_vector is served as integer-keyed "__N" entries, which a DeviceMap
    # cannot hold: connecting must say so rather than hand back a map that has
    # silently dropped them.
    _, prefix = nested_ioc_and_prefix
    device = EpicsTestPviMapOverVectorDevice(
        prefix, with_pvi=True, name="map_over_vector"
    )
    # device_vector is filled while connecting as a child, so its TypeError
    # arrives aggregated into the parent's NotConnectedError.
    with pytest.raises(NotConnectedError, match="only a DeviceVector can hold"):
        await device.connect(timeout=TIMEOUT)


@pytest.mark.timeout(TIMEOUT)
async def test_pv_suffix_agreeing_with_pvi_connects(nested_ioc_and_prefix):
    # A PvSuffix that names the same PV PVI serves is redundant, not wrong, so
    # it connects and works normally -- the counterpart to the two tests below.
    _, prefix = nested_ioc_and_prefix
    device = EpicsTestPviAgreeingPvSuffixDevice(prefix, with_pvi=True, name="agreeing")
    await device.connect(timeout=TIMEOUT)
    # Round-trip rather than assert the db's initial values: the IOC is shared
    # across this module and other tests write to these same records.
    await device.signal_rw.set(101)
    assert await device.signal_rw.get_value() == 101
    await device.child.signal_rw.set(202)
    assert await device.child.signal_rw.get_value() == 202


@pytest.mark.timeout(TIMEOUT)
async def test_sub_device_pv_suffix_disagreeing_with_pvi_raises(nested_ioc_and_prefix):
    # If a sub-device is addressed both by a PvSuffix annotation and by PVI, and
    # the two name different PVI PVs, then one of them is wrong -- say so rather
    # than silently letting PVI win. The Signal counterpart of this lives in
    # test_epics_signal_mechanisms.py.
    _, prefix = nested_ioc_and_prefix
    device = EpicsTestPviDisagreeingDeviceDevice(
        prefix, with_pvi=True, name="disagreeing_device"
    )
    with pytest.raises(TypeError, match="child is addressed at .*not_child:PVI"):
        await device.connect(timeout=TIMEOUT)
