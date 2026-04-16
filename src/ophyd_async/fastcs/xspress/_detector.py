from ophyd_async.core import PathProvider, StandardDetector
from ophyd_async.fastcs.core import fastcs_connector

from ._arm_logic import XspressArmLogic
from ._data_logic import XspressOdinDataLogic
from ._io import XspressDetectorIO
from ._trigger_logic import XspressTriggerLogic
from ._xsp_odin_io import XspressOdinIO


class XspressDetector(StandardDetector):
    """Ophyd-async implementation of an Xspress Detector."""

    xspress: XspressDetectorIO
    od: XspressOdinIO

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        name="",
    ):
        connector = fastcs_connector(prefix, self)

        self.add_detector_logics(
            XspressTriggerLogic(self.xspress),
            XspressArmLogic(self.xspress),
            XspressOdinDataLogic(
                path_provider=path_provider,
                odin=self.od,
            ),
        )
        super().__init__(name=name, connector=connector)
