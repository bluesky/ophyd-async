import re
import types
from collections.abc import Callable
from dataclasses import dataclass
from inspect import isclass
from typing import (
    Any,
    Literal,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    DeviceVector,
    Signal,
    SoftSignalBackend,
    T,
)
from ophyd_async.epics.signal import (
    PvaSignalBackend,
    epics_signal_r,
    epics_signal_rw,
    epics_signal_w,
    epics_signal_x,
)

Access = frozenset[
    Literal["r"] | Literal["w"] | Literal["rw"] | Literal["x"] | Literal["d"]
]


def _strip_number_from_string(string: str) -> tuple[str, int | None]:
    match = re.match(r"(.*?)(\d*)$", string)
    assert match

    name = match.group(1)
    number = match.group(2) or None
    if number is None:
        return name, None
    else:
        return name, int(number)


def _split_subscript(tp: T) -> tuple[Any, tuple[Any]] | tuple[T, None]:
    """Split a subscripted type into the its origin and args.

    If `tp` is not a subscripted type, then just return the type and None as args.

    """
    if get_origin(tp) is not None:
        return get_origin(tp), get_args(tp)

    return tp, None


def _strip_union(field: T | T) -> tuple[T, bool]:
    if get_origin(field) in [Union, types.UnionType]:
        args = get_args(field)
        is_optional = type(None) in args
        for arg in args:
            if arg is not type(None):
                return arg, is_optional
    return field, False


def _strip_device_vector(field: type[Device]) -> tuple[bool, type[Device]]:
    if get_origin(field) is DeviceVector:
        return True, get_args(field)[0]
    return False, field


@dataclass
class _PVIEntry:
    """
    A dataclass to represent a single entry in the PVI table.
    This could either be a signal or a sub-table.
    """

    sub_entries: dict[str, Union[dict[int, "_PVIEntry"], "_PVIEntry"]]
    pvi_pv: str | None = None
    device: Device | None = None
    common_device_type: type[Device] | None = None


def _verify_common_blocks(entry: _PVIEntry, common_device: type[Device]):
    if not entry.sub_entries:
        return
    common_sub_devices = get_type_hints(common_device)
    for sub_name, sub_device in common_sub_devices.items():
        if sub_name.startswith("_") or sub_name == "parent":
            continue
        assert entry.sub_entries
        device_t, is_optional = _strip_union(sub_device)
        if sub_name not in entry.sub_entries and not is_optional:
            raise RuntimeError(
                f"sub device `{sub_name}:{type(sub_device)}` " "was not provided by pvi"
            )
        if isinstance(entry.sub_entries[sub_name], dict):
            for sub_sub_entry in entry.sub_entries[sub_name].values():  # type: ignore
                _verify_common_blocks(sub_sub_entry, sub_device)  # type: ignore
        else:
            _verify_common_blocks(
                entry.sub_entries[sub_name],  # type: ignore
                sub_device,  # type: ignore
            )


_pvi_mapping: dict[frozenset[str], Callable[..., Signal]] = {
    frozenset({"r", "w"}): lambda dtype, read_pv, write_pv: epics_signal_rw(
        dtype, "pva://" + read_pv, "pva://" + write_pv
    ),
    frozenset({"rw"}): lambda dtype, read_write_pv: epics_signal_rw(
        dtype, "pva://" + read_write_pv, write_pv="pva://" + read_write_pv
    ),
    frozenset({"r"}): lambda dtype, read_pv: epics_signal_r(dtype, "pva://" + read_pv),
    frozenset({"w"}): lambda dtype, write_pv: epics_signal_w(
        dtype, "pva://" + write_pv
    ),
    frozenset({"x"}): lambda _, write_pv: epics_signal_x("pva://" + write_pv),
}


def _parse_type(
    is_pvi_table: bool,
    number_suffix: int | None,
    common_device_type: type[Device] | None,
):
    if common_device_type:
        # pre-defined type
        device_cls, _ = _strip_union(common_device_type)
        is_device_vector, device_cls = _strip_device_vector(device_cls)
        device_cls, device_args = _split_subscript(device_cls)
        assert issubclass(device_cls, Device)

        is_signal = issubclass(device_cls, Signal)
        signal_dtype = device_args[0] if device_args is not None else None

    elif is_pvi_table:
        # is a block, we can make it a DeviceVector if it ends in a number
        is_device_vector = number_suffix is not None
        is_signal = False
        signal_dtype = None
        device_cls = Device
    else:
        # is a signal, signals aren't stored in DeviceVectors unless
        # they're defined as such in the common_device_type
        is_device_vector = False
        is_signal = True
        signal_dtype = None
        device_cls = Signal

    return is_device_vector, is_signal, signal_dtype, device_cls


def _mock_common_blocks(device: Device, stripped_type: type | None = None):
    device_t = stripped_type or type(device)
    sub_devices = (
        (field, field_type)
        for field, field_type in get_type_hints(device_t).items()
        if not field.startswith("_") and field != "parent"
    )

    for device_name, device_cls in sub_devices:
        device_cls, _ = _strip_union(device_cls)
        is_device_vector, device_cls = _strip_device_vector(device_cls)
        device_cls, device_args = _split_subscript(device_cls)
        assert issubclass(device_cls, Device)

        signal_dtype = device_args[0] if device_args is not None else None

        if is_device_vector:
            if issubclass(device_cls, Signal):
                sub_device_1 = device_cls(SoftSignalBackend(signal_dtype))
                sub_device_2 = device_cls(SoftSignalBackend(signal_dtype))
                sub_device = DeviceVector({1: sub_device_1, 2: sub_device_2})
            else:
                if hasattr(device, device_name):
                    sub_device = getattr(device, device_name)
                else:
                    sub_device = DeviceVector(
                        {
                            1: device_cls(),
                            2: device_cls(),
                        }
                    )

                for sub_device_in_vector in sub_device.values():
                    _mock_common_blocks(sub_device_in_vector, stripped_type=device_cls)

            for value in sub_device.values():
                value.parent = sub_device
        else:
            if issubclass(device_cls, Signal):
                sub_device = device_cls(SoftSignalBackend(signal_dtype))
            else:
                sub_device = getattr(device, device_name, device_cls())
                _mock_common_blocks(sub_device, stripped_type=device_cls)

        setattr(device, device_name, sub_device)
        sub_device.parent = device


