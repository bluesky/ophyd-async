from pathlib import Path
from unittest.mock import call

import bluesky.plan_stubs as bps
import numpy as np
import pytest
import yaml

from ophyd_async.core import Settings, YamlSettingsProvider
from ophyd_async.plan_stubs import (
    apply_settings,
    apply_settings_if_different,
    get_current_settings,
    retrieve_settings,
    store_settings,
)
from ophyd_async.testing import (
    ExampleTable,
    OneOfEverythingDevice,
    ParentOfEverythingDevice,
    get_mock,
)

TEST_DATA = Path(__file__).absolute().parent.parent / "test_data"


@pytest.fixture
async def parent_device() -> ParentOfEverythingDevice:
    device = ParentOfEverythingDevice("parent")
    await device.connect(mock=True)
    return device


@pytest.fixture
async def every_parent_device() -> OneOfEverythingDevice:
    device = OneOfEverythingDevice("parent")
    await device.connect(mock=True)
    return device


async def test_get_current_settings(RE, parent_device: ParentOfEverythingDevice):
    expected_values = await parent_device.get_signal_values()

    def my_plan():
        current_settings = yield from get_current_settings(parent_device)
        assert dict(current_settings) == expected_values

    RE(my_plan())


async def test_get_current_config_settings(
    RE, every_parent_device: OneOfEverythingDevice
):
    expected_values = await every_parent_device.get_signal_values()

    def my_plan():
        current_settings = yield from get_current_settings(
            every_parent_device, only_config=True
        )
        current_settings = dict(current_settings)
        for key, value in current_settings.items():
            if isinstance(value, np.ndarray):
                assert np.array_equal(value, expected_values[key])
            else:
                assert value == expected_values[key]

    RE(my_plan())


async def test_store_settings(RE, parent_device: ParentOfEverythingDevice, tmp_path):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_settings(provider, "test_file", parent_device)
        with open(tmp_path / "test_file.yaml") as actual_file:
            with open(TEST_DATA / "test_yaml_save.yaml") as expected_file:
                assert yaml.safe_load(actual_file) == yaml.safe_load(expected_file)

    RE(my_plan())


async def test_store_config_settings(
    RE, every_parent_device: OneOfEverythingDevice, tmp_path
):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_settings(
            provider, "test_file", every_parent_device, only_config=True
        )
        with open(tmp_path / "test_file.yaml") as actual_file:
            actual_data = yaml.safe_load(actual_file)
        with open(TEST_DATA / "test_yaml_config_save.yaml") as expected_file:
            expected_data = yaml.safe_load(expected_file)
        assert actual_data == expected_data

    RE(my_plan())


async def test_retrieve_and_apply_settings(RE, parent_device: ParentOfEverythingDevice):
    provider = YamlSettingsProvider(TEST_DATA)
    expected_values = await parent_device.get_signal_values()
    serialized_values = {}
    # Override the table to be the serialized version so it compares equal
    for sig, value in expected_values.items():
        if isinstance(value, ExampleTable):
            serialized_values[sig] = {
                k: pytest.approx(v) for k, v in value.model_dump().items()
            }
        else:
            serialized_values[sig] = pytest.approx(value)

    def my_plan():
        m = get_mock(parent_device)
        assert not m.mock_calls
        settings = yield from retrieve_settings(
            provider, "test_yaml_save", parent_device
        )
        assert dict(settings) == serialized_values
        assert not m.mock_calls
        yield from apply_settings(settings)
        assert len(m.mock_calls) == 62
        m.reset_mock()
        assert not m.mock_calls
        yield from apply_settings_if_different(settings, apply_settings)
        assert not m.mock_calls
        yield from bps.abs_set(parent_device.sig_rw, "foo", wait=True)
        assert m.mock_calls == [call.sig_rw.put("foo", wait=True)]
        m.reset_mock()
        yield from apply_settings_if_different(settings, apply_settings)
        assert m.mock_calls == [call.sig_rw.put("Top level SignalRW", wait=True)]

    RE(my_plan())


async def test_retrieve_and_apply_config_settings(
    RE, every_parent_device: OneOfEverythingDevice
):
    provider = YamlSettingsProvider(TEST_DATA)
    expected_values = await every_parent_device.get_signal_values()
    serialized_values = {}
    # Override the table to be the serialized version so it compares equal
    for sig, value in expected_values.items():
        if isinstance(value, ExampleTable):
            serialized_values[sig] = {
                k: pytest.approx(v) for k, v in value.model_dump().items()
            }
        else:
            serialized_values[sig] = pytest.approx(value)

    def my_plan():
        m = get_mock(every_parent_device)
        settings = yield from retrieve_settings(
            provider, "test_yaml_config_save", every_parent_device, only_config=True
        )
        assert dict(settings) == serialized_values
        assert not m.mock_calls
        yield from apply_settings(settings)
        assert len(m.mock_calls) == 20
        m.reset_mock()
        assert not m.mock_calls
        yield from apply_settings_if_different(settings, apply_settings)
        assert not m.mock_calls
        yield from bps.abs_set(every_parent_device.a_str, "foo", wait=True)
        assert m.mock_calls == [call.a_str.put("foo", wait=True)]
        m.reset_mock()
        yield from apply_settings_if_different(settings, apply_settings)
        assert m.mock_calls == [call.a_str.put("test_string", wait=True)]

    RE(my_plan())


async def test_ignored_settings(RE, parent_device: ParentOfEverythingDevice):
    def my_plan():
        m = get_mock(parent_device)
        settings = Settings(
            parent_device, {parent_device.sig_rw: "foo", parent_device._sig_rw: None}
        )
        yield from apply_settings(settings)
        assert m.mock_calls == [call.sig_rw.put("foo", wait=True)]

    RE(my_plan())
