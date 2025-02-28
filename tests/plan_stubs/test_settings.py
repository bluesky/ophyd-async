from pathlib import Path
from unittest.mock import call

import bluesky.plan_stubs as bps
import pytest
import yaml

from ophyd_async.core import Settings, YamlSettingsProvider
from ophyd_async.plan_stubs import (
    apply_settings,
    apply_settings_if_different,
    get_current_settings,
    retrieve_settings,
    store_settings,
    store_config_settings,
)
from ophyd_async.testing import (
    ExampleTable,
    ParentOfEverythingDevice,
    get_mock,
    OneOfEverythingDevice
)

TEST_DATA = Path(__file__).absolute().parent.parent / "test_data"


@pytest.fixture
async def parent_device() -> ParentOfEverythingDevice:
    device = ParentOfEverythingDevice("parent")
    await device.connect(mock=True)
    return device


async def test_get_current_settings(RE, parent_device: ParentOfEverythingDevice):
    expected_values = await parent_device.get_signal_values()

    def my_plan():
        current_settings = yield from get_current_settings(parent_device)
        assert dict(current_settings) == expected_values

    RE(my_plan())


async def test_store_settings(RE, parent_device: ParentOfEverythingDevice, tmp_path):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_settings(provider, "test_file", parent_device)
        with open(tmp_path / "test_file.yaml") as actual_file:
            with open(TEST_DATA / "test_yaml_save.yaml") as expected_file:
                assert yaml.safe_load(actual_file) == yaml.safe_load(expected_file)

    RE(my_plan())

async def test_store_config_settings(RE, parent_device: OneOfEverythingDevice, tmp_path):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_config_settings(provider, "test_file", parent_device)
        with open(tmp_path / "test_file.yaml") as actual_file:
            actual_data = yaml.safe_load(actual_file)
        with open(TEST_DATA / "test_yaml_save.yaml") as expected_file:
            expected_data = yaml.safe_load(expected_file)
        # Remove the keys that shouldn't be expected
        expected_data.pop('_sig_rw', None)
        expected_data.pop('sig_rw', None)
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
        assert len(m.mock_calls) == 59
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


async def test_ignored_settings(RE, parent_device: ParentOfEverythingDevice):
    def my_plan():
        m = get_mock(parent_device)
        settings = Settings(
            parent_device, {parent_device.sig_rw: "foo", parent_device._sig_rw: None}
        )
        yield from apply_settings(settings)
        assert m.mock_calls == [call.sig_rw.put("foo", wait=True)]

    RE(my_plan())
