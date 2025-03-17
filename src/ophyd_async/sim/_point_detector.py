import asyncio
import time

import numpy as np

from ophyd_async.core import (
    AsyncStatus,
    DeviceVector,
    SignalR,
    StandardReadable,
    StrictEnum,
    gather_dict,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format

from ._pattern_generator import PatternGenerator


class EnergyMode(StrictEnum):
    """Energy mode for `SimPointDetector`."""

    LOW = "Low Energy"
    """Low energy mode"""

    HIGH = "High Energy"
    """High energy mode"""


class SimPointDetectorChannel(StandardReadable):
    def __init__(self, value_signal: SignalR[int], name=""):
        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.value = value_signal
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.mode = soft_signal_rw(EnergyMode)
        super().__init__(name)


class SimPointDetector(StandardReadable):
    """Simalutes a point detector with multiple channels."""

    def __init__(
        self, generator: PatternGenerator, num_channels: int = 3, name: str = ""
    ) -> None:
        self._generator = generator
        self.acquire_time = soft_signal_rw(float, 0.1)
        self.acquiring, self._set_acquiring = soft_signal_r_and_setter(bool)
        self._value_signals = dict(
            soft_signal_r_and_setter(int) for _ in range(num_channels)
        )
        with self.add_children_as_readables():
            self.channel = DeviceVector(
                {
                    i + 1: SimPointDetectorChannel(value_signal)
                    for i, value_signal in enumerate(self._value_signals)
                }
            )
        super().__init__(name=name)

    async def _update_values(self, acquire_time: float):
        # Get the modes
        modes = await gather_dict(
            {channel: channel.mode.get_value() for channel in self.channel.values()}
        )
        start = time.monotonic()
        # Make an array of relative update times at 10Hz intervals
        update_times = np.arange(0.1, acquire_time, 0.1)
        # With the end position appended
        update_times = np.concatenate((update_times, [acquire_time]))
        for update_time in update_times:
            # Calculate how long to wait to get there
            relative_time = time.monotonic() - start
            await asyncio.sleep(update_time - relative_time)
            # Update the channel value
            for i, channel in self.channel.items():
                high_energy = modes[channel] == EnergyMode.HIGH
                point = self._generator.generate_point(i, high_energy)
                setter = self._value_signals[channel.value]
                setter(int(point * 10000 * update_time))

    @AsyncStatus.wrap
    async def trigger(self):
        for setter in self._value_signals.values():
            setter(0)
        await self._update_values(await self.acquire_time.get_value())
