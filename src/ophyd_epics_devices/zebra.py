import asyncio
from enum import Enum

import numpy as np
import numpy.typing as npt
from bluesky import RunEngine
from ophyd.v2.core import Device, DeviceCollector, DeviceVector, SignalR, SignalRW
from ophyd.v2.epics import epics_signal_r, epics_signal_rw
from typing_extensions import TypeAlias


class Bool(Enum):
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


class UpdateRate(Enum):
    passive = "Passive"
    event = "Event"
    io_intr = "I/O Intr"
    s10 = "10 second"
    s5 = "5 second"
    s2 = "2 second"
    s1 = "1 second"
    s0_5 = ".5 second"
    s0_2 = ".2 second"
    s0_1 = ".1 second"


CapturePvType: TypeAlias = DeviceVector[SignalRW[Bool]]
ArrayOutPvType: TypeAlias = DeviceVector[SignalRW[npt.NDArray[np.float64]]]


#######################################################################################


class PcSetupCapture(Device):
    def __init__(self, prefix: str, name="") -> None:
        self.enc: CapturePvType = DeviceVector(
            {
                idx + 1: epics_signal_rw(Bool, f"{prefix}:B{key}")
                for idx, key in enumerate(range(4))
            }
        )
        self.sys = DeviceVector(
            {
                idx + 1: epics_signal_rw(Bool, f"{prefix}:B{key}")
                for idx, key in enumerate(range(4, 6))
            }
        )
        self.div = DeviceVector(
            {
                idx + 1: epics_signal_rw(Bool, f"{prefix}:B{key}")
                for idx, key in enumerate(range(6, 10))
            }
        )


class PcSetup(Device):
    def __init__(self, prefix: str) -> None:
        self.capture = PcSetupCapture(f"{prefix}:PC_BIT_CAP")
        self.posn_trig = epics_signal_rw(EncoderType, f"{prefix}:PC_ENC")
        self.posn_dir = epics_signal_rw(Direction, f"{prefix}:PC_DIR")
        self.time_units = epics_signal_rw(TimeUnits, f"{prefix}:PC_TSPRE")

    async def reset(self):
        await self.time_units.set(TimeUnits.ms)


class PcArm(Device):
    def __init__(self, prefix: str) -> None:
        self.trig_source = epics_signal_rw(ArmSelect, f"{prefix}:PC_ARM_SEL")
        self.arm = epics_signal_rw(float, f"{prefix}:PC_ARM")
        self.disarm = epics_signal_rw(float, f"{prefix}:PC_DISARM")
        self.arm_status = epics_signal_rw(float, f"{prefix}:PC_ARM_OUT")

    async def reset(self):
        await self.disarm.set(1)
        await self.trig_source.set(ArmSelect.soft)


class PcGate(Device):
    def __init__(self, prefix: str) -> None:
        self.trig_source = epics_signal_rw(GatePulseSelect, f"{prefix}:PC_GATE_SEL")
        self.gate_start = epics_signal_rw(float, f"{prefix}:PC_GATE_START")
        self.gate_width = epics_signal_rw(float, f"{prefix}:PC_GATE_WID")
        self.num_gates = epics_signal_rw(float, f"{prefix}:PC_GATE_NGATE")
        # self.gate_input = epics_signal_rw(int, "PC_GATE_INP")
        self.gate_step = epics_signal_rw(float, f"{prefix}:PC_GATE_STEP")
        self.gate_status = epics_signal_rw(float, f"{prefix}:PC_GATE_OUT")

    async def reset(self):
        await self.trig_source.set(GatePulseSelect.position)


