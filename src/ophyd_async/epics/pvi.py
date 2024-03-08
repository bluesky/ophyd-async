import re
from dataclasses import dataclass
from typing import (
    Callable,
    Dict,
    FrozenSet,
    List,
    Literal,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from ophyd_async.core import Device, DeviceVector, SimSignalBackend
from ophyd_async.core.signal import Signal
from ophyd_async.core.utils import DEFAULT_TIMEOUT
from ophyd_async.epics._backend._p4p import PvaSignalBackend
from ophyd_async.epics.signal.signal import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_w,
    epics_signal_x,
)

T = TypeVar("T")
Access = FrozenSet[
    Literal["r"] | Literal["w"] | Literal["rw"] | Literal["x"] | Literal["d"]
]


def _strip_number_from_string(string: str) -> Tuple[str, Optional[int]]:
    match = re.match(r"(.*?)(\d*)$", string)
    assert match

    name = match.group(1)
    number = match.group(2) or None
    if number:
        number = int(number)
    return name, number


def _strip_union(field: Union[Union[T], T]) -> T:
    if get_origin(field) is Union:
        args = get_args(field)
        for arg in args:
            if arg is not type(None):
                return arg

    return field


def _strip_device_vector(field: Union[Type[Device]]) -> Tuple[bool, Type[Device]]:
    if get_origin(field) is DeviceVector:
        return True, get_args(field)[0]
    return False, field


def _get_common_device_typeypes(name: str, common_device: Type[Device]) -> Type[Device]:
    return get_type_hints(common_device).get(name, {})


@dataclass
class PVIEntry:
    """
    A dataclass to represent a single entry in the PVI table.
    This could either be a signal or a sub-table.
    """

    name: Optional[str]
    access: Access
    values: List[str]
    # `sub_entries` if the signal is a PVI table
    # If a sub device is a device vector then it will be represented by a further dict
    sub_entries: Optional[Dict[str, Union[Dict[int, "PVIEntry"], "PVIEntry"]]] = None
    device: Optional[Device] = None

    @property
    def is_pvi_table(self) -> bool:
        return len(self.values) == 1 and self.values[0].endswith(":PVI")


def _verify_common_blocks(entry: PVIEntry, common_device: Type[Device]):
    common_sub_devices = get_type_hints(common_device)
    for sub_name, sub_device in common_sub_devices.items():
        if sub_name in ("_name", "parent"):
            continue
        assert entry.sub_entries
        if sub_name not in entry.sub_entries:
            raise RuntimeError(
                f"sub device `{sub_name}:{type(sub_device)}` was not provided by pvi"
            )


