from __future__ import annotations

from enum import Enum

from ophyd_async.core import Device, DeviceVector, SignalR, SignalRW, SubsetEnum

from ._table import DatasetTable, SeqTable


class DataBlock(Device):
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


class PulseBlock(Device):
    delay: SignalRW[float]
    width: SignalRW[float]


class PcompDirectionOptions(str, Enum):
    positive = "Positive"
    negative = "Negative"
    either = "Either"


EnableDisableOptions = SubsetEnum["ZERO", "ONE"]


class PcompBlock(Device):
    active: SignalR[bool]
    dir: SignalRW[PcompDirectionOptions]
    enable: SignalRW[EnableDisableOptions]
    pulses: SignalRW[int]
    start: SignalRW[int]
    step: SignalRW[int]
    width: SignalRW[int]


class TimeUnits(str, Enum):
    min = "min"
    s = "s"
    ms = "ms"
    us = "us"


class SeqBlock(Device):
    table: SignalRW[SeqTable]
    active: SignalRW[bool]
    repeats: SignalRW[int]
    prescale: SignalRW[float]
    prescale_units: SignalRW[TimeUnits]
    enable: SignalRW[EnableDisableOptions]


class PcapBlock(Device):
    active: SignalR[bool]
    arm: SignalRW[bool]


class CommonPandaBlocks(Device):
    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcomp: DeviceVector[PcompBlock]
    pcap: PcapBlock
    data: DataBlock
