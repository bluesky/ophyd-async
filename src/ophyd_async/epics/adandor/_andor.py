from collections.abc import Sequence

from ophyd_async.core import PathProvider
from ophyd_async.core._signal import SignalR
from ophyd_async.epics import adcore

from ._andor_controller import Andor2Controller
from ._andor_io import Andor2DriverIO


class Andor2Detector(adcore.AreaDetector[Andor2Controller]):
    """Andor 2 area detector device (CCD detector 56fps with full chip readout).

    Andor model:DU897_BV.
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        writer_cls: type[adcore.ADWriter] = adcore.ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        config_sigs: Sequence[SignalR] = (),
        plugins: dict[str, adcore.NDPluginBaseIO] | None = None,
    ):
        driver = Andor2DriverIO(prefix + drv_suffix)
        controller = Andor2Controller(driver)

        writer = writer_cls.with_io(
            prefix,
            path_provider,
            dataset_source=driver,
            fileio_suffix=fileio_suffix,
            plugins=plugins,
        )

        super().__init__(
            controller=controller,
            writer=writer,
            plugins=plugins,
            name=name,
            config_sigs=config_sigs,
        )