_pvi_mapping: Dict[FrozenSet[str], Callable[..., Signal]] = {
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


class PVIParser:
    def __init__(
        self,
        root_pv: str,
        timeout=DEFAULT_TIMEOUT,
    ):
        self.root_entry = PVIEntry(
            name=None, access=frozenset({"d"}), values=[root_pv], sub_entries={}
        )
        self.timeout = timeout

    async def get_pvi_entries(self, entry: Optional[PVIEntry] = None):
        """Creates signals from a top level PVI table"""
        if not entry:
            entry = self.root_entry

        if not entry.is_pvi_table:
            raise RuntimeError(f"{entry.values[0]} is not a PVI table")

        pvi_table_signal_backend: PvaSignalBackend = PvaSignalBackend(
            None, entry.values[0], entry.values[0]
        )
        await pvi_table_signal_backend.connect(
            timeout=self.timeout
        )  # create table signal backend

        pva_table = await pvi_table_signal_backend.get_value()
        entry.sub_entries = {}

        for sub_name, pva_entries in pva_table["pvi"].items():
            sub_entry = PVIEntry(
                name=sub_name,
                access=frozenset(pva_entries.keys()),
                values=list(pva_entries.values()),
                sub_entries={},
            )

            if sub_entry.is_pvi_table:
                sub_split_name, sub_split_number = _strip_number_from_string(sub_name)
                if not sub_split_number:
                    sub_split_number = 1

                await self.get_pvi_entries(entry=sub_entry)
                entry.sub_entries[sub_split_name] = entry.sub_entries.get(
                    sub_split_name, {}
                )
                entry.sub_entries[sub_split_name][
                    sub_split_number
                ] = sub_entry  # type: ignore
            else:
                entry.sub_entries[sub_name] = sub_entry

    def initialize_device(
        self,
        entry: PVIEntry,
        common_device_type: Optional[Type[Device]] = None,
    ):
        """Recursively iterates through the tree of PVI entries and creates devices.

        Args:
            entry: The current PVI entry
            common_device_type: The common device type for the current entry
                if it exists, else None
        Returns:
            The initialised device containing it's signals, all typed.
        """

        assert entry.sub_entries
        for sub_name, sub_entries in entry.sub_entries.items():
            sub_common_device_type = None
            if common_device_type:
                sub_common_device_type = _get_common_device_typeypes(
                    sub_name, common_device_type
                )
                sub_common_device_type = _strip_union(sub_common_device_type)
                pre_defined_device_vector, sub_common_device_type = (
                    _strip_device_vector(sub_common_device_type)
                )

            if isinstance(sub_entries, dict) and (
                len(sub_entries) != 1 or pre_defined_device_vector
            ):
                sub_device: Union[DeviceVector, Device] = DeviceVector()

                for sub_split_number, sub_entry in sub_entries.items():
                    if sub_entry.is_pvi_table:  # If the entry isn't a signal
                        if (
                            sub_common_device_type
                            and get_origin(sub_common_device_type) == DeviceVector
                        ):
                            sub_common_device_type = get_args(sub_common_device_type)[0]
                        sub_entry.device = (
                            sub_common_device_type()
                            if sub_common_device_type
                            else Device()
                        )
                        self.initialize_device(
                            sub_entry, common_device_type=sub_common_device_type
                        )
                    else:  # entry is a signal
                        signal_type = (
                            get_args(sub_common_device_type)[0]
                            if sub_common_device_type
                            else None
                        )
                        sub_entry.device = _pvi_mapping[sub_entry.access](
                            signal_type, *sub_entry.values
                        )
                    assert isinstance(sub_device, DeviceVector)
                    sub_device[sub_split_number] = sub_entry.device
            else:
                if isinstance(sub_entries, dict):
                    sub_device = (
                        sub_common_device_type() if sub_common_device_type else Device()
                    )
                    assert list(sub_entries) == [1]
                    sub_entries[1].device = sub_device
                    self.initialize_device(
                        sub_entries[1], common_device_type=sub_common_device_type
                    )
                else:  # entry is a signal
                    signal_type = (
                        get_args(sub_common_device_type)[0]
                        if sub_common_device_type
                        else None
                    )
                    sub_device = _pvi_mapping[sub_entries.access](
                        signal_type, *sub_entries.values
                    )

            setattr(entry.device, sub_name, sub_device)

        # Check that all predefined devices are present
        if common_device_type:
            _verify_common_blocks(entry, common_device_type)


def _sim_common_blocks(device: Device, stripped_type: Optional[Type] = None):

    device_t = stripped_type or type(device)
    for sub_name, sub_device_t in get_type_hints(device_t).items():
        if sub_name in ("_name", "parent"):
            continue

        # we'll take the first type in the union which isn't NoneType
        sub_device_t = _strip_union(sub_device_t)
        is_device_vector, sub_device_t = _strip_device_vector(sub_device_t)
        is_signal = (origin := get_origin(sub_device_t)) and issubclass(origin, Signal)

        if is_signal:
            signal_type = get_args(sub_device_t)[0]
            print("DEBUG: SIGNAL TYPE", signal_type)
            print("DEBUG: SIGNAL ARGS", get_args(sub_device_t))
            sub_device = sub_device_t(SimSignalBackend(signal_type, sub_name))
        elif is_device_vector:
            sub_device = DeviceVector(
                {
                    1: sub_device_t(name=f"{device.name}-{sub_name}-1"),
                    2: sub_device_t(name=f"{device.name}-{sub_name}-2"),
                }
            )
        else:
            sub_device = sub_device_t(name=f"{device.name}-{sub_name}")

        if not is_signal:
            if is_device_vector:
                for sub_device_in_vector in sub_device.values():
                    _sim_common_blocks(sub_device_in_vector, stripped_type=sub_device_t)
            else:
                _sim_common_blocks(sub_device, stripped_type=sub_device_t)

        setattr(device, sub_name, sub_device)


async def fill_pvi_entries(
    device: Device, root_pv: str, timeout=DEFAULT_TIMEOUT, sim=True
):
    """
    Fills a `device` with signals from a the `root_pvi:PVI` table.

    If the device names match with parent devices of `device` then types are used.
    """
    if not sim:
        # check the pvi table for devices and fill the device with them
        parser = PVIParser(root_pv, timeout=timeout)
        await parser.get_pvi_entries()
        parser.root_entry.device = device
        parser.initialize_device(parser.root_entry, common_device_type=type(device))

    if sim:
        # set up sim signals for the common annotations
        _sim_common_blocks(device)
