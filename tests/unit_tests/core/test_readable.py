import asyncio
from collections.abc import Sequence
from unittest.mock import MagicMock

import pytest
from bluesky.protocols import HasHints

from ophyd_async.core import (
    Device,
    DeviceMap,
    DeviceVector,
    MockSignalBackend,
    SignalR,
    StandardReadable,
    TransitionError,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format


def test_standard_readable_hints():
    sr = StandardReadable()

    assert sr.hints == {}

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"fields": ["abc"], "dimensions": [(["f1", "f2"], "s1")]}

    hint2 = MagicMock(spec=HasHints)
    hint2.hints = {"fields": ["def", "ghi"]}

    hint3 = MagicMock(spec=HasHints)
    hint3.hints = {"fields": ["jkl"], "gridding": "rectilinear_nonsequential"}

    sr.set_readable_format(hint1, Format.CHILD)
    sr.set_readable_format(hint2, Format.CHILD)
    sr.set_readable_format(hint3, Format.CHILD)

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

    sr.set_readable_format(hint1, Format.CHILD)
    sr.set_readable_format(hint2, Format.CHILD)

    with pytest.raises(RuntimeError, match=r"Hint key .* may not be overridden"):
        sr.hints  # noqa: B018


@pytest.mark.parametrize(
    ["sub_hints", "error"],
    [
        ({"fields": "1"}, "'fields' key must be a Sequence, received <class 'str'>"),
        ({"fields": 1}, "'fields' key must be a Sequence, received <class 'int'>"),
        (
            {"dimensions": "1"},
            "'dimensions' key must be a Sequence, received <class 'str'>",
        ),
        (
            {"dimensions": 1},
            "'dimensions' key must be a Sequence, received <class 'int'>",
        ),
    ],
)
def test_incorrect_fields_and_dimensions_in_hints(sub_hints: dict, error: str):
    sr = StandardReadable()
    has_hints = MagicMock(spec=HasHints)
    has_hints.hints = sub_hints
    sr.set_readable_format(has_hints, Format.CHILD)

    with pytest.raises(RuntimeError, match=error):
        sr.hints  # noqa: B018


def test_standard_readable_arbitrary_hints():
    sr = StandardReadable()

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {
        "fields": ["field1"],
        "common-key": 1,
        "hint1-key": None,
        "dimensions": [(["f1", "f2"], "s1")],
        "gridding": "rectilinear_nonsequential",
    }

    hint2 = MagicMock(spec=HasHints)
    hint2.hints = {
        "fields": ["field2"],
        "common-key": 2,
        "hint2-key": None,
        "dimensions": [(["f3", "f4"], "s1")],
        "gridding": "rectilinear_nonsequential",
    }

    sr.set_readable_format(hint1, Format.CHILD)
    sr.set_readable_format(hint2, Format.CHILD)
    assert sr.hints == {
        "gridding": "rectilinear_nonsequential",
        "fields": ["field1", "field2"],
        "dimensions": [(["f1", "f2"], "s1"), (["f3", "f4"], "s1")],
    }  # Arbitrary keys left out.


def test_standard_readable_hints_raises_when_overriding_sequence():
    sr = StandardReadable()

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"fields": ["field1", "field2"]}

    hint2 = MagicMock(spec=HasHints)
    hint2.hints = {"fields": ["field2"]}

    sr.set_readable_format(hint1, Format.CHILD)
    sr.set_readable_format(hint2, Format.CHILD)

    with pytest.raises(RuntimeError, match=r"Hint 'fields' .* override existing hint"):
        sr.hints  # noqa: B018


def test_standard_readable_add_children_context_manager():
    sr = StandardReadable()
    with sr.add_children_as_readables():
        sr.a = MagicMock(spec=SignalR)
        sr.b = MagicMock(spec=SignalR)
        sr.c = MagicMock(spec=SignalR)

    assert list(sr.get_readable_formats()) == [
        (sr.a, Format.CHILD),
        (sr.b, Format.CHILD),
        (sr.c, Format.CHILD),
    ]


