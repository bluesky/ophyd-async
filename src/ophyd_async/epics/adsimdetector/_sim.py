from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore
from ophyd_async.epics.adcore._core_detector import AreaDetector
from ophyd_async.epics.adcore._core_io import DetectorState, NDPluginBaseIO
from ophyd_async.epics.adcore._core_logic import DEFAULT_GOOD_STATES
from ophyd_async.epics.adcore._core_writer import ADWriter
from ophyd_async.epics.adcore._hdf_writer import ADHDFWriter


class SimDriverIO(adcore.ADBaseIO): ...


class SimController(adcore.ADBaseController[SimDriverIO]):
    def __init__(
        self,
        driver: SimDriverIO,
        good_states: frozenset[DetectorState] = DEFAULT_GOOD_STATES,
    ) -> None:
        super().__init__(driver, good_states=good_states)


class SimDetector(AreaDetector[SimController, ADWriter]):
    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        writer_cls: type[ADWriter] = ADHDFWriter,
        fileio_suffix: str | None = None,
        name="",
        config_sigs: Sequence[SignalR] = (),
        plugins: dict[str, NDPluginBaseIO] = None,
    ):
        if plugins is None:
            plugins = {}
        controller, driver = SimController.controller_and_drv(
            prefix + drv_suffix, name=name
        )

        super().__init__(
            prefix=prefix,
            driver=driver,
            controller=controller,
            writer_cls=writer_cls,
            fileio_suffix=fileio_suffix,
            path_provider=path_provider,
            plugins=plugins,
            name=name,
            config_sigs=config_sigs,
        )
