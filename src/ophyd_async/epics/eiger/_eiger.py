from pydantic import Field

from ophyd_async.core import AsyncStatus, PathProvider, StandardDetector
from ophyd_async.core._detector import TriggerInfo

from ._eiger_controller import EigerController
from ._eiger_io import EigerDriverIO
from ._odin_io import Odin, OdinWriter


class EigerTriggerInfo(TriggerInfo):
    energy_ev: float = Field(gt=0)


class EigerDetector(StandardDetector):
    """
    Ophyd-async implementation of an Eiger Detector.
    """

    _controller: EigerController
    _writer: Odin

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="-EA-EIGER-01:",
        hdf_suffix="-EA-ODIN-01:",
        name="",
    ):
        self.drv = EigerDriverIO(prefix + drv_suffix)
        self.odin = Odin(prefix + hdf_suffix + "FP:")

        super().__init__(
            EigerController(self.drv),
            OdinWriter(path_provider, lambda: self.name, self.odin),
            name=name,
        )

    @AsyncStatus.wrap
    async def prepare(self, value: EigerTriggerInfo) -> None:  # type: ignore
        await self._controller.set_energy(value.energy_ev)
        await super().prepare(value)
