from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    PathProvider,
    StandardDetector,
    TriggerInfo,
    wait_for_value,
)
from ophyd_async.epics.eiger import Odin, OdinWriter

from ._eiger_controller import EigerController
from ._eiger_io import EigerDriverIO


class EigerDetector(StandardDetector):
    """Ophyd-async implementation of an Eiger Detector."""

    _controller: EigerController
    _writer: OdinWriter

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="-EA-EIGER-01:",
        hdf_suffix="-EA-EIGER-01:OD:",
        odin_nodes: int = 4,
        name="",
    ):
        self.drv = EigerDriverIO(prefix + drv_suffix)
        self.odin = Odin(prefix + hdf_suffix, nodes=odin_nodes)

        super().__init__(
            EigerController(self.drv),
            OdinWriter(
                path_provider,
                self.odin,
                self.drv.detector.bit_depth_image,
            ),
            name=name,
        )

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:
        await super().prepare(value)

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        await super().kickoff()
        await wait_for_value(self.odin.fan_ready, 1, DEFAULT_TIMEOUT)
