"""The building blocks for making devices."""

from typing import TYPE_CHECKING

from ._detector import (
    DetectorController,
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
    WatcherUpdate,
    gather_dict,
    get_dtype,
    get_enum_cls,
    get_unique,
    in_micros,
    wait_for_connection,
)
from ._yaml_settings import YamlSettingsProvider

# Docstrings must be added here for sphinx
if not TYPE_CHECKING:
    SignalDatatypeT = SignalDatatypeT
    """The supported `Signal` datatypes:

    - A python primitive `bool`, `int`, `float`, `str`
    - A `StrictEnum` or `SubsetEnum` subclass
    - A fixed datatype `Array1D` of numpy bool, signed and unsigned integers or float
    - A `np.ndarray` which can change dimensions and datatype at runtime
    - A `Sequence` of `str`
    - A `Sequence` of `StrictEnum` or `SubsetEnum` subclass
    - A `Table` subclass
    """


__all__ = [
    # Device
    "Device",
    "DeviceConnector",
    "DeviceFiller",
    "DeviceVector",
    "init_devices",
    # Protocols
    "AsyncReadable",
    "AsyncConfigurable",
    "AsyncStageable",
    "Watcher",
    # Status
    "AsyncStatus",
    "WatchableAsyncStatus",
    "WatcherUpdate",
    "completed_status",
    # Signal
    "Signal",
    "SignalR",
    "SignalW",
    "SignalRW",
    "SignalX",
    "SignalBackend",
    "SignalConnector",
    # Signal Types
    "SignalDatatype",
    "SignalDatatypeT",
    "DTypeScalar_co",
    "Array1D",
    "StrictEnum",
    "SubsetEnum",
    "Table",
    "SignalMetadata",
    # Soft signal
    "SoftSignalBackend",
    "soft_signal_r_and_setter",
    "soft_signal_rw",
    # Mock signal
    "LazyMock",
    "MockSignalBackend",
    # Signal utilities
    "observe_value",
    "observe_signals_value",
    "wait_for_value",
    "set_and_wait_for_value",
    "set_and_wait_for_other_value",
    "walk_rw_signals",
    # Readable
    "StandardReadable",
    "StandardReadableFormat",
    # Detector
    "StandardDetector",
    "TriggerInfo",
    "DetectorTrigger",
    "DetectorController",
    "DetectorWriter",
    # Path
    "PathInfo",
    "PathProvider",
    "StaticPathProvider",
    "AutoIncrementingPathProvider",
    "YMDPathProvider",
    "FilenameProvider",
    "StaticFilenameProvider",
    "AutoIncrementFilenameProvider",
    "UUIDFilenameProvider",
    # Datatset
    "NameProvider",
    "DatasetDescriber",
    "HDFDataset",
    "HDFFile",
    # Flyer
    "StandardFlyer",
    "FlyerController",
    # Settings
    "Settings",
    "SettingsProvider",
    "YamlSettingsProvider",
    # Utils
    "config_ophyd_async_logging",
    "CALCULATE_TIMEOUT",
    "CalculatableTimeout",
    "DEFAULT_TIMEOUT",
    "Callback",
    "NotConnected",
    "Reference",
    "gather_dict",
    "get_dtype",
    "get_enum_cls",
    "get_unique",
    "in_micros",
    "make_datakey",
    "wait_for_connection",
    # Back compat - delete before 1.0
    "ConfigSignal",
    "HintedSignal",
]
