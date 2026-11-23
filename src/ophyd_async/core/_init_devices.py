from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from bluesky.run_engine import call_in_bluesky_event_loop, in_bluesky_event_loop

from ._command import Command
from ._device import Device, DeviceMock, _mocked_and_class, _without_device_entry
from ._signal import Signal
from ._utils import (
    DEFAULT_TIMEOUT,
    NotConnectedError,
    error_if_none,
    wait_for_connection,
)


def _check_mock_types(mock_types: Mapping[Any, Any]) -> None:
    for typ, choice in mock_types.items():
        if not (isinstance(typ, type) and issubclass(typ, Device)):
            raise TypeError(f"mock mapping key {typ!r} is not a Device subclass")
        if issubclass(typ, Signal | Command):
            raise TypeError(
                f"mock mapping key {typ.__name__} is a Signal or Command type: "
                "these always follow their parent Device, so key on the Device"
            )
        if not (
            isinstance(choice, bool)
            or (isinstance(choice, type) and issubclass(choice, DeviceMock))
        ):
            raise TypeError(
                f"mock mapping value {choice!r} for {typ.__name__} is not a bool "
                "or a DeviceMock subclass"
            )


async def connect_devices(
    devices: Mapping[str, Device],
    mock: bool | Mapping[type[Device], bool | type[DeviceMock]] = False,
    timeout: float = DEFAULT_TIMEOUT,
    force_reconnect: bool = False,
    on_connect_hook: Callable[[str, Awaitable[None]], Awaitable[None]] | None = None,
) -> None:
    """Connect Devices in parallel, raising one error that lists any failures.

    :param devices: The Devices to connect, keyed by the name to report them as.
    :param mock:
        `False` connects for real, `True` mocks everything. A `Mapping` chooses
        per Device type, see [](#init_devices).
    :param timeout: Time to wait before failing with a TimeoutError.
    :param force_reconnect: If True, connect each Device and everything below it
        even if the connect is cached, see [](#Device.connect).
    :param on_connect_hook:
        Async function called with `(name, connect_coro)` for each Device, which
        must await `connect_coro`. See [](#init_devices).
    :raises TypeError:
        If `mock` is not a bool or a `Mapping`, or a `Mapping` key is not a Device
        subclass (or is a Signal or Command subclass) or a value is not a bool or
        DeviceMock subclass.
    :raises NotConnectedError: If devices could not be connected.
    """
    if isinstance(mock, Mapping):
        _check_mock_types(mock)
    elif not isinstance(mock, bool):
        raise TypeError(f"mock must be a bool or a Mapping, not {type(mock).__name__}")
    coros: dict[str, Awaitable[None]] = {}
    for name, device in devices.items():
        root_mock: bool | DeviceMock
        if isinstance(mock, Mapping):
            mocked, mock_class = _mocked_and_class(device, False, mock)
            root_mock = mock_class(
                mocked=mocked, mock_types=_without_device_entry(mock)
            )
        else:
            root_mock = mock
        coros[name] = device.connect(
            mock=root_mock, timeout=timeout, force_reconnect=force_reconnect
        )
    if on_connect_hook:
        coros = {name: on_connect_hook(name, coro) for name, coro in coros.items()}
    await wait_for_connection(**coros)


class DeviceProcessor:
    """Sync/Async Context Manager that finds all the Devices declared within it.

    Used in `init_devices`
    """

    def __init__(self, process_devices: Callable[[dict[str, Device]], Awaitable[None]]):
        self._process_devices = process_devices
        self._locals_on_enter: dict[str, Any] = {}
        self._locals_on_exit: dict[str, Any] = {}

    def _caller_locals(self) -> dict[str, Any]:
        """Walk up until we find a stack frame that doesn't have us as self."""
        try:
            raise ValueError
        except ValueError:
            _, _, tb = sys.exc_info()
            tb = error_if_none(tb, "Can't get traceback, this shouldn't happen")

            caller_frame = tb.tb_frame
            while caller_frame.f_locals.get("self", None) is self:
                caller_frame = caller_frame.f_back
                if not caller_frame:
                    msg = (
                        "No previous frame to the one with self in it, "
                        "this shouldn't happen"
                    )
                    raise RuntimeError(  # noqa: B904
                        msg
                    )
            return caller_frame.f_locals.copy()

    def __enter__(self) -> DeviceProcessor:
        # Stash the names that were defined before we were called
        self._locals_on_enter = self._caller_locals()
        return self

    async def __aenter__(self) -> DeviceProcessor:
        return self.__enter__()

    async def __aexit__(self, type, value, traceback):
        self._locals_on_exit = self._caller_locals()
        await self._on_exit()

    def __exit__(self, type_, value, traceback):
        if in_bluesky_event_loop():
            raise RuntimeError(
                "Cannot use DeviceConnector inside a plan, instead use "
                "`yield from ophyd_async.plan_stubs.ensure_connected(device)`"
            )
        self._locals_on_exit = self._caller_locals()
        try:
            fut = call_in_bluesky_event_loop(self._on_exit())
        except RuntimeError as exc:
            raise NotConnectedError(
                "Could not connect devices. Is the bluesky event loop running? See "
                "https://blueskyproject.io/ophyd-async/main/"
                "user/explanations/event-loop-choice.html for more info."
            ) from exc
        return fut

    async def _on_exit(self) -> None:
        # Find all the devices
        devices = {
            name: obj
            for name, obj in self._locals_on_exit.items()
            if isinstance(obj, Device) and self._locals_on_enter.get(name) is not obj
        }
        # Call the provided process function on them
        await self._process_devices(devices)


