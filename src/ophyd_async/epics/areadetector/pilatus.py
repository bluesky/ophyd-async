from ophyd_async.core import StandardDetector, StaticDirectoryProvider
from ophyd_async.epics.areadetector.drivers.ad_driver import ADDriverShapeProvider
from ophyd_async.epics.areadetector.writers.hdf_writer import HDFWriter as ADHDFWriter
from ophyd_async.epics.areadetector.writers.nd_file_hdf import NDFileHDF
from ophyd_async.epics.areadetector.writers.nd_plugin import NDPluginStats

from .controllers.pilatus_controller import PilatusController
from .drivers.pilatus_driver import PilatusDriver

dp = StaticDirectoryProvider("/dls/p45/data/cmxxx/i22-yyy", "i22-yyy-")


class Pilatus(StandardDetector):
    def __init__(self, prefix: str):
        drv = PilatusDriver(prefix)
        hdf = NDFileHDF(prefix + "HDF:")
        super().__init__(
            PilatusController(drv),
            ADHDFWriter(
                hdf, dp, lambda: self.name, ADDriverShapeProvider(drv), sum="NDStatsSum"
            ),
            config_sigs=[drv.acquire_time, drv.acquire],
            drv=drv,
            stats=NDPluginStats(prefix + "STATS:"),
            hdf=hdf,
        )
