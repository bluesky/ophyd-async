from ophyd_async.core import PathProvider, StandardDetector

from ._eiger_controller import EigerController
from ._eiger_io import EigerDriverIO
from ._odin_io import Odin, OdinWriter


class EigerDetector(StandardDetector):
    """
    Ophyd-async implementation of an ADKinetix Detector.
    https://github.com/NSLS-II/ADKinetix
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
            OdinWriter(path_provider, lambda: "", self.odin),
            name=name,
        )
