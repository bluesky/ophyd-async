"""The building blocks for making devices."""

from ._derived_signal import (
    DerivedSignalFactory,
    derived_signal_r,
    derived_signal_rw,
    derived_signal_w,
)
from ._derived_signal_backend import Transform
from ._detector import (
    DetectorController,
    DetectorTrigger,
    DetectorWriter,
    StandardDetector,
    TriggerInfo,
)
from ._device import Device, DeviceConnector, DeviceVector, init_devices
from ._device_filler import DeviceFiller
from ._flyer import FlyerController, FlyMotorInfo, StandardFlyer
from ._hdf_dataset import HDFDatasetDescription, HDFDocumentComposer
from ._log import config_ophyd_async_logging
from ._mock_signal_backend import MockSignalBackend
from ._protocol import AsyncConfigurable, AsyncReadable, AsyncStageable, Watcher
from ._providers import (
    AutoIncrementFilenameProvider,
    AutoIncrementingPathProvider,
    DatasetDescriber,
    FilenameProvider,
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
    Ignore,
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
    walk_config_signals,
    walk_devices,
    walk_rw_signals,
    walk_signal_sources,
)
from ._signal_backend import (
    Array1D,
    DTypeScalar_co,
    Primitive,
    SignalBackend,
    SignalDatatype,
    SignalDatatypeT,
    SignalMetadata,
    make_datakey,
)
from ._soft_signal_backend import SoftSignalBackend
from ._status import AsyncStatus, WatchableAsyncStatus, completed_status
from ._table import Table
from ._utils import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    CalculatableTimeout,
    Callback,
    ConfinedModel,
    EnumTypes,
    LazyMock,
    NotConnected,
    Reference,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    WatcherUpdate,
    error_if_none,
    gather_dict,
    get_dtype,
    get_enum_cls,
    get_unique,
    in_micros,
    wait_for_connection,
)
from ._yaml_settings import YamlSettingsProvider

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
    "SupersetEnum",
    "EnumTypes",
    "Table",
    "SignalMetadata",
    "Primitive",
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
    "walk_config_signals",
    "walk_devices",
    "walk_signal_sources",
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
    "DatasetDescriber",
    "HDFDatasetDescription",
    "HDFDocumentComposer",
    # Flyer
    "StandardFlyer",
    "FlyMotorInfo",
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
    "ConfinedModel",
    "NotConnected",
    "Reference",
    "error_if_none",
    "gather_dict",
    "get_dtype",
    "get_enum_cls",
    "get_unique",
    "in_micros",
    "make_datakey",
    "wait_for_connection",
    "Ignore",
    # Derived signal
    "derived_signal_r",
    "derived_signal_rw",
    "derived_signal_w",
    "Transform",
    "DerivedSignalFactory",
    # Back compat - delete before 1.0
    "ConfigSignal",
    "HintedSignal",
]
