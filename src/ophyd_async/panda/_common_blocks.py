from __future__ import annotations

from enum import Enum

from ophyd_async.core import Device, DeviceVector, SignalR, SignalRW
from ophyd_async.panda._table import DatasetTable, SeqTable


class DataBlock(Device):
    # In future we may decide to make hdf_* optional
    hdf_directory: SignalRW[str]
    hdf_file_name: SignalRW[str]
    num_capture: SignalRW[int]
    num_captured: SignalR[int]
    capture: SignalRW[bool]
    flush_period: SignalRW[float]
    datasets: SignalR[DatasetTable]


class PulseBlock(Device):
    delay: SignalRW[float]
    width: SignalRW[float]


class PcompDirectoryOptions(str, Enum):
    positive = "Positive"
    negative = "Negative"
    either = "Either"


class PcompRelativeOptions(str, Enum):
    absolute = "Absolute"
    relative = "Relative"


class PcompBlock(Device):
    active: SignalR[bool]
    dir: SignalRW[PcompDirectoryOptions]
    enable: SignalRW[str]
    enable_delay: SignalRW[int]
    health: SignalR[str]
    inp: SignalRW[str]
    label: SignalRW[str]
    out: SignalRW[bool]
    pre_start: SignalRW[int]
    produced: SignalR[int]
    pulses: SignalRW[int]
    relative: SignalRW[PcompRelativeOptions]
    start: SignalRW[int]
    state: SignalR[str]
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
    enable: SignalRW[str]


class PcapBlock(Device):
    active: SignalR[bool]
    arm: SignalRW[bool]


class CommonPandaBlocks(Device):
    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcomp: DeviceVector[PcompBlock]
    pcap: PcapBlock
    data: DataBlock
