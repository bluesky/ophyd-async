from collections.abc import Iterator, Mapping, Sequence
from typing import Generic

from ophyd_async.core import (
    DetectorAcquireLogic,
    DetectorTriggerLogic,
    SignalR,
    StandardDetector,
)

from ._acquire_logic import ADContAcqAcquireLogic
from ._data_logic import ADWriterFactory
from ._io import ADBaseIO, ADBaseIOT, NDCircularBuffIO, NDPluginBaseIO, NDPluginBaseIOT, NDProcessIO
from ._trigger_logic import ADContAcqTriggerLogic


class AreaDetector(StandardDetector, Generic[ADBaseIOT]):
    def __init__(
        self,
        driver: ADBaseIOT,
        prefix: str | None = None,
        *writer_factories: ADWriterFactory,
        acquire_logic: DetectorAcquireLogic | None = None,
        trigger_logic: DetectorTriggerLogic | None = None,
        plugins: Mapping[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        self.driver = driver
        if plugins is not None:
            for plugin_name, plugin in plugins.items():
                setattr(self, plugin_name, plugin)
        if trigger_logic:
            self.add_detector_logics(trigger_logic)
        if acquire_logic:
            self.add_detector_logics(acquire_logic)
        if writer_factories:
            if prefix is None:
                raise ValueError("prefix is required when writer_factories are given")
            names = [f.writer_name for f in writer_factories]
            if len(names) != len(set(names)):
                duplicates = sorted({n for n in names if names.count(n) > 1})
                raise ValueError(
                    f"Duplicate writer_name(s) in writer_factories: {duplicates}"
                )
            plugin_list = list(plugins.values()) if plugins else []
            for factory in writer_factories:
                writer, data_logic = factory(prefix, driver, plugin_list)
                setattr(self, factory.writer_name, writer)
                self.add_detector_logics(data_logic)
        self.add_config_signals(
            self.driver.acquire_period, self.driver.acquire_time, *config_sigs
        )
        super().__init__(name=name)


    def get_plugin_by_name(
        self, name: str, plugin_type: type[NDPluginBaseIOT] = NDPluginBaseIO
    ) -> NDPluginBaseIOT:
        """Get a plugin by name and type.
        
        :param name: Name of the plugin attribute
        :param plugin_type: Expected type of the plugin
        :return: The plugin instance
        :raises AttributeError: If the plugin does not exist
        :raises TypeError: If the plugin is not of the expected type
        """

        plugin = getattr(self, name, None)
        if plugin is None:
            raise AttributeError(f"{self.name} has no plugin named '{name}'")
        elif not isinstance(plugin, plugin_type):
            raise TypeError(
                f"Expected {self.name}.{name} to be a {plugin_type.__name__}, "
                f"got {type(plugin).__name__}"
            )
        return plugin


    async def get_plugin_by_port_name(
        self, port_name: str, plugin_type: type[NDPluginBaseIOT] = NDPluginBaseIO
    ) -> NDPluginBaseIOT:
        """Get a plugin by its NDArray port name and type.

        :param port_name: The NDArray port name to search for
        :param plugin_type: Expected type of the plugin
        :return: The plugin instance
        :raises ValueError: If no plugin with the specified port name is found
        """

        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if isinstance(attr, plugin_type):
                if await attr.port_name.get_value() == port_name:
                    return attr
        raise ValueError(f"No plugin found with port name '{port_name}'")


    def get_plugins_by_type(
        self, plugin_type: type[NDPluginBaseIOT] = NDPluginBaseIO
    ) -> Iterator[NDPluginBaseIOT]:
        """Yield all plugins of a specific type.

        :param plugin_type: Expected type of the plugins
        :return: Iterator of plugin instances
        """

        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if isinstance(attr, plugin_type):
                yield attr


class ContAcqDetector(AreaDetector[ADBaseIO]):
    """Create an ADSimDetector AreaDetector instance.

    :param prefix: EPICS PV prefix for the detector
    :param writer_factories: Factories for file writer plugins and their data logics
    :param driver_suffix: Suffix for the driver PV, defaults to "cam1:"
    :param plugins: Additional areaDetector plugins to include
    :param config_sigs: Additional signals to include in configuration
    :param name: Name for the detector device
    """

    def __init__(
        self,
        prefix: str,
        *writer_factories: ADWriterFactory,
        driver_suffix="cam1:",
        cb_suffix="CB1:",
        plugins: dict[str, NDPluginBaseIO] | None = None,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
    ) -> None:
        driver = ADBaseIO(prefix + driver_suffix)
        cb_plugin = NDCircularBuffIO(prefix + cb_suffix)
        process_plugin = next(self.get_plugins_by_type(NDProcessIO), None)
        super().__init__(
            driver,
            prefix,
            *writer_factories,
            acquire_logic=ADContAcqAcquireLogic(driver, cb_plugin),
            trigger_logic=ADContAcqTriggerLogic(driver, cb_plugin, process_plugin),
            plugins=(plugins or {}) | {"cb": cb_plugin},
            config_sigs=config_sigs,
            name=name,
        )
