from ophyd_async.core import StaticDirectoryProvider, StandardDetector
from ophyd_async.epics.areadetector.drivers.ad_driver import ADDriverShapeProvider
from ophyd_async.epics.areadetector.writers.hdf_writer import HDFWriter as ADHDFWriter
from ophyd_async.epics.areadetector.writers.nd_file_hdf import NDFileHDF
from ophyd_async.epics.areadetector.writers.nd_plugin import NDPluginStats

from .drivers.pilatus_driver import PilatusDriver
from .pilatus_control import PilatusControl

dp = StaticDirectoryProvider("/dls/p45/data/cmxxx/i22-yyy", "i22-yyy-")


class Pilatus(StandardDetector):
    def __init__(self, prefix: str):
        drv = PilatusDriver(prefix)
        hdf = NDFileHDF(prefix + "HDF:")
        super().__init__(
            PilatusControl(drv),
            ADHDFWriter(
                hdf, dp, lambda: self.name, ADDriverShapeProvider(drv), sum="NDStatsSum"
            ),
            config_sigs=[drv.acquire_time, drv.acquire],
            drv=drv,
            stats=NDPluginStats(prefix + "STATS:"),
            hdf=hdf,
        )
