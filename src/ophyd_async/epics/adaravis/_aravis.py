from collections.abc import Sequence

from ophyd_async.core import PathProvider
from ophyd_async.core._signal import SignalR
from ophyd_async.epics import adcore
from ophyd_async.epics.adcore._core_io import NDPluginBaseIO

from ._aravis_controller import AravisController
from ._aravis_io import AravisDriverIO


def _aravis_drv_controller(
    prefix: str, drv_suffix: str, gpio_number: AravisController.GPIO_NUMBER
) -> tuple[AravisDriverIO, AravisController]:
    drv = AravisDriverIO(prefix + drv_suffix)
    controller = AravisController(drv, gpio_number)
    return drv, controller


def aravis_detector_hdf(
    prefix: str,
    path_provider: PathProvider,
    drv_suffix="cam1:",
    hdf_suffix="HDF1:",
    gpio_number: AravisController.GPIO_NUMBER = 1,
    plugins: dict[str, NDPluginBaseIO] | None = None,
    config_sigs: Sequence[SignalR] = (),
    name="",
) -> adcore.AreaDetector:
    drv, controller = _aravis_drv_controller(prefix, drv_suffix, gpio_number)
    fileio = adcore.NDFileHDFIO(prefix + hdf_suffix)
    return adcore.AreaDetector(
        drv, controller, fileio, path_provider, plugins or {}, config_sigs, name
    )


def aravis_detector_tiff(
    prefix: str,
    path_provider: PathProvider,
    drv_suffix="cam1:",
    tiff_suffix="TIFF:",
    gpio_number: AravisController.GPIO_NUMBER = 1,
    plugins: dict[str, NDPluginBaseIO] | None = None,
    config_sigs: Sequence[SignalR] = (),
    name="",
) -> adcore.AreaDetector:
    drv, controller = _aravis_drv_controller(prefix, drv_suffix, gpio_number)
    fileio = adcore.NDFileIO(prefix + tiff_suffix)
    return adcore.AreaDetector(
        drv, controller, fileio, path_provider, plugins or {}, config_sigs, name
    )
