from typing import Optional, Sequence
from bluesky.protocols import Hints
from ophyd_async.core import DirectoryProvider
from ophyd_async.core.detector import StandardDetector
from ophyd_async.core.signal import SignalR
from ophyd_async.epics.areadetector.controllers.pilatus_controller import (
    PilatusController,
)
from ophyd_async.epics.areadetector.drivers.ad_base import ADBaseShapeProvider
from ophyd_async.epics.areadetector.drivers.pilatus_driver import PilatusDriver
from ophyd_async.epics.areadetector.writers.hdf_writer import HDFWriter
from ophyd_async.epics.areadetector.writers.nd_file_hdf import NDFileHDF


class PilatusDetector(StandardDetector):
    """A Pilatus StandardDetector writing HDF files"""

    _controller: PilatusController
    _writer: HDFWriter

    def __init__(
        self,
        prefix: str,
        name: str,
        directory_provider: DirectoryProvider,
        driver: PilatusDriver,
        hdf: NDFileHDF,
        config_sigs: Optional[Sequence[SignalR]] = None,
        **scalar_sigs: str,
    ):
        self.drv = driver
        self.hdf = hdf

        super().__init__(
            PilatusController(self.drv),
            HDFWriter(
                self.hdf,
                directory_provider,
                lambda: self.name,
                ADBaseShapeProvider(self.drv),
                **scalar_sigs,
            ),
            config_sigs=config_sigs or (self.drv.acquire_time, ),
            name=name,
        )

    @property
    def hints(self) -> Hints:
        return self._writer.hints
