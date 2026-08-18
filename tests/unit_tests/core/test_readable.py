from unittest.mock import MagicMock

import pytest
from bluesky.protocols import HasHints

from ophyd_async.core import (
    ConfigSignal,
    Device,
    DeviceMap,
    DeviceVector,
    HintedSignal,
    MockSignalBackend,
    SignalR,
    StandardReadable,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format


@pytest.mark.parametrize("wrapper", [HintedSignal, HintedSignal.uncached, ConfigSignal])
def test_standard_readable_wrappers_raise_deprecation_warning(wrapper):
    sr = StandardReadable()
    with pytest.deprecated_call():
        sr.add_readables([soft_signal_rw(int)], wrapper)


def test_standard_readable_hints():
    sr = StandardReadable()

    assert sr.hints == {}

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"fields": ["abc"], "dimensions": [(["f1", "f2"], "s1")]}

    hint2 = MagicMock(spec=HasHints)
    hint2.hints = {"fields": ["def", "ghi"]}

    hint3 = MagicMock(spec=HasHints)
    hint3.hints = {"fields": ["jkl"], "gridding": "rectilinear_nonsequential"}

    sr.add_readables([hint1, hint2, hint3])

    assert sr.hints == {
        "fields": ["abc", "def", "ghi", "jkl"],
        "dimensions": [(["f1", "f2"], "s1")],
        "gridding": "rectilinear_nonsequential",
    }


def test_standard_readable_hints_raises_when_overriding_string_literal():
    sr = StandardReadable()

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"gridding": "rectilinear_nonsequential"}

    hint2 = MagicMock(spec=HasHints)
    hint2.hints = {"gridding": "a different string"}

    sr.add_readables([hint1, hint2])

    with pytest.raises(RuntimeError, match=r"Hints key .* value may not be overridden"):
        sr.hints  # noqa: B018


def test_standard_readable_hints_raises_when_overriding_sequence():
    sr = StandardReadable()

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"fields": ["field1", "field2"]}

    hint2 = MagicMock(spec=HasHints)
    hint2.hints = {"fields": ["field2"]}

    sr.add_readables([hint1, hint2])

    with pytest.raises(RuntimeError, match=r"Hint fields .* overrides existing hint"):
        sr.hints  # noqa: B018


@pytest.mark.parametrize("invalid_type", [1, 1.0, {"abc": "def"}, {1, 2, 3}])
def test_standard_readable_hints_invalid_types(invalid_type):
    sr = StandardReadable()

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"test": invalid_type}

    sr.add_readables([hint1])

    with pytest.raises(TypeError, match=r"Unknown type for value .* for key .*"):
        sr.hints  # noqa: B018


def test_standard_readable_add_children_context_manager():
    sr = StandardReadable()
    mock = MagicMock()
    sr.add_readables = mock
    with sr.add_children_as_readables():
        sr.a = MagicMock(spec=SignalR)
        sr.b = MagicMock(spec=SignalR)
        sr.c = MagicMock(spec=SignalR)

    # Can't use assert_called_once_with() as the order of items returned from
    # internal dict comprehension is not guaranteed
    mock.assert_called_once()
    assert set(mock.call_args.args[0]) == {sr.a, sr.b, sr.c}


@pytest.mark.parametrize(
    "device_type, keys",
    [
        (DeviceVector, [1, 2, 3]),
        (DeviceMap, ["a", "b", "c"]),
    ],
)
def test_standard_readable_add_children_cm_device_with_mappings(device_type, keys):
    sr = StandardReadable()
    mock = MagicMock()
    sr.add_readables = mock

    # Create a mock for the DeviceVector/DeviceMap.children() call
    devices = [MagicMock(spec=SignalR) for _ in range(3)]
    device = device_type(dict(zip(keys, devices, strict=True)))

    with sr.add_children_as_readables():
        sr.a = device

    # Can't use assert_called_once_with() as the order of items returned from
    # internal dict comprehension is not guaranteed
    mock.assert_called_once()
    assert set(mock.call_args.args[0]) == set(devices)


