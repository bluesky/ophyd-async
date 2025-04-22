from pydantic import Field

from ophyd_async.core import AsyncStatus, PathProvider, StandardDetector, TriggerInfo
from ophyd_async.epics.eiger._odin_io import OdinFileWriterMX

from ._eiger_controller import EigerController
from ._eiger_io import EigerDriverIO


class EigerTriggerInfo(TriggerInfo):
    energy_ev: float = Field(gt=0)


class EigerDetector(StandardDetector):
    """Ophyd-async implementation of an Eiger Detector."""

    _controller: EigerController
    _writer: OdinFileWriterMX

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="-EA-EIGER-02:",
        hdf_suffix="-EA-EIGER-01:",
        name="",
    ):
        # self.drv = EigerDriverIO(prefix + drv_suffix)
        # self.odin = OdinFileWriterMX(
        #     path_provider, prefix + hdf_suffix + "OD:", name=""
        # )
        self.drv = EigerDriverIO("BL03I-EA-EIGER-02:")
        self.odin = OdinFileWriterMX(path_provider, "BL03I-EA-EIGER-01:OD:", name="")
        super().__init__(
            EigerController(self.drv),
            self.odin,
            name=name,
        )

    @AsyncStatus.wrap
    async def prepare(self, value: EigerTriggerInfo) -> None:  # type: ignore
        await self._controller.set_energy(value.energy_ev)
        await super().prepare(value)
