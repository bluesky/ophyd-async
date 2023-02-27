from enum import Enum
from typing import List, Type

import numpy as np
import numpy.typing as npt

from ophyd.v2.core import StandardReadable, T
from ophyd.v2.epics import EpicsSignalR, EpicsSignalRW
from functools import partialmethod


def zebra_rw(datatype: Type[T], suffix: str) -> EpicsSignalRW[T]:
    return EpicsSignalRW(datatype, suffix)


def zebra_r(datatype: Type[T], suffix: str) -> EpicsSignalR[T]:
    return EpicsSignalR(datatype, suffix)


class Active(Enum):
    no = "No"
    yes = "Yes"


class GatePulseSelect(Enum):
    time = "Time"
    position = "Position"
    external = "External"


class ArmSelect(Enum):
    soft = "Soft"
    external = "External"


class Direction(Enum):
    positive = "Positive"
    negative = "Negative"


class EncoderType(Enum):
    enc1 = "Enc1"
    enc2 = "Enc2"
    enc3 = "Enc3"
    enc4 = "Enc4"
    enc1_4av = "Enc1-4Av"


class TimeUnits(Enum):
    ms = "ms"
    s = "s"
    s10 = "10s"


class Capture(StandardReadable):
    def __init__(self, prefix: str, name="") -> None:
        self.enc1 = zebra_rw(Active, "B0")
        self.enc2 = zebra_rw(Active, "B1")
        self.enc3 = zebra_rw(Active, "B2")
        self.enc4 = zebra_rw(Active, "B3")
        self.sys1 = zebra_rw(Active, "B4")
        self.sys2 = zebra_rw(Active, "B5")
        self.div1 = zebra_rw(Active, "B6")
        self.div2 = zebra_rw(Active, "B7")
        self.div3 = zebra_rw(Active, "B8")
        self.div4 = zebra_rw(Active, "B9")
        super().__init__(prefix, name)


class ArrayOuts(StandardReadable):
    def __init__(self, prefix: str, name="") -> None:
        def make_pv(suffix: str, common_prefix: str = "PC_"):
            return zebra_rw(npt.NDArray[np.float64], common_prefix + suffix)

        self.enc1 = make_pv("ENC1")
        self.enc2 = make_pv("ENC2")
        self.enc3 = make_pv("ENC3")
        self.enc4 = make_pv("ENC4")
        self.sys1 = make_pv("SYS1")
        self.sys2 = make_pv("SYS2")
        self.div1 = make_pv("DIV1")
        self.div2 = make_pv("DIV2")
        self.div3 = make_pv("DIV3")
        self.div4 = make_pv("DIV4")
        super().__init__(prefix, name)


class ZebraOutputPanel(StandardReadable):
    def __init__(self, prefix: str, name="") -> None:
        self.pulse_1_input = zebra_rw(int, "PULSE1_INP")

        self.out_1 = zebra_rw(int, "OUT1_TTL")
        self.out_2 = zebra_rw(int, "OUT2_TTL")
        self.out_3 = zebra_rw(int, "OUT3_TTL")
        self.out_4 = zebra_rw(int, "OUT4_TTL")
        super().__init__(prefix, name)

    @property
    def out_pvs(self) -> List[EpicsSignalRW[int]]:
        """A list of all the output TTL PVs. Note that as the PVs are 1 indexed
        `out_pvs[0]` is `None`. NOTE: technically typing for this is wrong.
        i.e. first index is not an EpicsSignal...
        """
        return [None, self.out_1, self.out_2, self.out_3, self.out_4]

    async def reset(self):
        ...


class GateControl(StandardReadable):
    def __init__(self, prefix: str, pv_prefix: str, name=""):
        self.enable = zebra_rw(int, "_ENA")
        self.source_1 = zebra_rw(int, "_INP1")
        self.source_2 = zebra_rw(int, "_INP2")
        self.source_3 = zebra_rw(int, "_INP3")
        self.source_4 = zebra_rw(int, "_INP4")
        self.invert = zebra_rw(int, "_INV")
        super().__init__(prefix, name)

    @property
    def sources(self):
        return [self.source_1, self.source_2, self.source_3, self.source_4]


def boolean_array_to_integer(values: List[bool]) -> int:
    """Converts a boolean array to integer by interpretting it in binary with LSB 0 bit
    numbering.
    Args:
        values (List[bool]): The list of booleans to convert.
    Returns:
        int: The interpretted integer.
    """
    return sum(v << i for i, v in enumerate(values))


class GateType(Enum):
    AND = "AND"
    OR = "OR"


class LogicGateConfiguration:
    NUMBER_OF_INPUTS = 4

    def __init__(self, input_source: int, invert: bool = False) -> None:
        self.sources: List[int] = []
        self.invert: List[bool] = []
        self.add_input(input_source, invert)

    def add_input(
        self, input_source: int, invert: bool = False
    ) -> "LogicGateConfiguration":
        """Add an input to the gate. This will throw an assertion error if more than 4
        inputs are added to the Zebra.
        Args:
            input_source (int): The source for the input (must be between 0 and 63).
            invert (bool, optional): Whether the input should be inverted. Default
                False.
        Returns:
            LogicGateConfiguration: A description of the gate configuration.
        """
        assert len(self.sources) < 4
        assert 0 <= input_source <= 63
        self.sources.append(input_source)
        self.invert.append(invert)
        return self

    def __str__(self) -> str:
        input_strings = []
        for input, (source, invert) in enumerate(zip(self.sources, self.invert)):
            input_strings.append(f"INP{input+1}={'!' if invert else ''}{source}")

        return ", ".join(input_strings)


