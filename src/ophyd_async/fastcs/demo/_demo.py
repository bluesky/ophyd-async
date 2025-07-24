import asyncio
import enum
import time
from dataclasses import dataclass
from math import cos, floor, sin

from fastcs.attributes import (
    AttrHandlerR,
    AttrR,
    AttrRW,
    SimpleAttrHandler,
)
from fastcs.controller import Controller, SubController
from fastcs.datatypes import Bool, Enum, Float, Int
from fastcs.wrappers import command

from ophyd_async.epics.demo import EnergyMode

# FastCS uses enum labels as the string value, value being an arbitrary index
_EnergyMode = enum.Enum(
    "_EnergyMode", {e.value: idx for idx, e in enumerate(EnergyMode)}
)


@dataclass
class ReadbackUpdater(AttrHandlerR):
    # implementing logic from src/ophyd_async/epics/demo/motor.db
    update_period: float | None = 0.1

    async def initialise(self, controller: "DemoMotorController"):
        self._setpoint = controller.setpoint
        self._velocity = controller.velocity

    async def update(self, attr: AttrR) -> None:
        readback = attr.get()  # A
        setpoint = self._setpoint.get()  # B
        velocity = self._velocity.get()
        velocity_div = velocity * self.update_period  # C
        if abs(setpoint - readback) < velocity_div:
            new_readback = setpoint
        elif setpoint > readback:
            new_readback = readback + velocity_div
        else:  # setpoint <= readback
            new_readback = readback - velocity_div
        new_readback = max(0.0, new_readback)  # recreates DRVL logic
        await attr.set(new_readback)


class DemoMotorController(SubController):
    readback = AttrR(Float(units="mm", prec=3), handler=ReadbackUpdater())
    # SimpleHander provides a trivial put method
    setpoint = AttrRW(
        Float(units="mm", prec=3), handler=SimpleAttrHandler(), initial_value=0.0
    )
    velocity = (
        AttrRW(  # maybe this should be an AttrR since we don't want to have an _RBV?
            Float(units="mm/s", prec=3), handler=SimpleAttrHandler(), initial_value=1.0
        )
    )

    @command()
    async def stop(self):
        readback = self.readback.get()
        await self.setpoint.set(readback)


class DemoController(Controller):  # top controller
    async def initialise(self):
        stage_controller = SubController()  # only exists to own X and Y
        self.register_sub_controller("STAGE", stage_controller)
        stage_controller.register_sub_controller("X", DemoMotorController())
        stage_controller.register_sub_controller("Y", DemoMotorController())
        det_controller = DemoPointDetectorDetController(3)  # TODO make 3 an init arg
        self.register_sub_controller("DET", det_controller)
        await det_controller.initialise(self)


@dataclass
class ValueHandler(AttrHandlerR):
    # reimplement point_detector_channel.db

    async def initialise(self, controller: "DemoPointDetectorChannelController"):
        det_controller = controller.top_controller.get_sub_controllers()["DET"]
        stage_controller = controller.top_controller.get_sub_controllers()["STAGE"]
        x_controller = stage_controller.get_sub_controllers()["X"]
        y_controller = stage_controller.get_sub_controllers()["Y"]
        self._x_readback = x_controller.readback
        self._y_readback = y_controller.readback
        self._channel = controller.channel
        self._mode = controller.mode
        self._elapsed = det_controller.elapsed

    async def update(self, attr: AttrR):
        x_readback = self._x_readback.get()  # A
        y_readback = self._y_readback.get()  # B
        channel = self._channel  # C
        mode = self._mode.get()  # D
        if mode == _EnergyMode["Low Energy"]:
            mode_rval = 10
        else:  # HIGH
            mode_rval = 100
        elapsed = self._elapsed.get()  # E
        value = floor(
            (sin(x_readback) ** channel + cos(x_readback * y_readback + mode_rval) + 2)
            * 2500
            * elapsed
        )
        await attr.set(value)


class DemoPointDetectorChannelController(SubController):
    """A channel for `DemoPointDetector` with int value based on X and Y Motors."""

    value = AttrR(Int(units="cts"), handler=ValueHandler())
    mode = AttrRW(Enum(_EnergyMode))

    def __init__(self, channel, parent):
        self.channel = channel
        self.top_controller = parent
        super().__init__()


class DemoPointDetectorDetController(SubController):
    acquire_time = AttrRW(Float(), initial_value=0.1)
    acquiring = AttrRW(Bool())
    start_time = AttrR(Float())
    current_time = AttrR(Float())
    elapsed = AttrR(Float())

    def __init__(self, num_channels: int = 3) -> None:
        self._num_channels = num_channels
        super().__init__()

    async def initialise(self, top_controller):
        for i in range(1, self._num_channels + 1):
            subcontroller = DemoPointDetectorChannelController(i, top_controller)
            self.register_sub_controller(f"C{i}", subcontroller)

    async def update_channels(self):
        updates = []
        for controller in self.get_sub_controllers().values():
            value_attr = controller.attributes["value"]
            handler = value_attr.updater
            updates.append(handler.update(value_attr))
        await asyncio.gather(*updates)

    async def update_elapsed(self, value):
        await self.elapsed.set(value)
        await self.update_channels()

    @command()
    async def start(self):
        start_time = time.time()
        await self.start_time.set(start_time)
        await self.acquiring.set(True)
        # reimplement Process PV logic
        while (diff := time.time() - start_time) <= self.acquire_time.get():
            await self.update_elapsed(round(diff, 1))
        await self.acquiring.set(False)
        await self.update_elapsed(self.acquire_time.get())

    @command()
    async def reset(self):
        await self.update_elapsed(0.0)