class PcPulse(Device):
    def __init__(self, prefix: str) -> None:
        self.trig_source = epics_signal_rw(GatePulseSelect, f"{prefix}:PC_PULSE_SEL")
        self.pulse_start = epics_signal_rw(float, f"{prefix}:PC_PULSE_START")
        self.pulse_width = epics_signal_rw(float, f"{prefix}:PC_PULSE_WID")
        self.pulse_step = epics_signal_rw(float, f"{prefix}:PC_PULSE_STEP")
        self.capt_delay = epics_signal_rw(float, f"{prefix}:PC_PULSE_DLY")
        # self.pulse_input = epics_signal_rw(int, "PC_PULSE_INP")
        self.max_pulses = epics_signal_rw(float, f"{prefix}:PC_PULSE_MAX")
        self.pulse_status = epics_signal_rw(float, f"{prefix}:PC_PULSE_OUT")

    async def reset(self):
        await self.trig_source.set(GatePulseSelect.time)
        await self.pulse_start.set(0.0)


class ArrayOuts(Device):
    def __init__(self, prefix: str) -> None:
        def make_pv(suffix: str):
            # return epics_signal_rw(npt.NDArray[np.float64], f"{prefix}:PC_{suffix}")
            return epics_signal_rw(npt.NDArray[np.float64], f"{prefix}:PC_{suffix}")

        self.enc: ArrayOutPvType = DeviceVector(
            {
                idx + 1: make_pv(name)
                for idx, name in enumerate(["ENC1", "ENC2", "ENC3", "ENC4"])
            }
        )
        self.sys: ArrayOutPvType = DeviceVector(
            {idx + 1: make_pv(name) for idx, name in enumerate(["SYS1", "SYS2"])}
        )
        self.div: ArrayOutPvType = DeviceVector(
            {
                idx + 1: make_pv(name)
                for idx, name in enumerate(["DIV1", "DIV2", "DIV3", "DIV4"])
            }
        )


class PcDownload(Device):
    def __init__(self, prefix: str) -> None:
        self.array_outputs = ArrayOuts(prefix)
        self.captured = epics_signal_r(float, f"{prefix}:PC_NUM_CAP")
        self.downloaded = epics_signal_r(float, f"{prefix}:PC_NUM_DOWN")
        self.in_progress = epics_signal_r(float, f"{prefix}:ARRAY_ACQ")
        self.update_rate = epics_signal_rw(UpdateRate, f"{prefix}:ARRAY_UPDATE.SCAN")


class PositionCompare(Device):
    def __init__(self, prefix: str) -> None:
        self.setup = PcSetup(prefix)
        self.arm = PcArm(prefix)
        self.gate = PcGate(prefix)
        self.pulse = PcPulse(prefix)
        self.download = PcDownload(prefix)

    async def reset(self):
        await self.setup.reset()
        await self.arm.reset()
        await self.gate.reset()
        await self.pulse.reset()


#######################################################################################


class Input(Device):
    """Designed to represent the 'INP' fields in GATE tab for example."""

    def __init__(self, prefix: str):
        self.input = epics_signal_rw(float, f"{prefix}")
        self.source = epics_signal_rw(str, f"{prefix}:STR")
        self.status = epics_signal_rw(float, f"{prefix}:STA")


class LogicGatePanelInput(Input):
    def __init__(self, prefix: str, number: int):
        self.use = epics_signal_rw(Bool, f"{prefix}_ENA:B{number-1}")
        self.invert = epics_signal_rw(Bool, f"{prefix}_INV:B{number-1}")
        super().__init__(f"{prefix}_INP{number}")


class LogicGatePanel(Device):
    def __init__(self, prefix: str):
        self.inp = DeviceVector(
            {channel: LogicGatePanelInput(prefix, channel) for channel in range(1, 5)}
        )


#######################################################################################


class Gate(Device):
    def __init__(self, prefix: str, number: int):
        self.inp1 = Input(f"{prefix}:GATE{number}_INP1")
        self.inp1_trigger = epics_signal_rw(Bool, f"{prefix}:POLARITY:B{number-1}")
        self.inp2 = Input(f"{prefix}:GATE{number}_INP2")
        self.inp2_trigger = epics_signal_rw(Bool, f"{prefix}:POLARITY:B{number+3}")
        self.out = epics_signal_r(float, f"{prefix}:GATE{number}_OUT")


