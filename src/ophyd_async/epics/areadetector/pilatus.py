from ophyd_async.core import StandardDetector, StaticDirectoryProvider
from ophyd_async.epics.areadetector.writers.hdf_writer import HDFWriter
from ophyd_async.epics.areadetector.writers.nd_file_hdf import NDFileHDF
from ophyd_async.epics.areadetector.writers.nd_plugin import NDPluginStats

from .controllers import PilatusController
from .drivers import ADDriverShapeProvider, PilatusDriver

dp = StaticDirectoryProvider("/dls/p45/data/cmxxx/i22-yyy", "i22-yyy-")


class Pilatus(StandardDetector):
    def __init__(self, prefix: str):
        drv = PilatusDriver(prefix)
        hdf = NDFileHDF(prefix + "HDF:")

        super().__init__(
            PilatusController(drv),
            HDFWriter(
                hdf, dp, lambda: self.name, ADDriverShapeProvider(drv), sum="NDStatsSum"
            ),
            config_sigs=[drv.acquire_time, drv.acquire],
        )
        self.stats = NDPluginStats(prefix + "STATS:")
        self.drv = drv
        self.hdf = hdf
