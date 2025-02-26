from collections.abc import Sequence

from ophyd_async.core import SignalR, StandardDetector

from ._core_io import NDPluginBaseIO
from ._core_logic import ADBaseContAcqControllerT, ADBaseControllerT
from ._core_writer import ADWriter


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
            for name, plugin in plugins.items():
                setattr(self, name, plugin)

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


class ContAcqAreaDetector(StandardDetector[ADBaseContAcqControllerT, ADWriter]):
    def __init__(
        self,
        controller: ADBaseContAcqControllerT,
        writer: ADWriter,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ):
        self.cb_plugin = controller.cb_plugin
        self.driver = controller.driver
        self.fileio = writer.fileio

        if plugins is not None:
            for name, plugin in plugins.items():
                setattr(self, name, plugin)

        super().__init__(
            controller,
            writer,
            (self.driver.acquire_period, self.driver.acquire_time, *config_sigs),
            name=name,
        )