async def _get_pvi_entries(entry: _PVIEntry, timeout=DEFAULT_TIMEOUT):
    if not entry.pvi_pv or not entry.pvi_pv.endswith(":PVI"):
        raise RuntimeError("Top level entry must be a pvi table")

    pvi_table_signal_backend: PvaSignalBackend = PvaSignalBackend(
        None, entry.pvi_pv, entry.pvi_pv
    )
    await pvi_table_signal_backend.connect(
        timeout=timeout
    )  # create table signal backend

    pva_table = (await pvi_table_signal_backend.get_value())["pvi"]
    common_device_type_hints = (
        get_type_hints(entry.common_device_type) if entry.common_device_type else {}
    )

    for sub_name, pva_entries in pva_table.items():
        pvs = list(pva_entries.values())
        is_pvi_table = len(pvs) == 1 and pvs[0].endswith(":PVI")
        sub_name_split, sub_number_split = _strip_number_from_string(sub_name)
        is_device_vector, is_signal, signal_dtype, device_type = _parse_type(
            is_pvi_table,
            sub_number_split,
            common_device_type_hints.get(sub_name_split),
        )
        if is_signal:
            device = _pvi_mapping[frozenset(pva_entries.keys())](signal_dtype, *pvs)
        else:
            device = getattr(entry.device, sub_name, device_type())

        sub_entry = _PVIEntry(
            device=device, common_device_type=device_type, sub_entries={}
        )

        if is_device_vector:
            # If device vector then we store sub_name -> {sub_number -> sub_entry}
            # and aggregate into `DeviceVector` in `_set_device_attributes`
            sub_number_split = 1 if sub_number_split is None else sub_number_split
            if sub_name_split not in entry.sub_entries:
                entry.sub_entries[sub_name_split] = {}
            entry.sub_entries[sub_name_split][sub_number_split] = sub_entry  # type: ignore
        else:
            entry.sub_entries[sub_name] = sub_entry

        if is_pvi_table:
            sub_entry.pvi_pv = pvs[0]
            await _get_pvi_entries(sub_entry)

    if entry.common_device_type:
        _verify_common_blocks(entry, entry.common_device_type)


def _set_device_attributes(entry: _PVIEntry):
    for sub_name, sub_entry in entry.sub_entries.items():
        if isinstance(sub_entry, dict):
            sub_device = DeviceVector()  # type: ignore
            for key, device_vector_sub_entry in sub_entry.items():
                sub_device[key] = device_vector_sub_entry.device
                if device_vector_sub_entry.pvi_pv:
                    _set_device_attributes(device_vector_sub_entry)
                # Set the device vector entry to have the device vector as a parent
                device_vector_sub_entry.device.parent = sub_device  # type: ignore
        else:
            sub_device = sub_entry.device
            assert sub_device, f"Device of {sub_entry} is None"
            if sub_entry.pvi_pv:
                _set_device_attributes(sub_entry)

        sub_device.parent = entry.device
        setattr(entry.device, sub_name, sub_device)


async def fill_pvi_entries(
    device: Device, root_pv: str, timeout=DEFAULT_TIMEOUT, mock=False
):
    """
    Fills a ``device`` with signals from a the ``root_pvi:PVI`` table.

    If the device names match with parent devices of ``device`` then types are used.
    """
    if mock:
        # set up mock signals for the common annotations
        _mock_common_blocks(device)
    else:
        # check the pvi table for devices and fill the device with them
        root_entry = _PVIEntry(
            pvi_pv=root_pv,
            device=device,
            common_device_type=type(device),
            sub_entries={},
        )
        await _get_pvi_entries(root_entry, timeout=timeout)
        _set_device_attributes(root_entry)

    # We call set name now the parent field has been set in all of the
    # introspect-initialized devices. This will recursively set the names.
    device.set_name(device.name)


def create_children_from_annotations(
    device: Device,
    included_optional_fields: tuple[str, ...] = (),
    device_vectors: dict[str, int] | None = None,
):
    """For intializing blocks at __init__ of ``device``."""
    for name, device_type in get_type_hints(type(device)).items():
        if name in ("_name", "parent"):
            continue
        device_type, is_optional = _strip_union(device_type)
        if is_optional and name not in included_optional_fields:
            continue
        is_device_vector, device_type = _strip_device_vector(device_type)
        if (
            (is_device_vector and (not device_vectors or name not in device_vectors))
            or ((origin := get_origin(device_type)) and issubclass(origin, Signal))
            or (isclass(device_type) and issubclass(device_type, Signal))
        ):
            continue

        if is_device_vector:
            n_device_vector = DeviceVector(
                {i: device_type() for i in range(1, device_vectors[name] + 1)}  # type: ignore
            )
            setattr(device, name, n_device_vector)
            for sub_device in n_device_vector.values():
                create_children_from_annotations(
                    sub_device, device_vectors=device_vectors
                )
        else:
            sub_device = device_type()
            setattr(device, name, sub_device)
            create_children_from_annotations(sub_device, device_vectors=device_vectors)
