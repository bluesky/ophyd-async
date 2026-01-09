from collections.abc import Sequence
from typing import Generic

from ophyd_async.core import (
    DetectorArmLogic,
    DetectorDataLogic,
    DetectorTriggerLogic,
    SignalR,
    StandardDetector,
)

from ._io import ADBaseIOT, NDPluginBaseIO, NDPluginBaseIOT


class AreaDetector(StandardDetector, Generic[ADBaseIOT]):
    def __init__(
        self,
        driver: ADBaseIOT,
        trigger_logic: DetectorTriggerLogic,
        data_logic: DetectorDataLogic,
        arm_logic: DetectorArmLogic,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ):
        self.driver = driver
        if plugins is not None:
            for plugin_name, plugin in plugins.items():
                setattr(self, plugin_name, plugin)

        super().__init__(
            trigger_logic=trigger_logic,
            arm_logic=arm_logic,
            data_logic=data_logic,
            config_sigs=(
                self.driver.acquire_period,
                self.driver.acquire_time,
                *config_sigs,
            ),
            name=name,
        )

    def get_plugin(
        self, name: str, plugin_type: type[NDPluginBaseIOT] = NDPluginBaseIO
    ) -> NDPluginBaseIOT:
        plugin = getattr(self, name, None)
        if not isinstance(plugin, plugin_type):
            raise TypeError(
                f"Expected {self.name}.{name} to be a {plugin_type}, got {plugin}"
            )
        return plugin
