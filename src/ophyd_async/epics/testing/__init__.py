from pathlib import Path

from ._devices import (
    CA_PVA_RECORDS,
    PVA_RECORDS,
    EpicsTestCaDevice,
    EpicsTestEnum,
    EpicsTestPvaDevice,
    EpicsTestPviDevice,
    EpicsTestPviDisagreeingSuffixDevice,
    EpicsTestSubsetEnum,
    EpicsTestSupersetEnum,
    EpicsTestTable,
)
from ._launch import generate_random_pv_prefix, start_ioc
from ._pvi_nested_devices import (
    PVI_NESTED_RECORDS,
    EpicsTestPviAgreeingPvSuffixDevice,
    EpicsTestPviDisagreeingDeviceDevice,
    EpicsTestPviLeafDevice,
    EpicsTestPviMapDevice,
    EpicsTestPviMapOverVectorDevice,
    EpicsTestPviNestedDevice,
    EpicsTestPviNestedDeviceMissingChild,
)

#: Path to the standalone script serving this package's fixed test IOC
#: catalog (`ca:`/`pva:`/`nested:`) - pass to `start_ioc`. A plain path
#: constant rather than a module reference so nothing needs to import
#: `_ioc.py` (or reach into a private attribute) just to launch it.
IOC = Path(__file__).parent / "_ioc.py"

__all__ = [
    "CA_PVA_RECORDS",
    "IOC",
    "PVA_RECORDS",
    "PVI_NESTED_RECORDS",
    "EpicsTestCaDevice",
    "EpicsTestEnum",
    "EpicsTestSubsetEnum",
    "EpicsTestSupersetEnum",
    "EpicsTestPvaDevice",
    "EpicsTestPviAgreeingPvSuffixDevice",
    "EpicsTestPviDevice",
    "EpicsTestPviDisagreeingDeviceDevice",
    "EpicsTestPviDisagreeingSuffixDevice",
    "EpicsTestPviLeafDevice",
    "EpicsTestPviMapDevice",
    "EpicsTestPviMapOverVectorDevice",
    "EpicsTestPviNestedDevice",
    "EpicsTestPviNestedDeviceMissingChild",
    "EpicsTestTable",
    "generate_random_pv_prefix",
    "start_ioc",
]
