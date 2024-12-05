from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from ophyd_async.core import (
    Array1D,
    Device,
    DTypeScalar_co,
    SignalRW,
    YamlSettingsProvider,
    set_mock_value,
)
from ophyd_async.epics.testing import ExampleEnum, ExamplePvaDevice, ExampleTable
from ophyd_async.plan_stubs import (
    apply_settings,
    apply_settings_if_different,
    get_current_settings,
    retrieve_settings,
    store_settings,
)

TEST_DATA = Path(__file__).absolute().parent.parent / "test_data"


def int_array(dtype: type[DTypeScalar_co]) -> Array1D[DTypeScalar_co]:
    iinfo = np.iinfo(dtype)  # type: ignore
    return np.array([iinfo.min, iinfo.max, 0, 1, 2, 3, 4], dtype=dtype)


def float_array(dtype: type[DTypeScalar_co]) -> Array1D[DTypeScalar_co]:
    finfo = np.finfo(dtype)  # type: ignore
    return np.array(
        [
            finfo.min,
            finfo.max,
            finfo.smallest_normal,
            finfo.smallest_subnormal,
            0,
            1.234,
            2.34e5,
            3.45e-6,
        ],
        dtype=dtype,
    )


@pytest.fixture
async def example_device() -> ExamplePvaDevice:
    device = ExamplePvaDevice("prefix", name="example")
    await device.connect(mock=True)
    set_mock_value(device.my_int, 1)
    set_mock_value(device.my_float, 1.234)
    set_mock_value(device.my_str, "test_string")
    set_mock_value(device.enum, ExampleEnum.B)
    set_mock_value(device.enum2, "Bbb")  # type: ignore
    set_mock_value(device.int8a, int_array(np.int8))
    set_mock_value(device.uint8a, int_array(np.uint8))
    set_mock_value(device.int16a, int_array(np.int16))
    set_mock_value(device.uint16a, int_array(np.uint16))
    set_mock_value(device.int32a, int_array(np.int32))
    set_mock_value(device.uint32a, int_array(np.uint32))
    set_mock_value(device.int64a, int_array(np.int64))
    set_mock_value(device.uint64a, int_array(np.uint64))
    set_mock_value(device.float32a, float_array(np.float32))
    set_mock_value(device.float64a, float_array(np.float64))
    set_mock_value(device.stra, ["one", "two", "three"])
    set_mock_value(
        device.table,
        ExampleTable(
            bool=np.array([False, False, True, True], np.bool_),
            int=np.array([1, 8, -9, 32], np.int32),
            float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
            str=["Hello", "World", "Foo", "Bar"],
            enum=[ExampleEnum.A, ExampleEnum.B, ExampleEnum.A, ExampleEnum.C],
        ),
    )
    return device


async def get_current_values(device: Device, wrap=lambda v: v) -> dict[SignalRW, Any]:
    return {
        sig: wrap(await sig.get_value())
        for _, sig in device.children()
        if isinstance(sig, SignalRW)
    }


async def test_get_current_settings(RE, example_device):
    expected_values = await get_current_values(example_device, wrap=pytest.approx)

    def my_plan():
        current_settings = yield from get_current_settings(example_device)
        assert dict(current_settings) == expected_values

    RE(my_plan())


async def test_store_settings(RE, example_device, tmp_path):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_settings(provider, "test_file", example_device)
        with open(tmp_path / "test_file.yaml") as actual_file:
            with open(TEST_DATA / "test_yaml_save.yaml") as expected_file:
                assert yaml.safe_load(actual_file) == yaml.safe_load(expected_file)

    RE(my_plan())


def by_name(d):
    return {sig.name: value for sig, value in d.items()}


async def test_retrieve_and_apply_settings(RE, example_device):
    provider = YamlSettingsProvider(TEST_DATA)
    expected_values = by_name(await get_current_values(example_device))
    # Dump the table so it compares equal
    expected_values["example-table"] = expected_values["example-table"].model_dump()

    # Make a blank device that we should be getting into the same state
    # as example_device
    target_device = ExamplePvaDevice("prefix", name="example")
    await target_device.connect(mock=True)

    def my_plan():
        settings = yield from retrieve_settings(
            provider, "test_yaml_save", target_device
        )
        # assert actual["example-table"] == expected["example-table"]
        assert expected_values["example-table"] == pytest.approx(
            by_name(settings)["example-table"]
        )

    RE(my_plan())