#######################################################################################


class Div(Device):
    triggers = {1: "8", 2: "9", 3: "A", 4: "B"}

    def __init__(self, prefix: str, number: int):
        self.input = Input(f"{prefix}:DIV{number}_INP")
        self.trigger = epics_signal_rw(
            Bool, f"{prefix}:POLARITY:B{self.triggers[number]}"
        )
        self.divisor = epics_signal_rw(float, f"{prefix}:DIV{number}_DIV")
        self.first_pulse = epics_signal_rw(Bool, f"{prefix}:DIV_FIRST:B{number-1}")
        self.outd = epics_signal_r(float, f"{prefix}:DIV{number}_OUTD")
        self.outn = epics_signal_r(float, f"{prefix}:DIV{number}_OUTN")


#######################################################################################


class Pulse(Device):
    triggers = {1: "C", 2: "D", 3: "E", 4: "F"}

    def __init__(self, prefix: str, number: int):
        self.input = Input(f"{prefix}:PULSE{number}_INP")
        self.trigger = epics_signal_rw(
            Bool, f"{prefix}:POLARITY:B{self.triggers[number]}"
        )
        self.delay_before = epics_signal_rw(float, f"{prefix}:PULSE{number}_DLY")
        self.pulse_width = epics_signal_rw(float, f"{prefix}:PULSE{number}_WID")
        self.time_units = epics_signal_rw(TimeUnits, f"{prefix}:PULSE{number}_PRE")

        self.trig_while_active = epics_signal_r(
            int, f"{prefix}:SYS_STATERR.B{number-1}"
        )
        self.output_pulse = epics_signal_r(float, f"{prefix}:PULSE{number}_OUT")


#######################################################################################


class EachMotor(Device):
    def __init__(self, prefix: str, number: int):
        self.title = epics_signal_r(str, f"{prefix}:M{number}")
        self.description = epics_signal_r(str, f"{prefix}:M{number}:DESC")
        self.motor_current_pos = epics_signal_r(float, f"{prefix}:M{number}:RBV")
        self.set_zebra_pos = epics_signal_rw(float, f"{prefix}:POS{number}_SET")
        self.copy_motor_pos_to_zebra = epics_signal_rw(
            int, f"{prefix}:M{number}:SETPOS.PROC"
        )


class Quad(Device):
    def __init__(self, prefix: str):
        self.step = Input(f"{prefix}:QUAD_STEP")
        self.dir = Input(f"{prefix}:QUAD_DIR")

        self.outa = epics_signal_r(float, f"{prefix}:QUAD_OUTA")
        self.outb = epics_signal_r(float, f"{prefix}:QUAD_OUTB")


class Enc(Device):
    def __init__(self, prefix: str):
        self.pos: DeviceVector[EachMotor] = DeviceVector(
            {number: EachMotor(prefix, number) for number in range(1, 5)}
        )
        self.quad = Quad(prefix)


#######################################################################################


class SysFrontPanelOutputs(Device):
    def __init__(self, prefix: str) -> None:
        self.out_ttl: DeviceVector[Input] = DeviceVector(
            {channel: Input(f"{prefix}:OUT{channel}_TTL") for channel in range(1, 5)}
        )
        self.out_nim: DeviceVector[Input] = DeviceVector(
            {channel: Input(f"{prefix}:OUT{channel}_NIM") for channel in [1, 2, 4]}
        )
        self.out_lvds: DeviceVector[Input] = DeviceVector(
            {channel: Input(f"{prefix}:OUT{channel}_LVDS") for channel in [1, 2, 3]}
        )
        self.out_oc: DeviceVector[Input] = DeviceVector({3: Input(f"{prefix}:OUT3_OC")})
        self.out_pecl: DeviceVector[Input] = DeviceVector(
            {4: Input(f"{prefix}:OUT4_PECL")}
        )