def test_standard_readable_add_children_cm_filters_non_devices():
    sr = StandardReadable()
    mock = MagicMock()
    sr.add_readables = mock

    with sr.add_children_as_readables():
        sr.a = MagicMock(spec=SignalR)
        sr.b = MagicMock(spec=Device)
        sr.c = 1.0
        sr.d = "abc"
        sr.e = MagicMock(spec=MockSignalBackend)

    # Can't use assert_called_once_with() as the order of items returned from
    # internal dict comprehension is not guaranteed
    mock.assert_called_once()
    assert set(mock.call_args.args[0]) == {sr.a, sr.b}


async def assert_contributes(
    sr: StandardReadable,
    *,
    read: set[str] = frozenset(),
    config: set[str] = frozenset(),
    hints: set[str] = frozenset(),
) -> None:
    """Assert which keys a StandardReadable contributes to each verb."""
    assert set(await sr.read()) == set(read)
    assert set(await sr.describe()) == set(read)
    assert set(await sr.read_configuration()) == set(config)
    assert set(await sr.describe_configuration()) == set(config)
    assert set(sr.hints.get("fields", [])) == set(hints)


@pytest.mark.parametrize(
    "format, in_read, in_config, in_hints",
    [
        (Format.CONFIG_SIGNAL, False, True, False),
        (Format.HINTED_SIGNAL, True, False, True),
        (Format.UNCACHED_SIGNAL, True, False, False),
        (Format.HINTED_UNCACHED_SIGNAL, True, False, True),
    ],
)
async def test_standard_readable_signal_formats_route_to_expected_verbs(
    format, in_read, in_config, in_hints
):
    sr = StandardReadable(name="sr")
    sr.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")
    sr.set_readable_format(sr.sig, format)
    name = {sr.sig.name}
    await assert_contributes(
        sr,
        read=name if in_read else set(),
        config=name if in_config else set(),
        hints=name if in_hints else set(),
    )


async def test_standard_readable_child_format_uses_child_verbs():
    inner = StandardReadable(name="inner")
    inner.conf, _ = soft_signal_r_and_setter(int, 0, name="conf")
    inner.val, _ = soft_signal_r_and_setter(int, 0, name="val")
    inner.set_readable_format(inner.conf, Format.CONFIG_SIGNAL)
    inner.set_readable_format(inner.val, Format.HINTED_SIGNAL)

    outer = StandardReadable(name="outer")
    outer.inner = inner
    outer.set_readable_format(inner, Format.CHILD)

    await assert_contributes(
        outer,
        read={inner.val.name},
        config={inner.conf.name},
        hints={inner.val.name},
    )


async def test_standard_readable_child_format_ignores_plain_device():
    sr = StandardReadable(name="sr")
    sr.child = Device(name="child")
    sr.set_readable_format(sr.child, Format.CHILD)
    await assert_contributes(sr)


@pytest.mark.parametrize(
    "format",
    [
        Format.CONFIG_SIGNAL,
        Format.HINTED_SIGNAL,
        Format.UNCACHED_SIGNAL,
        Format.HINTED_UNCACHED_SIGNAL,
    ],
)
def test_standard_readable_add_readables_raises_signalr_typeerror(format) -> None:
    # Mock a Device instance that is not a SignalR
    mock_device = MagicMock(spec=Device)
    sr = StandardReadable()

    # Ensure it raises TypeError
    with pytest.raises(TypeError, match=f"{mock_device} is not a SignalR"):
        sr.add_readables([mock_device], format=format)