class LogicGateConfigurer(StandardReadable):
    DEFAULT_SOURCE_IF_GATE_NOT_USED = 0

    def __init__(self, prefix: str, name=""):
        self.and_gate_1 = GateControl(prefix, "AND1", name)
        self.and_gate_2 = GateControl(prefix, "AND2", name)
        self.and_gate_3 = GateControl(prefix, "AND3", name)
        self.and_gate_4 = GateControl(prefix, "AND4", name)

        self.or_gate_1 = GateControl(prefix, "OR1", name)
        self.or_gate_2 = GateControl(prefix, "OR2", name)
        self.or_gate_3 = GateControl(prefix, "OR3", name)
        self.or_gate_4 = GateControl(prefix, "OR4", name)

        self.all_gates = {
            GateType.AND: [
                self.and_gate_1,
                self.and_gate_2,
                self.and_gate_3,
                self.and_gate_4,
            ],
            GateType.OR: [
                self.or_gate_1,
                self.or_gate_2,
                self.or_gate_3,
                self.or_gate_4,
            ],
        }

        super().__init__(prefix, name)

    async def apply_logic_gate_config(
        self, type: GateType, gate_number: int, config: LogicGateConfiguration
    ):
        """Uses the specified `LogicGateConfiguration` to configure a gate on the Zebra.
        Args:
            type (GateType): The type of gate e.g. AND/OR
            gate_number (int): Which gate to configure.
            config (LogicGateConfiguration): A configuration for the gate.
        """
        gate: GateControl = self.all_gates[type][gate_number - 1]

        await gate.enable.set(boolean_array_to_integer([True] * len(config.sources)))

        # Input Source
        for source_number, source_pv in enumerate(gate.sources):
            try:
                await source_pv.set(config.sources[source_number])
            except IndexError:
                await source_pv.set(self.DEFAULT_SOURCE_IF_GATE_NOT_USED)

        # Invert
        await gate.invert.set(boolean_array_to_integer(config.invert))

    async def reset(self):
        ...

    apply_and_gate_config = partialmethod(apply_logic_gate_config, GateType.AND)
    apply_or_gate_config = partialmethod(apply_logic_gate_config, GateType.OR)


class PositionCompare(StandardReadable):
    def __init__(self, prefix: str, name="") -> None:
        self.capture = Capture("PC_BIT_CAP:")
        self.array_outputs = ArrayOuts("")

        self.direction = zebra_rw(Direction, "PC_DIR")
        self.time_units = zebra_rw(TimeUnits, "PC_TSPRE")
        self.time = zebra_rw(float, "PC_TIME")

        self.pulse_sel = zebra_rw(GatePulseSelect, "PC_PULSE_SEL")
        self.pulse_input = zebra_rw(int, "PC_PULSE_INP")
        self.pulse_start = zebra_rw(float, "PC_PULSE_START")
        self.pulse_width = zebra_rw(float, "PC_PULSE_WID")
        self.pulse_delay = zebra_rw(int, "PC_PULSE_DLY")
        self.pulse_step = zebra_rw(int, "PC_PULSE_STEP")
        self.pulse_max = zebra_rw(int, "PC_PULSE_MAX")

        self.num_gates = zebra_rw(int, "PC_GATE_NGATE")
        self.gate_trigger = zebra_rw(EncoderType, "PC_ENC")
        self.gate_sel = zebra_rw(GatePulseSelect, "PC_GATE_SEL")
        self.gate_input = zebra_rw(int, "PC_GATE_INP")
        self.gate_start = zebra_rw(float, "PC_GATE_START")
        self.gate_width = zebra_rw(float, "PC_GATE_WID")
        self.gate_step = zebra_rw(int, "PC_GATE_STEP")

        self.arm_sel = zebra_rw(ArmSelect, "PC_ARM_SEL")
        self.arm = zebra_rw(int, "PC_ARM")
        self.disarm = zebra_rw(int, "PC_DISARM")
        self.armed = zebra_rw(int, "PC_ARM_OUT")

        self.captured = zebra_r(int, "PC_NUM_CAP")
        self.downloaded = zebra_r(int, "PC_NUM_DOWN")
        super().__init__(prefix, name)

        # want a mapping between the encoder, capture and array pvs?

    async def reset(self):
        await self.time_units.set(TimeUnits.ms)
        await self.pulse_sel.set(GatePulseSelect.time)
        await self.gate_sel.set(GatePulseSelect.position)
        await self.disarm.set(1)
        await self.arm_sel.set(ArmSelect.soft)
        await self.pulse_start.set(0.0)


class System(StandardReadable):
    def __init__(self, prefix: str, name: str = ""):
        self.sys_reset = zebra_rw(int, "SYS_RESET.PROC")
        self.config_file = zebra_rw(str, "CONFIG_FILE")
        self.config_read = zebra_rw(int, "CONFIG_READ.PROC")
        self.config_status = zebra_rw(str, "CONFIG_STATUS")

        super().__init__(prefix, name)

    async def reset(self):
        await self.sys_reset.set(1)


class Zebra(StandardReadable):
    def __init__(self, prefix: str, name: str = ""):
        self.pc = PositionCompare("")
        self.output = ZebraOutputPanel("")
        self.logic_gates = LogicGateConfigurer("")
        self.sys = System("")

        super().__init__(prefix, name)

    async def reset(self):
        await self.pc.reset()
        await self.output.reset()
        await self.logic_gates.reset()
        await self.sys.reset()
