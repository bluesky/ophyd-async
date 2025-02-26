from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore


class SimDriverIO(adcore.ADBaseIO):
    """Base class for driving simulated Areadetector IO."""

    pass


class SimController(adcore.ADBaseController[SimDriverIO]):
    """Controller for simulated Areadetector."""

    def __init__(
        self,
        driver: SimDriverIO,
        good_states: frozenset[adcore.ADState] = adcore.DEFAULT_GOOD_STATES,
    ) -> None:
        super().__init__(driver, good_states=good_states)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001


class SimDetector(adcore.AreaDetector[SimController]):
    """Detector for simulated Areadetector."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix="cam1:",
        writer_cls: type[adcore.ADWriter] = adcore.ADHDFWriter,
        fileio_suffix: str | None = None,
        name="",
        config_sigs: Sequence[SignalR] = (),
        plugins: dict[str, adcore.NDPluginBaseIO] | None = None,
    ):
        driver = SimDriverIO(prefix + drv_suffix)
        controller = SimController(driver)

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


class ContAcqSimController(adcore.ADBaseContAcqController[SimDriverIO]):
    """Controller for simulated Areadetector in continuous acquisition mode."""

    def __init__(
        self,
        cb_plugin_prefix: str,
        driver: SimDriverIO,
    ):
        super().__init__(cb_plugin_prefix, driver)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001


class ContAcqSimDetector(adcore.ContAcqAreaDetector[ContAcqSimController]):
    """Detector for simulated Areadetector in continuous acquisition mode."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_suffix: str = "cam1:",
        cb_plugin_suffix: str = "CB1:",
        writer_cls: type[adcore.ADWriter] = adcore.ADHDFWriter,
        fileio_suffix: str | None = None,
        name="",
        config_sigs: Sequence[SignalR] = (),
        plugins: dict[str, adcore.NDPluginBaseIO] | None = None,
    ):
        driver = SimDriverIO(prefix + drv_suffix)
        controller = ContAcqSimController(prefix + cb_plugin_suffix, driver)

        writer = writer_cls.with_io(
            prefix,
            path_provider,
            dataset_source=controller.cb_plugin,
            fileio_suffix=fileio_suffix,
            plugins=plugins,
        )

        super().__init__(
            controller=controller,
            writer=writer,
            name=name,
            config_sigs=config_sigs,
            plugins=plugins,
        )