async def test_add_children_as_readables_registers_in_declaration_order():
    sr = StandardReadable(name="sr")
    names = ["zeta", "alpha", "mu", "beta", "omega", "gamma", "kappa", "delta"]
    with sr.add_children_as_readables(Format.HINTED_SIGNAL):
        for name in names:
            setattr(sr, name, soft_signal_r_and_setter(int, 0)[0])

    assert sr.hints == {"fields": [f"sr-{name}" for name in names]}


@pytest.mark.parametrize(
    "device_type, keys",
    [
        (DeviceVector, [1, 2, 3]),
        (DeviceMap, ["a", "b", "c"]),
    ],
)
def test_standard_readable_add_children_cm_device_with_mappings(device_type, keys):
    sr = StandardReadable()

    # A DeviceVector/DeviceMap registers its values, not itself
    devices = [MagicMock(spec=SignalR) for _ in range(3)]
    device = device_type(dict(zip(keys, devices, strict=True)))

    with sr.add_children_as_readables():
        sr.a = device

    assert list(sr.get_readable_formats()) == [(d, Format.CHILD) for d in devices]


def test_standard_readable_add_children_cm_filters_non_devices():
    sr = StandardReadable()

    with sr.add_children_as_readables():
        sr.a = MagicMock(spec=SignalR)
        sr.b = MagicMock(spec=Device)
        sr.c = 1.0
        sr.d = "abc"
        sr.e = MagicMock(spec=MockSignalBackend)

    # Only the Devices are registered
    assert list(sr.get_readable_formats()) == [
        (sr.a, Format.CHILD),
        (sr.b, Format.CHILD),
    ]


