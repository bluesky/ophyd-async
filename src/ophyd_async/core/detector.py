"""Module which defines abstract classes to work with detectors"""
import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from typing import AsyncIterator, Dict, Optional, Sequence, TypeVar

from bluesky.protocols import (
    Asset,
    Collectable,
    Configurable,
    Descriptor,
    Readable,
    Reading,
    Stageable,
    StreamAsset,
    Triggerable,
    WritesStreamAssets,
)

from .async_status import AsyncStatus
from .device import Device
from .signal import SignalR
from .utils import DEFAULT_TIMEOUT, merge_gathered_dicts

T = TypeVar("T")


class DetectorTrigger(str, Enum):
    #: Detector generates internal trigger for given rate
    internal = "internal"
    #: Expect a series of arbitrary length trigger signals
    edge_trigger = "edge_trigger"
    #: Expect a series of constant width external gate signals
    constant_gate = "constant_gate"
    #: Expect a series of variable width external gate signals
    variable_gate = "variable_gate"


class DetectorControl(ABC):
    @abstractmethod
    def get_deadtime(self, exposure: float) -> float:
        """For a given exposure, how long should the time between exposures be"""

    @abstractmethod
    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        """Arm the detector and return AsyncStatus.

        Awaiting the return value will wait for num frames to be written.
        """

    @abstractmethod
    async def disarm(self):
        """Disarm the detector"""


class DetectorWriter(ABC):
    @abstractmethod
    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        """Open writer and wait for it to be ready for data.

        Args:
            multiplier: Each StreamDatum index corresponds to this many
                written exposures

        Returns:
            Output for ``describe()``
        """

    @abstractmethod
    async def wait_for_index(
        self, index: int, timeout: Optional[float] = DEFAULT_TIMEOUT
    ) -> None:
        """Wait until a specific index is ready to be collected"""

    @abstractmethod
    async def get_indices_written(self) -> int:
        """Get the number of indices written"""

    @abstractmethod
    def collect_stream_docs(self, indices_written: int) -> AsyncIterator[Asset]:
        """Create Stream docs up to given number written"""

    @abstractmethod
    async def close(self) -> None:
        """Close writer and wait for it to be finished"""


class StandardDetector(
    Device,
    Stageable,
    Configurable,
    Readable,
    Triggerable,
    WritesStreamAssets,
    Collectable,
):
    """Detector with useful default behaviour.

    Must be supplied instances of classes that inherit from DetectorControl and
    DetectorData, to dictate how the detector will be controlled (i.e. arming and
    disarming) as well as how the detector data will be written (i.e. opening and
    closing the writer, and handling data writing indices).

    NOTE: only for step-scans.
    """

    def __init__(
        self,
        controller: DetectorControl,
        writer: DetectorWriter,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
        writer_timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """
        Parameters
        ----------
        control:
            instance of class which inherits from :class:`DetectorControl`
        data:
            instance of class which inherits from :class:`DetectorData`
        name:
            detector name
        """
        self._controller = controller
        self._writer = writer
        self._describe: Dict[str, Descriptor] = {}
        self._config_sigs = list(config_sigs)
        self._frame_writing_timeout = writer_timeout
        super().__init__(name)

    @property
    def controller(self) -> DetectorControl:
        return self._controller

    @property
    def writer(self) -> DetectorWriter:
        return self._writer

    async def check_config_sigs(self):
        """Checks configuration signals are named and connected."""
        for signal in self._config_sigs:
            if signal._name == "":
                raise Exception(
                    "config signal must be named before it is passed to the detector"
                )

            try:
                await signal.get_value()
            except NotImplementedError:
                raise Exception(
                    f"config signal {signal._name} must be connected before it is "
                    + "passed to the detector"
                )

    @AsyncStatus.wrap
    async def stage(self) -> None:
        """Disarm the detector, stop filewriting, and open file for writing."""
        await self.check_config_sigs()
        await asyncio.gather(self.writer.close(), self.controller.disarm())
        self._describe = await self.writer.open()

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(sig.describe() for sig in self._config_sigs)

    async def read_configuration(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(sig.read() for sig in self._config_sigs)

    def describe(self) -> Dict[str, Descriptor]:
        return self._describe

    async def describe_collect(self) -> Dict[str, Descriptor]:
        return self._describe

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Arm the detector and wait for it to finish."""
        indices_written = await self.writer.get_indices_written()
        written_status = await self.controller.arm(
            num=1,
            trigger=DetectorTrigger.internal,
        )
        await written_status
        await self.writer.wait_for_index(
            indices_written + 1, timeout=self._frame_writing_timeout
        )

    async def read(self) -> Dict[str, Reading]:
        """Read the detector"""
        # All data is in StreamResources, not Events, so nothing to output here
        return {}

    async def get_index(self) -> int:
        return await self.writer.get_indices_written()

    async def collect_asset_docs(
        self, index: Optional[int]
    ) -> AsyncIterator[StreamAsset]:
        """Collect stream datum documents for all indices written.

        The index is optional, and provided for flyscans, however this needs to be
        retrieved for stepscans.
        """
        if index:
            async for doc in self.writer.collect_stream_docs(index):
                yield doc
        else:
            index = await self.writer.get_indices_written()
            async for doc in self.writer.collect_stream_docs(index):
                yield doc

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        """Stop data writing."""
        await self.writer.close()
