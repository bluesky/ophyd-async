from __future__ import annotations

from enum import Enum

from ophyd_async.core import Device, DeviceVector, SignalR, SignalRW

from ._table import SeqTable


class DataBlock(Device):
    # In future we may decide to make hdf_* optional
    hdf_directory: SignalRW[str]
    hdf_file_name: SignalRW[str]
    num_capture: SignalRW[int]
    num_captured: SignalR[int]
    capture: SignalRW[bool]
    flush_period: SignalRW[float]


class PulseBlock(Device):
    delay: SignalRW[float]
    width: SignalRW[float]


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
    pcap: PcapBlock
    data: DataBlock
