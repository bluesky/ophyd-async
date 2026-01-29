from collections.abc import Mapping, Sequence
from typing import Generic

from ophyd_async.core import (
    DetectorArmLogic,
    DetectorTriggerLogic,
    PathProvider,
    SignalR,
    StandardDetector,
)

from ._arm_logic import ADContAcqArmLogic
from ._data_logic import ADWriterType, make_writer_data_logic
from ._io import ADBaseIO, ADBaseIOT, NDCircularBuffIO, NDPluginBaseIO, NDPluginBaseIOT
from ._trigger_logic import ADContAcqTriggerLogic


class AreaDetector(StandardDetector, Generic[ADBaseIOT]):
    def __init__(
        self,
        driver: ADBaseIOT,
        arm_logic: DetectorArmLogic | None = None,
        trigger_logic: DetectorTriggerLogic | None = None,
        path_provider: PathProvider | None = None,
        writer_type: ADWriterType | None = ADWriterType.HDF,
        prefix: str = "",
        writer_suffix: str | None = None,
        plugins: Mapping[str, NDPluginBaseIO] | None = None,
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


class ContAcqDetector(AreaDetector[ADBaseIO]):
    """Create an ADSimDetector AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param path_provider: Provider for file paths during acquisition
    :param driver_suffix: Suffix for the driver PV, defaults to "cam1:"
    :param writer_type: Type of file writer (HDF or TIFF)
    :param writer_suffix: Suffix for the writer PV
    :param plugins: Additional areaDetector plugins to include
    :param config_sigs: Additional signals to include in configuration
    :param name: Name for the detector device
    """

    def __init__(
        self,
        prefix: str,
        path_provider: PathProvider | None = None,
        driver_suffix="cam1:",
        cb_suffix="CB1:",
        writer_type: ADWriterType | None = ADWriterType.HDF,
        writer_suffix: str | None = None,
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = ADBaseIO(prefix + driver_suffix)
        cb_plugin = NDCircularBuffIO(prefix + cb_suffix)
        super().__init__(
            prefix=prefix,
            driver=driver,
            arm_logic=ADContAcqArmLogic(driver, cb_plugin),
            trigger_logic=ADContAcqTriggerLogic(driver, cb_plugin),
            path_provider=path_provider,
            writer_type=writer_type,
            writer_suffix=writer_suffix,
            plugins=(plugins or {}) | {"cb": cb_plugin},
            config_sigs=config_sigs,
            name=name,
        )
