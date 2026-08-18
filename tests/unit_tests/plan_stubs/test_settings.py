from pathlib import Path
from unittest.mock import call

import bluesky.plan_stubs as bps
import numpy as np
import pytest
import yaml

from ophyd_async.core import (
    Device,
    Settings,
    StandardReadable,
    YamlSettingsProvider,
    apply_readable_formats,
    get_mock,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format
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
    device.energy = soft_signal_rw(float, 7.0)
    device.temperature = soft_signal_rw(float, 20.0)
    device.set_name("mono")
    device.set_readable_format(device.energy, Format.CONFIG_SIGNAL)
    device.set_readable_format(device.temperature, Format.CONFIG_SIGNAL)
    return device


async def test_store_settings_writes_formats_under_reserved_key(
    RE, technique_device, tmp_path
):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_settings(provider, "fixed_energy", technique_device)
        with open(tmp_path / "fixed_energy.yaml") as f:
            stored = yaml.safe_load(f)
        # Values stay flat, formats live under a key that cannot be a path
        assert stored == {
            "energy": 7.0,
            "temperature": 20.0,
            "<READABLE_FORMATS>": {
                "<ROOT_DEVICE>": {
                    "energy": "CONFIG_SIGNAL",
                    "temperature": "CONFIG_SIGNAL",
                }
            },
        }

    RE(my_plan())


async def test_reserved_keys_need_no_quoting_in_yaml(RE, technique_device, tmp_path):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_settings(provider, "fixed_energy", technique_device)
        text = (tmp_path / "fixed_energy.yaml").read_text()
        assert "<READABLE_FORMATS>:" in text
        assert "<ROOT_DEVICE>:" in text
        # An empty string root would make yaml fall back to "? ''" explicit keys
        assert "?" not in text

    RE(my_plan())


async def test_settings_round_trip_switches_technique(RE, technique_device, tmp_path):
    provider = YamlSettingsProvider(tmp_path)
    energy, temperature = technique_device.energy, technique_device.temperature

    def my_plan():
        yield from store_settings(provider, "fixed_energy", technique_device)

        # Switch to a technique that scans energy and drops temperature entirely
        technique_device.set_readable_format(energy, Format.HINTED_SIGNAL)
        technique_device.set_readable_format(temperature, None)
        yield from bps.abs_set(energy, 9.0, wait=True)
        yield from store_settings(provider, "scan_energy", technique_device)

        # Going back restores both the value and the formats in one apply
        fixed = yield from retrieve_settings(provider, "fixed_energy", technique_device)
        yield from apply_settings(fixed)
        assert technique_device.get_readable_format(energy) is Format.CONFIG_SIGNAL
        assert technique_device.get_readable_format(temperature) is Format.CONFIG_SIGNAL
        assert (yield from bps.rd(energy)) == 7.0

        # And forward again drops temperature rather than merging the two
        scanning = yield from retrieve_settings(
            provider, "scan_energy", technique_device
        )
        yield from apply_settings(scanning)
        assert technique_device.get_readable_format(energy) is Format.HINTED_SIGNAL
        assert technique_device.get_readable_format(temperature) is None
        assert (yield from bps.rd(energy)) == 9.0

    RE(my_plan())


async def test_settings_file_without_formats_leaves_them_alone(
    RE, technique_device, tmp_path
):
    """A file stored before formats existed must not clear them."""
    provider = YamlSettingsProvider(tmp_path)
    energy = technique_device.energy
    (tmp_path / "old_style.yaml").write_text("energy: 3.0\ntemperature: 4.0\n")

    def my_plan():
        settings = yield from retrieve_settings(provider, "old_style", technique_device)
        assert settings.readable_formats == {}
        yield from apply_settings(settings)
        # Values applied, formats untouched
        assert (yield from bps.rd(energy)) == 3.0
        assert technique_device.get_readable_format(energy) is Format.CONFIG_SIGNAL

    RE(my_plan())


async def test_formats_only_file_applies_without_touching_values(
    RE, technique_device, tmp_path
):
    """A hand written formats only profile changes no hardware."""
    provider = YamlSettingsProvider(tmp_path)
    energy = technique_device.energy
    (tmp_path / "hinted.yaml").write_text(
        "<READABLE_FORMATS>:\n  <ROOT_DEVICE>:\n    energy: HINTED_SIGNAL\n"
    )

    def my_plan():
        settings = yield from retrieve_settings(provider, "hinted", technique_device)
        assert dict(settings) == {}
        yield from apply_settings(settings)
        assert technique_device.get_readable_format(energy) is Format.HINTED_SIGNAL
        # temperature was not mentioned, so the root's registry was replaced
        assert (
            technique_device.get_readable_format(technique_device.temperature) is None
        )
        assert (yield from bps.rd(energy)) == 7.0

    RE(my_plan())


async def test_store_settings_walks_nested_devices(RE, tmp_path):
    provider = YamlSettingsProvider(tmp_path)
    inner = StandardReadable(name="inner")
    inner.sig = soft_signal_rw(float, 1.0)
    outer = StandardReadable(name="outer")
    outer.inner = inner
    outer.top = soft_signal_rw(float, 2.0)
    outer.set_name("outer")
    inner.set_readable_format(inner.sig, Format.HINTED_SIGNAL)
    outer.set_readable_format(outer.top, Format.CONFIG_SIGNAL)
    outer.set_readable_format(inner, Format.CHILD)

    def my_plan():
        yield from store_settings(provider, "nested", outer)
        with open(tmp_path / "nested.yaml") as f:
            assert yaml.safe_load(f) == {
                "top": 2.0,
                "inner.sig": 1.0,
                "<READABLE_FORMATS>": {
                    "<ROOT_DEVICE>": {"top": "CONFIG_SIGNAL", "inner": "CHILD"},
                    "inner": {"inner.sig": "HINTED_SIGNAL"},
                },
            }

    RE(my_plan())


def test_apply_readable_formats_rejects_unknown_path(technique_device):
    with pytest.raises(KeyError, match="No Device at 'nope'"):
        apply_readable_formats(technique_device, {"nope": {}})


def test_apply_readable_formats_rejects_non_readable(technique_device):
    with pytest.raises(TypeError, match="is not a StandardReadable"):
        apply_readable_formats(technique_device, {"energy": {}})


def test_settings_partition_carries_formats_to_both_halves(technique_device):
    # apply_panda_settings applies only the halves, never the original, so
    # formats must survive on whichever half is applied
    settings = Settings(
        technique_device,
        {technique_device.energy: 1.0, technique_device.temperature: 2.0},
        {"<ROOT_DEVICE>": {"energy": Format.CONFIG_SIGNAL}},
    )
    a, b = settings.partition(lambda sig: "energy" in sig.name)
    assert a.readable_formats == settings.readable_formats
    assert b.readable_formats == settings.readable_formats


async def test_store_settings_records_a_readable_that_registers_nothing(RE, tmp_path):
    """An empty owner entry means "clear this owner", so it must be stored.

    This is the shape of TangoTestDevice, and it is why applying a profile that
    registers nothing drops what the previous profile registered rather than
    silently leaving it in place.
    """
    provider = YamlSettingsProvider(tmp_path)
    device = StandardReadable(name="dev")
    device.sig = soft_signal_rw(float, 1.0)
    device.set_name("dev")

    def my_plan():
        yield from store_settings(provider, "empty", device)
        with open(tmp_path / "empty.yaml") as f:
            assert yaml.safe_load(f) == {
                "sig": 1.0,
                "<READABLE_FORMATS>": {"<ROOT_DEVICE>": {}},
            }

        # Register something, then apply the stored file back
        device.set_readable_format(device.sig, Format.CONFIG_SIGNAL)
        settings = yield from retrieve_settings(provider, "empty", device)
        yield from apply_settings(settings)
        assert device.get_readable_format(device.sig) is None

    RE(my_plan())


async def test_store_settings_omits_the_key_for_a_device_with_no_readables(
    RE, tmp_path
):
    """A Device with no StandardReadable in its tree has nothing to clear.

    This is the shape of EpicsTestCaDevice, and is why the EPICS golden files
    needed no regeneration.
    """
    provider = YamlSettingsProvider(tmp_path)

    class Plain(Device):
        pass

    device = Plain(name="dev")
    device.sig = soft_signal_rw(float, 1.0)
    device.set_name("dev")

    def my_plan():
        yield from store_settings(provider, "plain", device)
        with open(tmp_path / "plain.yaml") as f:
            assert yaml.safe_load(f) == {"sig": 1.0}

    RE(my_plan())
