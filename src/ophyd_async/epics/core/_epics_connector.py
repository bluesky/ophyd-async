from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, TypeVar

from ophyd_async.core import Device, DeviceConnector, DeviceFiller

from ._signal import (
    get_command_backend_type,
    get_signal_backend_type,
    split_protocol_from_pv,
)
from ._util import EpicsCommandBackend, EpicsOptions, EpicsSignalBackend


@dataclass
class PvSuffix:
    """Define the PV suffix to be appended to the device prefix.

    For a SignalRW:
    - If you use the same "Suffix" for the read and write PV then use PvSuffix("Suffix")
    - If you have "Suffix" for the write PV and "Suffix_RBV" for the read PV then use
      PvSuffix.rbv("Suffix")
    - If you have "WriteSuffix" for the write PV and "ReadSuffix" for the read PV then
      you use PvSuffix(read_suffix="ReadSuffix", write_suffix="WriteSuffix")

    For a SignalR:
    - If you have "Suffix" for the read PV then use PvSuffix("Suffix")
    - If you have "Suffix_RBV" for the read PV then use PvSuffix("Suffix_RBV"), do not
      use PvSuffix.rbv as that will try to connect to multiple PVs
    """

    read_suffix: str
    write_suffix: str | None = None

    @classmethod
    def rbv(cls, write_suffix: str, rbv_suffix: str = "_RBV") -> PvSuffix:
        return cls(write_suffix + rbv_suffix, write_suffix)


class _PvPrefixDeviceConnector(DeviceConnector):
    """Baseclass for `DeviceConnector`s that address a Device by PV prefix.

    :param prefix:
        The PV prefix of the Device. Empty when the connector is made for a
        declarative sub-device, whose parent sets the prefix via `set_prefix`
        before the child is constructed.
    """

    def __init__(self, prefix: str = "") -> None:
        self.set_prefix(prefix)

    def set_prefix(self, prefix: str) -> None:
        """Set the PV prefix, and anything the subclass derives from it."""
        self.prefix = prefix


EpicsSignalBackendT = TypeVar("EpicsSignalBackendT", bound=EpicsSignalBackend)
EpicsCommandBackendT = TypeVar("EpicsCommandBackendT", bound=EpicsCommandBackend)
_PvPrefixDeviceConnectorT = TypeVar(
    "_PvPrefixDeviceConnectorT", bound=_PvPrefixDeviceConnector
)


def fill_children_with_prefix(
    prefix: str,
    filler: DeviceFiller[
        EpicsSignalBackendT, _PvPrefixDeviceConnectorT, EpicsCommandBackendT
    ],
    filled: bool = True,
):
    """Create a Device's declarative children, addressing them under `prefix`.

    Each Signal, Command and sub-device annotated with a [](#PvSuffix) is
    addressed at `prefix` plus that suffix.

    :param prefix: The parent Device's PV prefix, which may name a protocol.
    :param filler: The parent Device's `DeviceFiller`.
    :param filled:
        If True then a [](#PvSuffix) is the only thing that will address these
        children, so a sub-device must have one. If False then a PVI structure
        will address them at connection time, and a [](#PvSuffix) is optional.
    """
    # Signals and commands connect to a bare PV, but a sub-device's connector
    # re-derives the protocol from the prefix it is given, so keep it there.
    _, pv_prefix = split_protocol_from_pv(prefix)
    for backend, signal_annotations in filler.create_signals_from_annotations(
        filled=filled
    ):
        fill_backend_with_prefix(pv_prefix, backend, signal_annotations)
    for command_backend, command_annotations in filler.create_commands_from_annotations(
        filled=filled
    ):
        fill_command_with_prefix(pv_prefix, command_backend, command_annotations)
    for connector, device_annotations in filler.create_devices_from_annotations(
        filled=filled
    ):
        fill_connector_with_prefix(
            prefix, connector, device_annotations, required=filled
        )


def fill_command_with_prefix(
    prefix: str, backend: EpicsCommandBackend, annotations: list[Any]
):
    """Set the `write_pv` on an EPICS command backend from a [](#PvSuffix)."""
    unhandled = []
    while annotations:
        annotation = annotations.pop(0)
        if isinstance(annotation, PvSuffix):
            backend.write_pv = prefix + (
                annotation.write_suffix or annotation.read_suffix
            )
        else:
            unhandled.append(annotation)
    annotations.extend(unhandled)


def fill_connector_with_prefix(
    prefix: str,
    connector: _PvPrefixDeviceConnector,
    annotations: list[Any],
    required: bool = True,
):
    """Set a declarative sub-device's connector prefix from a [](#PvSuffix).

    The child connector's prefix becomes the parent prefix plus that suffix, so
    the child's own signals connect under it.

    :param required:
        If True then a `PvSuffix` is the only thing that will address the child,
        so raise a `TypeError` if there isn't one. If False then something else
        (a PVI structure) will address it, and a `PvSuffix` is optional.
    """
    unhandled = []
    suffix: str | None = None
    while annotations:
        annotation = annotations.pop(0)
        if isinstance(annotation, PvSuffix):
            # A sub-device is addressed by a single prefix; use the read suffix.
            suffix = annotation.read_suffix
        else:
            unhandled.append(annotation)
    annotations.extend(unhandled)
    if suffix is not None:
        connector.set_prefix(prefix + suffix)
    elif required:
        raise TypeError(
            "A declarative EPICS sub-device must be given a PvSuffix to set its "
            "prefix, but none was found in its annotations"
        )
    # Any leftover annotations (e.g. StandardReadableFormat) are handled by the filler


def fill_backend_with_prefix(
    prefix: str, backend: EpicsSignalBackend, annotations: list[Any]
):
    unhandled = []
    while annotations:
        annotation = annotations.pop(0)
        if isinstance(annotation, PvSuffix):
            backend.read_pv = prefix + annotation.read_suffix
            backend.write_pv = prefix + (
                annotation.write_suffix or annotation.read_suffix
            )
        elif isinstance(annotation, EpicsOptions):
            backend.options = annotation
        else:
            unhandled.append(annotation)
    annotations.extend(unhandled)
    # These leftover annotations will now be handled by the iterator


class EpicsDeviceConnector(_PvPrefixDeviceConnector):
    """Used for connecting signals to static EPICS pvs."""

    def create_children_from_annotations(self, device: Device):
        if not hasattr(self, "filler"):
            protocol, _ = split_protocol_from_pv(self.prefix)

            def _command_backend_factory(
                sig: inspect.Signature | None,
            ) -> EpicsCommandBackend:
                # EPICS only supports void/void commands (plain PV put); typed
                # Command[P, T] annotations are a mistake on an EPICS device.
                if sig is not None:
                    raise TypeError(
                        f"{device.name}: EPICS only supports TriggerableCommand /"
                        " Command[[], None]; typed Command with parameters is not"
                        " yet supported over EPICS"
                    )
                return get_command_backend_type(protocol)()

            self.filler = DeviceFiller(
                device,
                signal_backend_factory=get_signal_backend_type(protocol),
                # Declarative sub-devices get their own EpicsDeviceConnector so
                # their signals are created under a PvSuffix-derived prefix.
                device_connector_factory=EpicsDeviceConnector,
                command_backend_factory=_command_backend_factory,
            )
            fill_children_with_prefix(self.prefix, self.filler)