def init_devices(
    set_name: bool = True,
    child_name_separator: str = "-",
    connect: bool = True,
    mock: bool | Mapping[type[Device], bool | type[DeviceMock]] = False,
    timeout: float = 10.0,
    on_connect_hook: Callable[[str, Awaitable[None]], Awaitable[None]] | None = None,
):
    """Auto initialize top level Device instances: to be used as a context manager.

    :param set_name:
        If True, call `device.set_name(variable_name)` on all Devices created
        within the context manager that have an empty `name`.
    :param child_name_separator: Separator for child names if `set_name` is True.
    :param connect:
        If True, call `device.connect(mock, timeout)` in parallel on all Devices
        created within the context manager.
    :param mock:
        `False` connects everything for real, `True` mocks everything. A `Mapping`
        of Device type to `bool` or [](#DeviceMock) subclass chooses per type: each
        Device looks itself up by the nearest class in its MRO, and a DeviceMock
        subclass means mocked with that class. A Device with no entry follows its
        parent, so "mock this Device" means its whole subtree. An entry under
        `Device` is the default for the first level only, the top level Devices,
        real if there is none. `Signal` and `Command` types cannot be keys, as they
        always follow their parent Device.
    :param timeout: How long to wait for connect before logging an exception.
    :param on_connect_hook:
        Async function called with `(variable_name, connect_coro)` for each
        Device, which must await `connect_coro`. Any exception it lets escape
        is raised from `init_devices` as a `NotConnectedError`, so it can
        catch exceptions to suppress them. See [](#print_connection_status)
        for an example.
    :raises TypeError:
        If `mock` is not a bool or a `Mapping`, or a `Mapping` key is not a Device
        subclass (or is a Signal or Command subclass) or a value is not a bool or
        DeviceMock subclass.
    :raises RuntimeError: If used inside a plan, use [](#ensure_connected) instead.
    :raises NotConnectedError: If devices could not be connected.

    For example, to connect and name 2 motors in parallel:
    ```python
    [async] with init_devices():
        t1x = motor.Motor("BLxxI-MO-TABLE-01:X")
        t1y = motor.Motor("pva://BLxxI-MO-TABLE-01:Y")
        # Names and connects devices here
    assert t1x.name == "t1x"
    ```

    To mock only some types of Device, or the opposite:
    ```python
    [async] with init_devices(mock={Motor: True}):
        ...  # Motors, and everything below them, are mocked, the rest is real
    [async] with init_devices(mock={Device: True, Motor: False}):
        ...  # Everything is mocked, except Motors which are real all the way down
    ```
    """

    async def process_devices(devices: dict[str, Device]):
        if set_name:
            for name, device in devices.items():
                if not device.name:
                    device.set_name(name, child_name_separator=child_name_separator)
        if connect:
            await connect_devices(
                devices, mock, timeout, on_connect_hook=on_connect_hook
            )

    return DeviceProcessor(process_devices)


async def print_connection_status(name: str, coro: Awaitable[None]):
    """Print a coloured connection status line, for use as `on_connect_hook`.

    Exceptions are caught and reported rather than raised.

    :param name: The variable name of the Device.
    :param coro: The Device's connect coroutine.

    For example:
    ```python
    [async] with init_devices(on_connect_hook=print_connection_status):
        t1x = motor.Motor("BLxxI-MO-TABLE-01:X")
    ```
    """
    try:
        await coro
    except NotConnectedError:
        status = "\033[1;31m DISCONNECTED \033[0m"
    except Exception:
        status = "\033[1;31m    FAILED    \033[0m"
    else:
        status = "\033[1;32m      OK      \033[0m"
    dots = "." * (40 - len(name))
    print(f"  {name} {dots} [{status}]")
