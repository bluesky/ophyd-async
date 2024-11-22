from collections.abc import Sequence

from ophyd_async.core import PathProvider, SignalR, StandardDetector

from ._core_io import ADBaseDatasetDescriber, ADBaseIO, NDPluginBaseIO
from ._core_logic import ADBaseControllerT
from ._core_writer import ADWriterT


class AreaDetector(StandardDetector[ADBaseControllerT, ADWriterT]):
    def __init__(
        self,
        prefix: str,
        driver: ADBaseIO,
        controller: ADBaseControllerT,
        writer_cls: type[ADWriterT],
        path_provider: PathProvider,
        plugins: dict[str, NDPluginBaseIO] | None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
        fileio_suffix: str | None = None,
    ):
        self.drv = driver
        writer, self.fileio = writer_cls.writer_and_io(
            prefix + (fileio_suffix or writer_cls.default_suffix),
            path_provider,
            lambda: name,
            ADBaseDatasetDescriber(self.drv),
            plugins=plugins,
            name=name,
        )

        if plugins is not None:
            for name, plugin in plugins.items():
                setattr(self, name, plugin)

        super().__init__(
            controller,
            writer,
            (self.drv.acquire_period, self.drv.acquire_time, *config_sigs),
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
