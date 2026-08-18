from pathlib import Path
from unittest.mock import call

import bluesky.plan_stubs as bps
import numpy as np
import pytest
import yaml

from ophyd_async.core import (
    Settings,
    StandardReadable,
    YamlSettingsProvider,
    apply_readable_formats,
    get_mock,
    soft_signal_r_and_setter,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.plan_stubs import (
    apply_settings,
    apply_settings_if_different,
    get_current_settings,
    retrieve_readable_formats,
    retrieve_settings,
    store_readable_formats,
    store_settings,
)
from ophyd_async.testing import (
    ExampleTable,
    OneOfEverythingDevice,
    ParentOfEverythingDevice,
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
        assert len(m.mock_calls) == 68
        m.reset_mock()
        assert not m.mock_calls
        yield from apply_settings_if_different(settings, apply_settings)
        assert not m.mock_calls
        yield from bps.abs_set(parent_device.sig_rw, "foo", wait=True)
        assert m.mock_calls == [call.sig_rw.put("foo")]
        m.reset_mock()
        yield from apply_settings_if_different(settings, apply_settings)
        assert m.mock_calls == [call.sig_rw.put("Top level SignalRW")]

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
        assert len(m.mock_calls) == 22
        m.reset_mock()
        assert not m.mock_calls
        yield from apply_settings_if_different(settings, apply_settings)
        assert not m.mock_calls
        yield from bps.abs_set(every_parent_device.a_str, "foo", wait=True)
        assert m.mock_calls == [call.a_str.put("foo")]
        m.reset_mock()
        yield from apply_settings_if_different(settings, apply_settings)
        assert m.mock_calls == [call.a_str.put("test_string")]

    RE(my_plan())


async def test_ignored_settings(RE, parent_device: ParentOfEverythingDevice):
    def my_plan():
        m = get_mock(parent_device)
        settings = Settings(
            parent_device, {parent_device.sig_rw: "foo", parent_device._sig_rw: None}
        )
        yield from apply_settings(settings)
        assert m.mock_calls == [call.sig_rw.put("foo")]

    RE(my_plan())


@pytest.fixture
def technique_device() -> StandardReadable:
    """A Device whose energy signal is config for one technique, hinted for another."""
    device = StandardReadable(name="mono")
    device.energy, _ = soft_signal_r_and_setter(float, 7.0)
    device.temperature, _ = soft_signal_r_and_setter(float, 20.0)
    device.set_name("mono")
    device.set_readable_format(device.energy, Format.CONFIG_SIGNAL)
    device.set_readable_format(device.temperature, Format.CONFIG_SIGNAL)
    return device


async def test_store_and_retrieve_readable_formats(RE, technique_device, tmp_path):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_readable_formats(provider, "fixed_energy", technique_device)
        with open(tmp_path / "fixed_energy.yaml") as f:
            # Stored as plain strings against dotted paths, so it stays editable
            assert yaml.safe_load(f) == {
                "": {"energy": "CONFIG_SIGNAL", "temperature": "CONFIG_SIGNAL"}
            }

        retrieved = yield from retrieve_readable_formats(
            provider, "fixed_energy", technique_device
        )
        assert retrieved == {
            "": {
                "energy": Format.CONFIG_SIGNAL,
                "temperature": Format.CONFIG_SIGNAL,
            }
        }

    RE(my_plan())


async def test_readable_formats_round_trip_switches_technique(
    RE, technique_device, tmp_path
):
    provider = YamlSettingsProvider(tmp_path)
    energy, temperature = technique_device.energy, technique_device.temperature

    def my_plan():
        yield from store_readable_formats(provider, "fixed_energy", technique_device)

        # Switch to a technique that scans energy and drops temperature entirely
        technique_device.set_readable_format(energy, Format.HINTED_SIGNAL)
        technique_device.set_readable_format(temperature, None)
        yield from store_readable_formats(provider, "scan_energy", technique_device)

        # Going back restores both, including the one that was dropped
        fixed = yield from retrieve_readable_formats(
            provider, "fixed_energy", technique_device
        )
        apply_readable_formats(technique_device, fixed)
        assert technique_device.get_readable_format(energy) is Format.CONFIG_SIGNAL
        assert technique_device.get_readable_format(temperature) is Format.CONFIG_SIGNAL

        # And forward again drops temperature rather than merging the two
        scanning = yield from retrieve_readable_formats(
            provider, "scan_energy", technique_device
        )
        apply_readable_formats(technique_device, scanning)
        assert technique_device.get_readable_format(energy) is Format.HINTED_SIGNAL
        assert technique_device.get_readable_format(temperature) is None

    RE(my_plan())


async def test_store_readable_formats_walks_nested_devices(RE, tmp_path):
    provider = YamlSettingsProvider(tmp_path)
    inner = StandardReadable(name="inner")
    inner.sig, _ = soft_signal_r_and_setter(float, 1.0)
    outer = StandardReadable(name="outer")
    outer.inner = inner
    outer.top, _ = soft_signal_r_and_setter(float, 2.0)
    outer.set_name("outer")
    inner.set_readable_format(inner.sig, Format.HINTED_SIGNAL)
    outer.set_readable_format(outer.top, Format.CONFIG_SIGNAL)
    outer.set_readable_format(inner, Format.CHILD)

    def my_plan():
        yield from store_readable_formats(provider, "nested", outer)
        with open(tmp_path / "nested.yaml") as f:
            assert yaml.safe_load(f) == {
                "": {"top": "CONFIG_SIGNAL", "inner": "CHILD"},
                "inner": {"inner.sig": "HINTED_SIGNAL"},
            }

    RE(my_plan())


def test_apply_readable_formats_rejects_unknown_path(technique_device):
    with pytest.raises(KeyError, match="No Device at 'nope'"):
        apply_readable_formats(technique_device, {"nope": {}})


def test_apply_readable_formats_rejects_non_readable(technique_device):
    with pytest.raises(TypeError, match="is not a StandardReadable"):
        apply_readable_formats(technique_device, {"energy": {}})
