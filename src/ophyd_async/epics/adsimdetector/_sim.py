from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR
from ophyd_async.epics import adcore


class SimDriverIO(adcore.ADBaseIO): ...


class SimController(adcore.ADBaseController[SimDriverIO]):
    def __init__(
        self,
        driver: SimDriverIO,
        good_states: frozenset[adcore.DetectorState] = adcore.DEFAULT_GOOD_STATES,
    ) -> None:
        super().__init__(driver, good_states=good_states)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001


class SimDetector(adcore.AreaDetector[SimController]):
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
