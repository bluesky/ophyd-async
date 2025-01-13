"""The building blocks for making devices.

.. data:: SignalDatatype

    The supported `Signal` datatypes

    - A python primitive `bool`, `int`, `float`, `str`
    - A `StrictEnum` or `SubsetEnum` subclass
    - A fixed datatype ``Array1D`` of numpy bool, signed and unsigned integers or float
    - A numpy array which can change dimensions and datatype at runtime
    - A `Sequence` of `str`
    - A `Sequence` of `StrictEnum` or `SubsetEnum` subclass
    - A `Table` subclass
"""

from ._detector import (
    DetectorController,
    DetectorControllerT,
    DetectorTrigger,
    DetectorWriter,
    StandardDetector,
    TriggerInfo,
)
from ._device import Device, DeviceConnector, DeviceVector, init_devices
from ._device_filler import DeviceFiller
from ._flyer import FlyerController, StandardFlyer
from ._hdf_dataset import HDFDataset, HDFFile
from ._log import config_ophyd_async_logging
from ._mock_signal_backend import MockSignalBackend
from ._protocol import AsyncConfigurable, AsyncReadable, AsyncStageable, Watcher
from ._providers import (
    AutoIncrementFilenameProvider,
    AutoIncrementingPathProvider,
    DatasetDescriber,
    FilenameProvider,
    NameProvider,
    PathInfo,
    PathProvider,
    StaticFilenameProvider,
    StaticPathProvider,
    UUIDFilenameProvider,
    YMDPathProvider,
)
from ._readable import (
    ConfigSignal,
    HintedSignal,
    StandardReadable,
    StandardReadableFormat,
)
from ._settings import Settings, SettingsProvider
from ._signal import (
    Signal,
    SignalConnector,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
    observe_signals_value,
    observe_value,
    set_and_wait_for_other_value,
    set_and_wait_for_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
    wait_for_value,
    walk_rw_signals,
)
from ._signal_backend import (
    Array1D,
    DTypeScalar_co,
    SignalBackend,
    SignalDatatype,
    SignalDatatypeT,
    make_datakey,
)
from ._soft_signal_backend import SignalMetadata, SoftSignalBackend
from ._status import AsyncStatus, WatchableAsyncStatus, completed_status
from ._table import Table
from ._utils import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    CalculatableTimeout,
    Callback,
    LazyMock,
    NotConnected,
    Reference,
    StrictEnum,
    SubsetEnum,
    T,
    WatcherUpdate,
    gather_dict,
    get_dtype,
    get_enum_cls,
    get_unique,
    in_micros,
    wait_for_connection,
)
from ._yaml_settings import YamlSettingsProvider

__all__ = [
    "DetectorController",
    "DetectorControllerT",
    "DetectorTrigger",
    "DetectorWriter",
    "StandardDetector",
    "TriggerInfo",
    "Device",
    "DeviceConnector",
    "init_devices",
    "DeviceVector",
    "DeviceFiller",
    "StandardFlyer",
    "FlyerController",
    "HDFDataset",
    "HDFFile",
    "config_ophyd_async_logging",
    "MockSignalBackend",
    "AsyncConfigurable",
    "AsyncReadable",
    "AsyncStageable",
    "AutoIncrementFilenameProvider",
    "AutoIncrementingPathProvider",
    "FilenameProvider",
    "NameProvider",
    "PathInfo",
    "PathProvider",
    "DatasetDescriber",
    "StaticFilenameProvider",
    "StaticPathProvider",
    "UUIDFilenameProvider",
    "YMDPathProvider",
    "ConfigSignal",
    "HintedSignal",
    "StandardReadable",
    "StandardReadableFormat",
    "Settings",
    "SettingsProvider",
    "Signal",
    "SignalConnector",
    "SignalR",
    "SignalRW",
    "SignalW",
    "SignalX",
    "observe_value",
    "observe_signals_value",
    "set_and_wait_for_value",
    "set_and_wait_for_other_value",
    "soft_signal_r_and_setter",
    "soft_signal_rw",
    "wait_for_value",
    "walk_rw_signals",
    "Array1D",
    "DTypeScalar_co",
    "SignalBackend",
    "make_datakey",
    "StrictEnum",
    "SubsetEnum",
    "SignalDatatype",
    "SignalDatatypeT",
    "SignalMetadata",
    "SoftSignalBackend",
    "AsyncStatus",
    "WatchableAsyncStatus",
    "DEFAULT_TIMEOUT",
    "CalculatableTimeout",
    "Callback",
    "LazyMock",
    "CALCULATE_TIMEOUT",
    "NotConnected",
    "Reference",
    "Table",
    "T",
    "WatcherUpdate",
    "gather_dict",
    "get_dtype",
    "get_enum_cls",
    "get_unique",
    "in_micros",
    "wait_for_connection",
    "completed_status",
    "YamlSettingsProvider",
    "Watcher",
]
