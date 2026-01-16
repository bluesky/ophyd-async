from collections.abc import Sequence
from typing import Generic

from ophyd_async.core import (
    DetectorArmLogic,
    DetectorTriggerLogic,
    PathProvider,
    SignalR,
    StandardDetector,
)

from ._data_logic import ADWriterType, make_writer_data_logic
from ._io import ADBaseIOT, NDPluginBaseIO, NDPluginBaseIOT


class AreaDetector(StandardDetector, Generic[ADBaseIOT]):
    def __init__(
        self,
        prefix: str,
        driver: ADBaseIOT,
        arm_logic: DetectorArmLogic | None = None,
        trigger_logic: DetectorTriggerLogic | None = None,
        path_provider: PathProvider | None = None,
        writer_type: ADWriterType | None = ADWriterType.HDF,
        writer_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        self.driver = driver
        if plugins is not None:
            for plugin_name, plugin in plugins.items():
                setattr(self, plugin_name, plugin)
        if trigger_logic:
            self.add_logics(trigger_logic)
        if arm_logic:
            self.add_logics(arm_logic)
        if writer_type:
            if path_provider is None:
                raise ValueError("PathProvider required to add a writer")
            writer, data_logic = make_writer_data_logic(
                prefix=prefix,
                path_provider=path_provider,
                writer_suffix=writer_suffix,
                driver=driver,
                writer_type=writer_type,
                plugins=plugins,
            )
            self.writer = writer
            self.add_logics(data_logic)
        self.add_config_signals(
            self.driver.acquire_period, self.driver.acquire_time, *config_sigs
        )
        super().__init__(name=name)

    def get_plugin(
        self, name: str, plugin_type: type[NDPluginBaseIOT] = NDPluginBaseIO
    ) -> NDPluginBaseIOT:
        plugin = getattr(self, name, None)
        if plugin is None:
            raise AttributeError(f"{self.name} has no plugin named '{name}'")
        elif not isinstance(plugin, plugin_type):
            raise TypeError(
                f"Expected {self.name}.{name} to be a {plugin_type.__name__}, "
                f"got {type(plugin).__name__}"
            )
        return plugin