@pytest.mark.parametrize(
    "format, staged",
    [
        (Format.HINTED_SIGNAL, True),
        (Format.CHILD, True),
        (Format.CONFIG_SIGNAL, False),
        (Format.UNCACHED_SIGNAL, False),
        (Format.HINTED_UNCACHED_SIGNAL, False),
    ],
)
async def test_standard_readable_stage_starts_caching_only_for_cached_formats(
    format, staged
):
    # stage() exists to start monitoring, and reading cached raises if it isn't
    sr = StandardReadable(name="sr")
    sr.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")
    await sr.sig.connect(mock=False)
    sr.set_readable_format(sr.sig, format)

    await sr.stage()
    if staged:
        assert await sr.sig.read(cached=True)
    else:
        with pytest.raises(RuntimeError, match="not being monitored"):
            await sr.sig.read(cached=True)

    # unstage tears the monitor back down
    await sr.unstage()
    with pytest.raises(RuntimeError, match="not being monitored"):
        await sr.sig.read(cached=True)


def test_standard_readable_add_children_multi_nested():
    inner = StandardReadable()
    outer = StandardReadable()
    with inner.add_children_as_readables(Format.HINTED_SIGNAL):
        inner.a, _ = soft_signal_r_and_setter(float, initial_value=5.0)
        inner.b, _ = soft_signal_r_and_setter(float, initial_value=6.0)
    with outer.add_children_as_readables():
        outer.inner = inner
    assert outer


async def test_duplicate_readable_raises_exception():
    class DummyBaseDevice(StandardReadable):
        def __init__(self, name):
            with self.add_children_as_readables():
                self.twin = soft_signal_rw(float)
            super().__init__(name)

    class DummyDerivedDevice(DummyBaseDevice):
        def __init__(self, name):
            with self.add_children_as_readables():
                self.twin = soft_signal_rw(float)
            super().__init__(name)

    with pytest.raises(KeyError):
        DummyDerivedDevice("test_duplicates")


async def test_set_readable_format_changes_verb_at_runtime():
    # The ophyd v1 `kind` use case from #1394: a signal that is config for one
    # technique and hinted for another, without redefining the Device.
    sr = StandardReadable(name="sr")
    sr.energy, _ = soft_signal_r_and_setter(float, 0.0, name="energy")

    sr.set_readable_format(sr.energy, Format.CONFIG_SIGNAL)
    await assert_contributes(sr, config={sr.energy.name})

    sr.set_readable_format(sr.energy, Format.HINTED_SIGNAL)
    await assert_contributes(sr, read={sr.energy.name}, hints={sr.energy.name})

    sr.set_readable_format(sr.energy, None)
    await assert_contributes(sr)


async def test_set_readable_format_replaces_rather_than_duplicates():
    sr = StandardReadable(name="sr")
    sr.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")

    sr.set_readable_format(sr.sig, Format.HINTED_SIGNAL)
    sr.set_readable_format(sr.sig, Format.HINTED_SIGNAL)

    assert sr.hints == {"fields": [sr.sig.name]}
    assert sr.get_readable_format(sr.sig) is Format.HINTED_SIGNAL


async def test_get_readable_format_returns_none_when_unregistered():
    sr = StandardReadable(name="sr")
    sr.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")
    assert sr.get_readable_format(sr.sig) is None
    sr.set_readable_format(sr.sig, Format.CONFIG_SIGNAL)
    assert sr.get_readable_format(sr.sig) is Format.CONFIG_SIGNAL


async def test_set_readable_format_affects_staging_of_later_runs():
    sr = StandardReadable(name="sr")
    sr.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")
    await sr.sig.connect(mock=False)
    sr.set_readable_format(sr.sig, Format.HINTED_SIGNAL)

    await sr.stage()
    assert await sr.sig.read(cached=True)
    await sr.unstage()

    # Dropping the signal means the next run does not monitor it
    sr.set_readable_format(sr.sig, None)
    await sr.stage()
    with pytest.raises(RuntimeError, match="not being monitored"):
        await sr.sig.read(cached=True)
    await sr.unstage()


def test_set_readable_format_rejects_non_signal_for_signal_format():
    sr = StandardReadable(name="sr")
    sr.child = Device(name="child")
    with pytest.raises(TypeError, match="is not a SignalR"):
        sr.set_readable_format(sr.child, Format.CONFIG_SIGNAL)