async def assert_contributes(
    sr: StandardReadable,
    *,
    read: Sequence[str] = (),
    config: Sequence[str] = (),
    hints: Sequence[str] = (),
) -> None:
    """Assert which keys a StandardReadable contributes to each verb."""
    assert list(await sr.read()) == list(read)
    assert list(await sr.describe()) == list(read)
    assert list(await sr.read_configuration()) == list(config)
    assert list(await sr.describe_configuration()) == list(config)
    assert list(sr.hints.get("fields", [])) == list(hints)


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
    name = [sr.sig.name]
    await assert_contributes(
        sr,
        read=name if in_read else [],
        config=name if in_config else [],
        hints=name if in_hints else [],
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
        read=[inner.val.name],
        config=[inner.conf.name],
        hints=[inner.val.name],
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
        sr.set_readable_format(mock_device, format)


def test_add_readables_is_deprecated() -> None:
    sr = StandardReadable()
    sig = soft_signal_rw(int)
    with pytest.warns(DeprecationWarning, match="set_readable_format"):
        sr.add_readables([sig], Format.CONFIG_SIGNAL)
    # Still does the job it always did
    assert list(sr.get_readable_formats()) == [(sig, Format.CONFIG_SIGNAL)]


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


async def test_standard_readable_stage_twice_raises():
    sr = StandardReadable(name="sr")
    await sr.stage()
    # Like ophyd's RedundantStaging
    with pytest.raises(TransitionError, match="cannot go to STAGING from STAGED"):
        await sr.stage()
    await sr.unstage()
    await sr.stage()


class SlowToStage(StandardReadable):
    """Its stage hook runs until cancelled, as if staged beside a failing device."""

    def __init__(self, name: str = "") -> None:
        super().__init__(name=name)
        self.calls: list[str] = []
        self.staging = asyncio.Event()
        # Registered as a mix-in would
        self._stage_funcs += (self.__on_stage,)
        self._unstage_funcs += (self.__on_unstage,)

    async def __on_stage(self) -> None:
        self.calls.append("stage")
        self.staging.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.calls.append("stage cancelled")
            raise

    async def __on_unstage(self) -> None:
        self.calls.append("unstage")


async def test_unstage_cancels_a_stage_still_running():
    device = SlowToStage(name="device")
    stage = device.stage()
    await device.staging.wait()

    await device.unstage()

    # The stage is cancelled before the unstage hooks run
    assert device.calls == ["stage", "stage cancelled", "unstage"]
    with pytest.raises(asyncio.CancelledError):
        await stage


async def test_set_readable_format_changes_verb_at_runtime():
    # The ophyd v1 `kind` use case from #1394: a signal that is config for one
    # technique and hinted for another, without redefining the Device.
    sr = StandardReadable(name="sr")
    sr.energy, _ = soft_signal_r_and_setter(float, 0.0, name="energy")

    sr.set_readable_format(sr.energy, Format.CONFIG_SIGNAL)
    await assert_contributes(sr, config=[sr.energy.name])

    sr.set_readable_format(sr.energy, Format.HINTED_SIGNAL)
    await assert_contributes(sr, read=[sr.energy.name], hints=[sr.energy.name])

    sr.set_readable_format(sr.energy, None)
    await assert_contributes(sr)


async def test_set_readable_format_replaces_rather_than_duplicates():
    sr = StandardReadable(name="sr")
    sr.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")

    sr.set_readable_format(sr.sig, Format.HINTED_SIGNAL)
    sr.set_readable_format(sr.sig, Format.HINTED_SIGNAL)

    assert sr.hints == {"fields": [sr.sig.name]}
    assert list(sr.get_readable_formats()) == [(sr.sig, Format.HINTED_SIGNAL)]


async def test_get_readable_formats_omits_unregistered_children():
    sr = StandardReadable(name="sr")
    sr.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")
    sr.other, _ = soft_signal_r_and_setter(int, 0, name="other")
    assert list(sr.get_readable_formats()) == []
    sr.set_readable_format(sr.sig, Format.CONFIG_SIGNAL)
    sr.set_readable_format(sr.other, Format.HINTED_SIGNAL)
    # Registration order is preserved, and an unregistered child is absent
    assert list(sr.get_readable_formats()) == [
        (sr.sig, Format.CONFIG_SIGNAL),
        (sr.other, Format.HINTED_SIGNAL),
    ]
    sr.set_readable_format(sr.sig, None)
    assert list(sr.get_readable_formats()) == [(sr.other, Format.HINTED_SIGNAL)]


async def test_set_readable_format_while_iterating_get_readable_formats():
    sr = StandardReadable(name="sr")
    sr.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")
    sr.other, _ = soft_signal_r_and_setter(int, 0, name="other")
    sr.set_readable_format(sr.sig, Format.CONFIG_SIGNAL)
    sr.set_readable_format(sr.other, Format.CONFIG_SIGNAL)

    for signal, _format in sr.get_readable_formats():
        sr.set_readable_format(signal, Format.HINTED_SIGNAL)
    for signal, _format in sr.get_readable_format_changes():
        sr.set_readable_format(signal, None)

    assert list(sr.get_readable_formats()) == []


async def test_reset_readable_formats_undoes_runtime_changes():
    class Dev(StandardReadable):
        def __init__(self, name=""):
            self.energy, _ = soft_signal_r_and_setter(float, 0.0, name="energy")
            self.temp, _ = soft_signal_r_and_setter(float, 0.0, name="temp")
            self.set_readable_format(self.energy, Format.CONFIG_SIGNAL)
            self.set_readable_format(self.temp, Format.CONFIG_SIGNAL)
            super().__init__(name=name)

    dev = Dev(name="dev")
    dev.extra, _ = soft_signal_r_and_setter(float, 0.0, name="extra")
    declared = list(dev.get_readable_formats())

    # Change one, drop one, add one that was never declared
    dev.set_readable_format(dev.energy, Format.HINTED_SIGNAL)
    dev.set_readable_format(dev.temp, None)
    dev.set_readable_format(dev.extra, Format.HINTED_SIGNAL)
    assert list(dev.get_readable_formats()) == [
        (dev.energy, Format.HINTED_SIGNAL),
        (dev.extra, Format.HINTED_SIGNAL),
    ]
    assert list(dev.get_readable_format_changes()) == [
        (dev.energy, Format.HINTED_SIGNAL),
        (dev.extra, Format.HINTED_SIGNAL),
        (dev.temp, None),
    ]

    dev.reset_readable_formats()
    assert list(dev.get_readable_formats()) == declared
    assert list(dev.get_readable_format_changes()) == []
    # Repeatable, and the baseline is not consumed
    dev.set_readable_format(dev.energy, None)
    dev.reset_readable_formats()
    assert list(dev.get_readable_formats()) == declared


async def test_reset_readable_formats_keeps_registrations_after_super_init():
    # The reason the baseline is sealed by the metaclass rather than at the end
    # of StandardReadable.__init__: this registration happens after super() and
    # is still part of what the class declares
    class Dev(StandardReadable):
        def __init__(self, name=""):
            self.before, _ = soft_signal_r_and_setter(int, 0, name="before")
            self.set_readable_format(self.before, Format.CONFIG_SIGNAL)
            super().__init__(name=name)
            self.after, _ = soft_signal_r_and_setter(int, 0, name="after")
            self.set_readable_format(self.after, Format.HINTED_SIGNAL)

    dev = Dev(name="dev")
    expected = [(dev.before, Format.CONFIG_SIGNAL), (dev.after, Format.HINTED_SIGNAL)]
    assert list(dev.get_readable_formats()) == expected

    dev.set_readable_format(dev.after, None)
    dev.reset_readable_formats()
    assert list(dev.get_readable_formats()) == expected


async def test_reset_readable_formats_restores_annotated_declarations():
    sr = StandardReadable(name="sr")
    sr.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")
    # Nothing declared, so a runtime registration resets away entirely
    sr.set_readable_format(sr.sig, Format.HINTED_SIGNAL)
    sr.reset_readable_formats()
    assert list(sr.get_readable_formats()) == []


async def test_default_readable_formats_are_not_shared_between_instances():
    class Dev(StandardReadable):
        def __init__(self, name=""):
            self.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")
            self.set_readable_format(self.sig, Format.CONFIG_SIGNAL)
            super().__init__(name=name)

    a, b = Dev(name="a"), Dev(name="b")
    a.set_readable_format(a.sig, None)
    a.reset_readable_formats()
    b.reset_readable_formats()
    assert list(a.get_readable_formats()) == [(a.sig, Format.CONFIG_SIGNAL)]
    assert list(b.get_readable_formats()) == [(b.sig, Format.CONFIG_SIGNAL)]
    assert StandardReadable._default_readables == {}


async def test_readables_registered_before_super_init_survive():
    # Devices register children before calling super().__init__(),
    # so the registry must not be created there. It must also be per instance.
    class Dev(StandardReadable):
        def __init__(self, name=""):
            self.sig, _ = soft_signal_r_and_setter(int, 0, name="sig")
            self.set_readable_format(self.sig, Format.HINTED_SIGNAL)
            super().__init__(name=name)

    a, b = Dev(name="a"), Dev(name="b")
    assert list(a.get_readable_formats()) == [(a.sig, Format.HINTED_SIGNAL)]
    assert list(b.get_readable_formats()) == [(b.sig, Format.HINTED_SIGNAL)]

    b.set_readable_format(b.sig, None)
    assert list(a.get_readable_formats()) == [(a.sig, Format.HINTED_SIGNAL)]
    assert list(b.get_readable_formats()) == []


async def test_set_readable_format_keeps_position_when_reformatting():
    # Changing a format must not reorder hints
    sr = StandardReadable(name="sr")
    sr.one, _ = soft_signal_r_and_setter(int, 0, name="one")
    sr.two, _ = soft_signal_r_and_setter(int, 0, name="two")
    sr.set_readable_format(sr.one, Format.HINTED_SIGNAL)
    sr.set_readable_format(sr.two, Format.HINTED_SIGNAL)
    assert sr.hints == {"fields": [sr.one.name, sr.two.name]}

    sr.set_readable_format(sr.one, Format.HINTED_UNCACHED_SIGNAL)
    assert sr.hints == {"fields": [sr.one.name, sr.two.name]}


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