class SysRearPanelOutputs(Device):
    def __init__(self, prefix: str) -> None:
        self.out_enca: DeviceVector[Input] = DeviceVector(
            {channel: Input(f"{prefix}:OUT{channel}_ENCA") for channel in range(5, 9)}
        )
        self.out_encb: DeviceVector[Input] = DeviceVector(
            {channel: Input(f"{prefix}:OUT{channel}_ENCB") for channel in range(5, 9)}
        )
        self.out_encz: DeviceVector[Input] = DeviceVector(
            {channel: Input(f"{prefix}:OUT{channel}_ENCZ") for channel in range(5, 9)}
        )
        self.out_conn: DeviceVector[Input] = DeviceVector(
            {channel: Input(f"{prefix}:OUT{channel}_CONN") for channel in range(5, 9)}
        )


class SysWriteRegsToFileFlash(Device):
    def __init__(self, prefix: str):
        self.file = epics_signal_rw(str, f"{prefix}:CONFIG_FILE")
        self.store_to_file = epics_signal_rw(int, f"{prefix}:CONFIG_WRITE.PROC")
        self.restore_from_file = epics_signal_rw(int, f"{prefix}:CONFIG_READ.PROC")
        self.status = epics_signal_r(str, f"{prefix}:CONFIG_STATUS")
        self.store_to_flash = epics_signal_rw(int, f"{prefix}:STORE.PROC")
        self.restore_from_flash = epics_signal_rw(int, f"{prefix}:RESTORE.PROC")


class Sys(Device):
    def __init__(self, prefix: str):
        self.front_panel_outputs = SysFrontPanelOutputs(prefix)
        self.rear_panel_outputs = SysRearPanelOutputs(prefix)
        self.write_regs_to_file_or_flash = SysWriteRegsToFileFlash(prefix)

        self.version = epics_signal_r(float, f"{prefix}:SYS_VER")
        self.initial_poll_done = epics_signal_r(Bool, f"{prefix}:INITIAL_POLL_DONE")

    async def reset(self):
        return None


#######################################################################################


class SoftIn(Device):
    def __init__(self, prefix: str):
        self.input: DeviceVector[epics_signal_rw[Bool]] = DeviceVector(
            {
                number: epics_signal_rw(Bool, f"{prefix}:B{number-1}")
                for number in range(1, 5)
            }
        )


class Zebra(Device):
    def __init__(self, prefix: str):
        """
        Designed to pair well with the epics EDM screens for zebras.
        """
        self.pc = PositionCompare(prefix)

        self.and_gates: DeviceVector[LogicGatePanel] = DeviceVector(
            {
                channel: LogicGatePanel(f"{prefix}:AND{channel}")
                for channel in range(1, 5)
            }
        )
        self.or_gates: DeviceVector[LogicGatePanel] = DeviceVector(
            {
                channel: LogicGatePanel(f"{prefix}:OR{channel}")
                for channel in range(1, 5)
            }
        )
        self.gate: DeviceVector[Gate] = DeviceVector(
            {number: Gate(prefix, number) for number in range(1, 5)}
        )
        self.div: DeviceVector[Div] = DeviceVector(
            {number: Div(prefix, number) for number in range(1, 5)}
        )
        self.pulse: DeviceVector[Pulse] = DeviceVector(
            {number: Pulse(prefix, number) for number in range(1, 5)}
        )
        self.enc = Enc(prefix)
        self.sys = Sys(prefix)

        self.soft_in = SoftIn(f"{prefix}:SOFT_IN")
        self.block_state = epics_signal_rw(int, f"{prefix}:SYS_RESET.PROC")

    async def reset(self):
        await self.pc.reset()
        await self.sys.reset()


# RE = RunEngine()


# async def somefunc():
#     async with DeviceCollector():
#         # I think I'd like to do and_screen.and[1].inp[1]...
#         # so let's start with inp[1]...

#         # and_gates[1].inp[1]

#         # want to do, inp[1].use  for example...
#         setup_cap = Zebra("BL03S-EA-ZEBRA-01")
#     return setup_cap


# zebra = asyncio.run(somefunc())
# print("aha")
