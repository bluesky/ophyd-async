from pathlib import Path
from unittest.mock import call

import bluesky.plan_stubs as bps
import numpy as np
import pytest
import yaml

from ophyd_async.core import (
    Device,
    DeviceSnapshot,
    Settings,
    StandardReadable,
    YamlSettingsProvider,
    get_mock,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.plan_stubs import (
    apply_readable_formats,
    apply_settings,
    apply_settings_if_different,
    get_current_settings,
    retrieve_settings,
    retrieve_snapshot,
    store_settings,
    store_snapshot,
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


async def test_store_snapshot(RE, parent_device: ParentOfEverythingDevice, tmp_path):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_snapshot(provider, "test_file", parent_device)
        with open(tmp_path / "test_file.yaml") as actual_file:
            with open(TEST_DATA / "test_yaml_save.yaml") as expected_file:
                assert yaml.safe_load(actual_file) == yaml.safe_load(expected_file)

    RE(my_plan())


async def test_store_config_snapshot(
    RE, every_parent_device: OneOfEverythingDevice, tmp_path
):
    provider = YamlSettingsProvider(tmp_path)

    def my_plan():
        yield from store_snapshot(
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
        snapshot = yield from retrieve_snapshot(
            provider, "test_yaml_save", parent_device
        )
        settings = snapshot.settings
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
        snapshot = yield from retrieve_snapshot(
            provider, "test_yaml_config_save", every_parent_device
        )
        settings = snapshot.settings
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


class _Mirror(StandardReadable):
    def __init__(self, name=""):
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.pitch = soft_signal_rw(float, 1.0)
        super().__init__(name=name)


class _Beamline(StandardReadable):
    def __init__(self, name=""):
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.energy = soft_signal_rw(float, 7.0)
            self.temperature = soft_signal_rw(float, 20.0)
        with self.add_children_as_readables():
            self.mirror = _Mirror()
        super().__init__(name=name)


@pytest.fixture
def beamline() -> _Beamline:
    return _Beamline(name="beamline")


def _formats(device: _Beamline):
    return (
        list(device.get_readable_formats()),
        list(device.mirror.get_readable_formats()),
    )


async def test_snapshot_round_trip_through_yaml(RE, beamline: _Beamline, tmp_path):
    provider = YamlSettingsProvider(tmp_path)
    constructed = _formats(beamline)

    def my_plan():
        # Switch to a technique that scans energy, drops temperature and hints
        # the nested mirror's pitch
        beamline.set_readable_format(beamline.energy, Format.HINTED_SIGNAL)
        beamline.set_readable_format(beamline.temperature, None)
        beamline.mirror.set_readable_format(beamline.mirror.pitch, Format.HINTED_SIGNAL)
        scanning = _formats(beamline)
        yield from bps.abs_set(beamline.energy, 9.0, wait=True)
        yield from store_snapshot(provider, "scan", beamline)

        assert (tmp_path / "scan.yaml").read_text() == (
            "<READABLE_FORMATS>:\n"
            "  energy: HINTED_SIGNAL\n"
            "  mirror:pitch: HINTED_SIGNAL\n"
            "  temperature: null\n"
            "energy: 9.0\n"
            "mirror.pitch: 1.0\n"
            "temperature: 20.0\n"
        )

        # Back to how it was constructed
        yield from bps.abs_set(beamline.energy, 7.0, wait=True)
        yield from apply_readable_formats(beamline, {})
        assert _formats(beamline) == constructed

        # One apply restores the values and the formats
        snapshot = yield from retrieve_snapshot(provider, "scan", beamline)
        yield from apply_settings(snapshot.settings)
        yield from apply_readable_formats(snapshot.device, snapshot.readable_formats)
        assert (yield from bps.rd(beamline.energy)) == 9.0
        assert _formats(beamline) == scanning

    RE(my_plan())


@pytest.mark.parametrize(
    "text, message",
    [
        ("energy: 3.0\nenergyy: 4.0\n", r"Unknown signal names \['energyy'\]"),
        (
            "energy: 3.0\n<READABLE_FORMATS>:\n  nope: CHILD\n",
            r"Unknown readable format paths \[\('', 'nope'\)\]",
        ),
        (
            "energy: 3.0\n<READABLE_FORMATS>:\n  mirror:nope: CHILD\n",
            r"Unknown readable format paths \[\('mirror', 'nope'\)\]",
        ),
        (
            "energy: 3.0\n<READABLE_FORMATS>:\n  nope:energy: CHILD\n",
            r"Unknown readable format paths \[\('nope', 'energy'\)\]",
        ),
        # The owner is a SignalRW, not a StandardReadable
        (
            "energy: 3.0\n<READABLE_FORMATS>:\n  energy:x: CHILD\n",
            r"owners that are not a StandardReadable \['energy'\]",
        ),
        # Every bad path is reported, not just the first
        (
            "energy: 3.0\n<READABLE_FORMATS>:\n  gone: null\n  nope:x: CHILD\n"
            "  energy:x: CHILD\n",
            r"Unknown readable format paths \[\('', 'gone'\), \('nope', 'x'\)\]; "
            r".*\['energy'\]",
        ),
    ],
)
async def test_retrieve_snapshot_with_a_stale_path_raises_before_anything_is_written(
    RE, beamline: _Beamline, tmp_path, text, message
):
    provider = YamlSettingsProvider(tmp_path)
    (tmp_path / "stale.yaml").write_text(text)
    beamline.set_readable_format(beamline.energy, Format.HINTED_SIGNAL)
    before = _formats(beamline)

    def my_plan():
        with pytest.raises(NameError, match=message):
            yield from retrieve_snapshot(provider, "stale", beamline)

    RE(my_plan())
    # Neither the value nor the formats were touched
    assert await beamline.energy.get_value() == 7.0
    assert _formats(beamline) == before


@pytest.mark.parametrize(
    "formats, expected",
    [
        (None, lambda b: None),
        ({}, lambda b: {}),
        (
            {
                ("", "energy"): Format.HINTED_SIGNAL,
                ("mirror", "pitch"): None,
            },
            lambda b: {
                b: {b.energy: Format.HINTED_SIGNAL},
                b.mirror: {b.mirror.pitch: None},
            },
        ),
    ],
)
def test_snapshot_readable_formats_resolve_against_the_device(
    beamline: _Beamline, formats, expected
):
    assert DeviceSnapshot(beamline, {}, formats).readable_formats == expected(beamline)


async def test_retrieve_snapshot_reads_a_null_section_as_reset(
    RE, beamline: _Beamline, tmp_path
):
    provider = YamlSettingsProvider(tmp_path)
    (tmp_path / "null.yaml").write_text("<READABLE_FORMATS>:\nenergy: 3.0\n")

    def my_plan():
        snapshot = yield from retrieve_snapshot(provider, "null", beamline)
        assert snapshot.readable_formats == {}
        assert snapshot.settings == {beamline.energy: 3.0}

    RE(my_plan())


async def test_retrieve_snapshot_with_a_bad_format_raises_before_anything_is_written(
    RE, beamline: _Beamline, tmp_path
):
    provider = YamlSettingsProvider(tmp_path)
    (tmp_path / "bad.yaml").write_text(
        "energy: 3.0\n<READABLE_FORMATS>:\n  energy: NOT_A_FORMAT\n"
    )
    before = _formats(beamline)

    def my_plan():
        with pytest.raises(ValueError, match="NOT_A_FORMAT"):
            yield from retrieve_snapshot(provider, "bad", beamline)

    RE(my_plan())
    assert await beamline.energy.get_value() == 7.0
    assert _formats(beamline) == before


def test_snapshot_views_are_copies(beamline: _Beamline):
    values = {"energy": 3.0}
    formats = {("", "energy"): Format.HINTED_SIGNAL}
    snapshot = DeviceSnapshot(beamline, values, formats)
    snapshot.settings[beamline.energy] = 99.0
    snapshot.readable_formats[beamline][beamline.energy] = Format.CHILD  # type: ignore
    values["energy"] = 5.0
    formats[("", "energy")] = Format.CHILD
    assert snapshot.settings == {beamline.energy: 3.0}
    assert snapshot.readable_formats == {
        beamline: {beamline.energy: Format.HINTED_SIGNAL}
    }


async def test_store_snapshot_only_config_still_stores_formats(RE, tmp_path):
    provider = YamlSettingsProvider(tmp_path)
    device = StandardReadable(name="dev")
    device.config = soft_signal_rw(float, 1.0)
    device.other = soft_signal_rw(float, 2.0)
    device.set_name("dev")
    device.set_readable_format(device.config, Format.CONFIG_SIGNAL)

    def my_plan():
        yield from store_snapshot(provider, "config", device, only_config=True)
        with open(tmp_path / "config.yaml") as f:
            assert yaml.safe_load(f) == {
                "config": 1.0,
                "<READABLE_FORMATS>": {"config": "CONFIG_SIGNAL"},
            }

    RE(my_plan())


async def test_store_snapshot_warns_and_skips_a_readable_outside_the_tree(RE, tmp_path):
    """A child registered from outside the tree has no path to store it against.

    See https://github.com/bluesky/ophyd-async/issues/1402.
    """
    provider = YamlSettingsProvider(tmp_path)
    device = StandardReadable(name="dev")
    device.sig = soft_signal_rw(float, 1.0)
    device.set_name("dev")
    outsider = soft_signal_rw(float, 2.0, name="outsider")
    device.set_readable_format(device.sig, Format.CONFIG_SIGNAL)
    device.set_readable_format(outsider, Format.CONFIG_SIGNAL)

    def my_plan():
        with pytest.warns(UserWarning, match="dev: outsider is not within dev"):
            yield from store_snapshot(provider, "outsider", device)
        with open(tmp_path / "outsider.yaml") as f:
            assert yaml.safe_load(f) == {
                "sig": 1.0,
                "<READABLE_FORMATS>": {"sig": "CONFIG_SIGNAL"},
            }

    RE(my_plan())


@pytest.mark.parametrize(
    "device_cls, stored",
    [
        # An unchanged readable still writes the section, as applying it resets
        (StandardReadable, {"sig": 1.0, "<READABLE_FORMATS>": {}}),
        # No StandardReadable in the tree: nothing to reset
        (Device, {"sig": 1.0}),
    ],
)
async def test_store_snapshot_writes_the_section_only_for_a_readable(
    RE, tmp_path, device_cls, stored
):
    provider = YamlSettingsProvider(tmp_path)
    device = device_cls(name="dev")
    device.sig = soft_signal_rw(float, 1.0)
    device.set_name("dev")

    def my_plan():
        yield from store_snapshot(provider, "dev", device)
        with open(tmp_path / "dev.yaml") as f:
            assert yaml.safe_load(f) == stored

    RE(my_plan())


@pytest.mark.parametrize("deprecated", ["store_settings", "retrieve_settings"])
async def test_deprecated_settings_stubs_warn_and_still_work(
    RE, beamline: _Beamline, tmp_path, deprecated
):
    provider = YamlSettingsProvider(tmp_path)
    (tmp_path / "old.yaml").write_text(
        "<READABLE_FORMATS>:\n  energy: HINTED_SIGNAL\nenergy: 3.0\n"
    )

    def my_plan():
        if deprecated == "store_settings":
            with pytest.warns(DeprecationWarning, match="store_snapshot") as record:
                yield from store_settings(provider, "new", beamline)
            # Delegates to store_snapshot, so the formats are stored too
            with open(tmp_path / "new.yaml") as f:
                stored = yaml.safe_load(f)
            assert stored["energy"] == 7.0
            assert "<READABLE_FORMATS>" in stored
        else:
            with pytest.warns(DeprecationWarning, match="retrieve_snapshot") as record:
                # only_config has no effect, so the non-config energy is retrieved
                settings = yield from retrieve_settings(
                    provider, "old", beamline, only_config=True
                )
            # The formats section is skipped
            assert dict(settings) == {beamline.energy: 3.0}
        # The warning points at the caller of the plan
        assert record[0].filename == __file__

    RE(my_plan())
