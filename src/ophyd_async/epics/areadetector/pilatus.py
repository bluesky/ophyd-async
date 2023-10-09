from ophyd_async.core import StandardDetector, StaticDirectoryProvider
from ophyd_async.epics.areadetector.writers.hdf_writer import HDFWriter
from ophyd_async.epics.areadetector.writers.nd_file_hdf import NDFileHDF
from ophyd_async.epics.areadetector.writers.nd_plugin import NDPluginStats

from .controllers.pilatus_controller import PilatusController
from .drivers.pilatus_driver import PilatusDriver

dp = StaticDirectoryProvider("/dls/p45/data/cmxxx/i22-yyy", "i22-yyy-")


class Pilatus(StandardDetector):
    def __init__(self, prefix: str):
        self.drv = PilatusDriver(prefix)
        self.hdf = NDFileHDF(prefix + "HDF:")
        self.stats = NDPluginStats(prefix + "STATS:")
        super().__init__(
            PilatusController(self.drv),
            HDFWriter(
                self.hdf, dp, lambda: self.name, self.drv.shape, sum="NDStatsSum"
            ),
            config_sigs=[self.drv.acquire_time, self.drv.acquire],
        )
