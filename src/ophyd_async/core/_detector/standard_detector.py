import asyncio
from typing import Dict, Iterator, Sequence

from bluesky.protocols import (
    Asset,
    Configurable,
    Descriptor,
    Readable,
    Reading,
    Stageable,
    Triggerable,
    WritesExternalAssets,
)

from .._device.device import Device
from .._signal.signal import SignalR
from ..async_status import AsyncStatus
from ..utils import merge_gathered_dicts
from .detector_control import DetectorControl, DetectorTrigger
from .detector_writer import DetectorWriter


class StandardDetector(
    Device,
    Stageable,
    Configurable,
    Readable,
    Triggerable,
    WritesExternalAssets,
):
    """Detector with useful default behaviour.

    Can be supplied extra devices such that they can also be accessed on the detector.
    This allows for similar on-the-fly device generation as what is currently done for
    the ophyd_async.panda.PandA object.

    Must be supplied instances of classes that inherit from DetectorControl and
    DetectorData, to dictate how the detector will be controlled (i.e. arming and
    disarming) as well as how the detector data will be written (i.e. opening and
    closing the writer, and handling data writing indices).

    NOTE: only for step-scans.
    """

    def __init__(
        self,
        control: DetectorControl,
        data: DetectorWriter,
        config_sigs: Sequence[SignalR],
        name: str = "",
        **plugins: Device,
    ) -> None:
        """
        Parameters
        ----------
        control:
            instance of class which inherits from :class:`DetectorControl`
        data:
            instance of class which inherits from :class:`DetectorData`
        config_sigs:
            configuration signals to be used for describing/reading the detector.
        name:
            detector name
        """
        self.control = control
        self.data = data
        self._config_sigs = config_sigs
        self._describe: Dict[str, Descriptor] = {}
        self.__dict__.update(plugins)
        super().__init__(name)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        """Disarm the detector, stop filewriting, and open file for writing."""
        await asyncio.gather(self.data.close(), self.control.disarm())
        self._describe = await self.data.open()

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(sig.describe() for sig in self._config_sigs)

    async def read_configuration(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(sig.read() for sig in self._config_sigs)

    def describe(self) -> Dict[str, Descriptor]:
        return self._describe

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Arm the detector and wait for it to finish."""
        indices_written = await self.data.get_indices_written()
        written_status = await self.control.arm(DetectorTrigger.internal, num=1)
        await written_status
        await self.data.wait_for_index(indices_written + 1)

    async def read(self) -> Dict[str, Reading]:
        """Unused method: will be deprecated."""
        # All data is in StreamResources, not Events, so nothing to output here
        return {}

    async def collect_asset_docs(self) -> Iterator[Asset]:
        """Collect stream datum documents for all indices written."""
        indices_written = await self.data.get_indices_written()
        async for doc in self.data.collect_stream_docs(indices_written):
            yield doc

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        """Stop data writing."""
        await self.data.close()
