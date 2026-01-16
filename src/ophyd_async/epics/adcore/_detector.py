from collections.abc import Mapping
from typing import Generic

from ophyd_async.core import StandardDetector

from ._io import ADBaseIOT, NDPluginBaseIO, NDPluginBaseIOT


class AreaDetector(StandardDetector, Generic[ADBaseIOT]):
    def __init__(
        self,
        driver: ADBaseIOT,
        plugins: Mapping[str, NDPluginBaseIO] | None = None,
        name: str = "",
    ):
        self.driver = driver
        if plugins is not None:
            for plugin_name, plugin in plugins.items():
                setattr(self, plugin_name, plugin)
        self.add_config_signals(
            self.driver.acquire_period,
            self.driver.acquire_time,
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
