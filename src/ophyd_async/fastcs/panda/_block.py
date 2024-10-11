from ophyd_async.core import (
    Device,
    DeviceBackend,
    DeviceVector,
    SignalR,
    SignalRW,
    StrictEnum,
    SubsetEnum,
)
from ophyd_async.epics.pvi import PviDeviceBackend

from ._table import DatasetTable, SeqTable


class FastCsDevice(Device):
    def __init__(
        self, uri: str = "", name: str = "", backend: DeviceBackend | None = None
    ) -> None:
        if backend is None:
            backend = PviDeviceBackend(type(self), uri + "PVI")
        super().__init__(name=name, backend=backend)


class DataBlock(FastCsDevice):
    # In future we may decide to make hdf_* optional
    hdf_directory: SignalRW[str]
    hdf_file_name: SignalRW[str]
    num_capture: SignalRW[int]
    num_captured: SignalR[int]
    create_directory: SignalRW[int]
    directory_exists: SignalR[bool]
    capture: SignalRW[bool]
    flush_period: SignalRW[float]
    datasets: SignalR[DatasetTable]


class PulseBlock(FastCsDevice):
    delay: SignalRW[float]
    width: SignalRW[float]


class PcompDirection(StrictEnum):
    positive = "Positive"
    negative = "Negative"
    either = "Either"


class BitMux(SubsetEnum):
    zero = "ZERO"
    one = "ONE"


class PcompBlock(FastCsDevice):
    active: SignalR[bool]
    dir: SignalRW[PcompDirection]
    enable: SignalRW[BitMux]
    pulses: SignalRW[int]
    start: SignalRW[int]
    step: SignalRW[int]
    width: SignalRW[int]


class TimeUnits(StrictEnum):
    min = "min"
    s = "s"
    ms = "ms"
    us = "us"


class SeqBlock(FastCsDevice):
    table: SignalRW[SeqTable]
    active: SignalR[bool]
    repeats: SignalRW[int]
    prescale: SignalRW[float]
    prescale_units: SignalRW[TimeUnits]
    enable: SignalRW[BitMux]


class PcapBlock(FastCsDevice):
    active: SignalR[bool]
    arm: SignalRW[bool]


class CommonPandaBlocks(Device):
    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcomp: DeviceVector[PcompBlock]
    pcap: PcapBlock
    data: DataBlock
