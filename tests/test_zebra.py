from typing import Any

import pytest
from ophyd.v2.core import DeviceCollector

from ophyd_epics_devices.zebra import (
    ArmSelect,
    Bool,
    Direction,
    EncoderType,
    GatePulseSelect,
    TimeUnits,
    Zebra,
)

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_WHILE = 0.001


@pytest.fixture
async def sim_zebra():
    async with DeviceCollector(sim=True):
        sim_zebra = Zebra("BLxxI-MO-TABLE-01")
        # Signals connected here

    assert sim_zebra.name == "sim_zebra"
    await sim_zebra.reset()

    yield sim_zebra


@pytest.mark.parametrize(
    "value",
    [(Direction.positive), (Direction.negative)],
)
async def test_setting_direction(value: Any, sim_zebra: Zebra) -> None:
    await sim_zebra.pc.setup.posn_dir.set(value)
    assert await sim_zebra.pc.setup.posn_dir.get_value() == value


@pytest.mark.parametrize(
    "value",
    [TimeUnits.ms, TimeUnits.s, TimeUnits.s10],
)
async def test_setting_time_units(value: Any, sim_zebra: Zebra) -> None:
    await sim_zebra.pc.setup.time_units.set(value)
    assert await sim_zebra.pc.setup.time_units.get_value() == value


@pytest.mark.parametrize(
    "value",
    [GatePulseSelect.time, GatePulseSelect.external, GatePulseSelect.position],
)
async def test_setting_pulse_and_gate_selection(value: Any, sim_zebra: Zebra) -> None:
    await sim_zebra.pc.pulse.trig_source.set(value)
    assert await sim_zebra.pc.pulse.trig_source.get_value() == value

    await sim_zebra.pc.gate.trig_source.set(value)
    assert await sim_zebra.pc.gate.trig_source.get_value() == value


@pytest.mark.parametrize(
    "value",
    [ArmSelect.external, ArmSelect.soft],
)
async def test_setting_arm_selection(value: Any, sim_zebra: Zebra) -> None:
    await sim_zebra.pc.arm.trig_source.set(value)
    assert await sim_zebra.pc.arm.trig_source.get_value() == value


@pytest.mark.parametrize(
    "value",
    [EncoderType.enc1, EncoderType.enc2, EncoderType.enc3, EncoderType.enc4],
)
async def test_setting_gate_trigger(value: Any, sim_zebra: Zebra) -> None:
    await sim_zebra.pc.gate.trig_source.set(value)
    assert await sim_zebra.pc.gate.trig_source.get_value() == value


@pytest.mark.parametrize(
    "value",
    [Bool.yes, Bool.no],
)
async def test_setting_capture_pvs(value: Any, sim_zebra: Zebra) -> None:
    await sim_zebra.pc.setup.capture.div[1].set(value)
    assert await sim_zebra.pc.setup.capture.div[1].get_value() == value

    await sim_zebra.pc.setup.capture.div[2].set(value)
    assert await sim_zebra.pc.setup.capture.div[2].get_value() == value

    await sim_zebra.pc.setup.capture.div[3].set(value)
    assert await sim_zebra.pc.setup.capture.div[3].get_value() == value

    await sim_zebra.pc.setup.capture.div[4].set(value)
    assert await sim_zebra.pc.setup.capture.div[4].get_value() == value

    await sim_zebra.pc.setup.capture.sys[1].set(value)
    assert await sim_zebra.pc.setup.capture.sys[1].get_value() == value

    await sim_zebra.pc.setup.capture.sys[2].set(value)
    assert await sim_zebra.pc.setup.capture.sys[2].get_value() == value

    await sim_zebra.pc.setup.capture.enc[1].set(value)
    assert await sim_zebra.pc.setup.capture.enc[1].get_value() == value

    await sim_zebra.pc.setup.capture.enc[2].set(value)
    assert await sim_zebra.pc.setup.capture.enc[2].get_value() == value

    await sim_zebra.pc.setup.capture.enc[3].set(value)
    assert await sim_zebra.pc.setup.capture.enc[3].get_value() == value

    await sim_zebra.pc.setup.capture.enc[4].set(value)
    assert await sim_zebra.pc.setup.capture.enc[4].get_value() == value
