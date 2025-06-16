from collections.abc import Sequence

from ophyd_async.core import SignalR, StandardDetector
from ophyd_async.core._providers import PathProvider

from ._core_io import ADBaseIO, NDPluginBaseIO, NDPluginCBIO
from ._core_logic import ADBaseContAcqController, ADBaseControllerT
from ._core_writer import ADWriter
from ._hdf_writer import ADHDFWriter


class AreaDetector(StandardDetector[ADBaseControllerT, ADWriter]):
    def __init__(
        self,
        controller: ADBaseControllerT,
        writer: ADWriter,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ):
        self.driver = controller.driver
        self.fileio = writer.fileio

        if plugins is not None:
            for plugin_name, plugin in plugins.items():
                setattr(self, plugin_name, plugin)

        super().__init__(
            controller,
            writer,
            (self.driver.acquire_period, self.driver.acquire_time, *config_sigs),
            name=name,
        )

    def get_plugin(
        self, name: str, plugin_type: type[NDPluginBaseIO] = NDPluginBaseIO
    ) -> NDPluginBaseIO:
        plugin = getattr(self, name, None)
        if not isinstance(plugin, plugin_type):
            raise TypeError(
                f"Expected {self.name}.{name} to be a {plugin_type}, got {plugin}"
            )
        return plugin


class ContAcqAreaDetector(AreaDetector[ADBaseContAcqController]):
    """Ophyd-async implementation of a continuously acquiring AreaDetector."""

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider,
        drv_cls: type[ADBaseIO] = ADBaseIO,
        drv_suffix: str = "cam1:",
        cb_suffix: str = "CB1:",
        writer_cls: type[ADWriter] = ADHDFWriter,
        fileio_suffix: str | None = None,
        name: str = "",
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
    ):
        self.cb_plugin = NDPluginCBIO(prefix + cb_suffix)
        driver = drv_cls(prefix + drv_suffix)
        controller = ADBaseContAcqController(driver, self.cb_plugin)

        writer = writer_cls.with_io(
            prefix,
            path_provider,
            # Since the CB plugin controls acq, use it when checking shape
            dataset_source=self.cb_plugin,
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
