from ophyd_async.core import (
    Device,
    DeviceVector,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
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
    """Data block for the PandA. Used for writing data through the IOC.

    This mirrors the interface provided by
    https://github.com/PandABlocks/fastcs-PandABlocks/blob/main/src/fastcs_pandablocks/panda/blocks/data.py
    """

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


class PandaPcompDirection(StrictEnum):
    """Direction options for position compare in the PandA."""

    POSITIVE = "Positive"
    NEGATIVE = "Negative"
    EITHER = "Either"


class PandaBitMux(SubsetEnum):
    """Bit input with configurable delay in the PandA."""

    ZERO = "ZERO"
    ONE = "ONE"


class PandaPosMux(SubsetEnum):
    """Pos input in the PandA."""

    ZERO = "ZERO"


class PulseBlock(Device):
    """Used for configuring pulses in the PandA.

    This mirrors the interface provided by
    PandABlocks-FPGA/modules/pulse/pulse.block.ini
    """

    enable: SignalRW[PandaBitMux]
    delay: SignalRW[float]
    pulses: SignalRW[int]
    step: SignalRW[float]
    width: SignalRW[float]


class PcompBlock(Device):
    """Position compare block in the PandA.

    This mirrors the interface provided by
    PandABlocks-FPGA/modules/pcomp/pcomp.block.ini
    """

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


class PandaSeqWrite(StrictEnum):
    """Options for what the next write command will do to the table."""

    REPLACE = "Replace"
    APPEND = "Append"
    APPEND_LAST = "Append Last"


class SeqBlock(Device):
    """Sequencer block in the PandA.

    This mirrors the interface provided by PandABlocks-FPGA/modules/seq/seq.block.ini
    """

    table: SignalRW[SeqTable]
    active: SignalR[bool]
    repeats: SignalRW[int]
    prescale: SignalRW[float]
    prescale_units: SignalRW[PandaTimeUnits]
    enable: SignalRW[PandaBitMux]
    posa: SignalRW[PandaPosMux]
    table_clear: SignalX | None
    table_next_write: SignalW[PandaSeqWrite] | None
    table_queued_lines: SignalR[int] | None


class PcapBlock(Device):
    """Position capture block in the PandA.

    This mirrors the interface provided by PandABlocks-FPGA/modules/pcap/pcap.block.ini
    """

    active: SignalR[bool]
    arm: SignalRW[bool]


class InencBlock(Device):
    """In encoder block in the PandA.

    This mirrors the interface provided by
    PandABlocks-FPGA/modules/inenc/inenc.block.ini
    """

    val_scale: SignalRW[float]
    val_offset: SignalRW[float]


class CommonPandaBlocks(Device):
    """Pandablocks device with blocks which are common and required on introspection."""

    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcomp: DeviceVector[PcompBlock]
    pcap: PcapBlock
    data: DataBlock
