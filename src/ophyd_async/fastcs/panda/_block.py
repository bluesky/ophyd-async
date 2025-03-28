from ophyd_async.core import (
    Device,
    DeviceVector,
    SignalR,
    SignalRW,
    StrictEnum,
    SubsetEnum,
)

from ._table import DatasetTable, SeqTable


class PandaCaptureMode(StrictEnum):
    """Capture mode for the `DataBlock` on the PandA."""

    FIRST_N = "FIRST_N"
    LAST_N = "LAST_N"
    FOREVER = "FOREVER"


class DataBlock(Device):
    """Data block for the PandA. Used for writing data through the IOC."""

    # In future we may decide to make hdf_* optional
    hdf_directory: SignalRW[str]
    hdf_file_name: SignalRW[str]
    num_capture: SignalRW[int]
    num_captured: SignalR[int]
    create_directory: SignalRW[int]
    directory_exists: SignalR[bool]
    capture_mode: SignalRW[PandaCaptureMode]
    capture: SignalRW[bool]
    flush_period: SignalRW[float]
    datasets: SignalR[DatasetTable]


class PulseBlock(Device):
    """Used for configuring pulses in the PandA."""

    delay: SignalRW[float]
    pulses: SignalRW[int]
    step: SignalRW[float]
    width: SignalRW[float]


class PandaPcompDirection(StrictEnum):
    """Direction options for position compare in the PandA."""

    POSITIVE = "Positive"
    NEGATIVE = "Negative"
    EITHER = "Either"


class PandaBitMux(SubsetEnum):
    """Bit input with configurable delay in the PandA."""

    ZERO = "ZERO"
    ONE = "ONE"


class PcompBlock(Device):
    """Position compare block in the PandA."""

    active: SignalR[bool]
    dir: SignalRW[PandaPcompDirection]
    enable: SignalRW[PandaBitMux]
    pulses: SignalRW[int]
    start: SignalRW[int]
    step: SignalRW[int]
    width: SignalRW[int]


class PandaTimeUnits(StrictEnum):
    """Options for units of time in the PandA."""

    MIN = "min"
    S = "s"
    MS = "ms"
    US = "us"


class SeqBlock(Device):
    """Sequencer block in the PandA."""

    table: SignalRW[SeqTable]
    active: SignalR[bool]
    repeats: SignalRW[int]
    prescale: SignalRW[float]
    prescale_units: SignalRW[PandaTimeUnits]
    enable: SignalRW[PandaBitMux]


class PcapBlock(Device):
    """Position capture block in the PandA."""

    active: SignalR[bool]
    arm: SignalRW[bool]


class CommonPandaBlocks(Device):
    """Pandablocks device with blocks which are common and required on introspection."""

    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcomp: DeviceVector[PcompBlock]
    pcap: PcapBlock
    data: DataBlock
