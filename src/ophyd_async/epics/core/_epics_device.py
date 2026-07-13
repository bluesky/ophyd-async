from ophyd_async.core import Device, DeviceConnector

from ._epics_connector import EpicsDeviceConnector
from ._pvi_connector import PviDeviceConnector


class EpicsDevice(Device):
    """Baseclass to allow child signals to be created declaratively.

    :param prefix: The PV prefix, used to build an `EpicsDeviceConnector` (or a
        `PviDeviceConnector` if `with_pvi`) unless `connector` is given.
    :param connector: A pre-built `DeviceConnector`, used when this device is
        created as a declarative sub-device of another `EpicsDevice` (the parent
        connector builds and addresses it). When given, `prefix`/`with_pvi` are
        ignored.
    """

    def __init__(
        self,
        prefix: str = "",
        with_pvi: bool = False,
        name: str = "",
        connector: DeviceConnector | None = None,
    ):
        if connector is None:
            if with_pvi:
                connector = PviDeviceConnector(prefix)
            else:
                connector = EpicsDeviceConnector(prefix)
        super().__init__(name=name, connector=connector)
