from enum import Enum
from typing import Optional, Type
from xml.etree import cElementTree as ET

from ophyd_async.core import DEFAULT_TIMEOUT, SignalR, SignalRW, T, wait_for_value

from ..signal.signal import epics_signal_r, epics_signal_rw


def ad_rw(datatype: Type[T], prefix: str) -> SignalRW[T]:
    return epics_signal_rw(datatype, prefix + "_RBV", prefix)


def ad_r(datatype: Type[T], prefix: str) -> SignalR[T]:
    return epics_signal_r(datatype, prefix + "_RBV")


class FileWriteMode(str, Enum):
    single = "Single"
    capture = "Capture"
    stream = "Stream"


class ImageMode(str, Enum):
    single = "Single"
    multiple = "Multiple"
    continuous = "Continuous"


class NDAttributeDataType(str, Enum):
    INT = "INT"
    DOUBLE = "DOUBLE"
    STRING = "STRING"


class NDAttributesXML:
    """Helper to make NDAttributesFile XML for areaDetector"""

    _dbr_types = {
        None: "DBR_NATIVE",
        NDAttributeDataType.INT: "DBR_LONG",
        NDAttributeDataType.DOUBLE: "DBR_DOUBLE",
        NDAttributeDataType.STRING: "DBR_STRING",
    }

    def __init__(self):
        self._root = ET.Element("Attributes")

    def add_epics_pv(
        self,
        name: str,
        pv: str,
        datatype: Optional[NDAttributeDataType] = None,
        description: str = "",
    ):
        """Add a PV to the attribute list

        Args:
            name: The attribute name
            pv: The pv to get from
            datatype: An override datatype, otherwise will use native EPICS type
            description: A description that appears in the HDF file as an attribute
        """
        ET.SubElement(
            self._root,
            "Attribute",
            name=name,
            type="EPICS_PV",
            source=pv,
            datatype=self._dbr_types[datatype],
            description=description,
        )

    def add_param(
        self,
        name: str,
        param: str,
        datatype: NDAttributeDataType,
        addr: int = 0,
        description: str = "",
    ):
        """Add a driver or plugin parameter to the attribute list

        Args:
            name: The attribute name
            param: The parameter string as seen in the INP link of the record
            datatype: The datatype of the parameter
            description: A description that appears in the HDF file as an attribute
        """
        ET.SubElement(
            self._root,
            "Attribute",
            name=name,
            type="PARAM",
            source=param,
            addr=str(addr),
            datatype=datatype.value,
            description=description,
        )

    def __str__(self) -> str:
        """Output the XML pretty printed"""
        ET.indent(self._root, space="    ", level=0)
        return ET.tostring(self._root, xml_declaration=True, encoding="utf-8").decode()


async def stop_busy_record(
    signal: SignalRW[T],
    value: T,
    timeout: float = DEFAULT_TIMEOUT,
    status_timeout: Optional[float] = None,
) -> None:
    await signal.set(value, wait=False, timeout=status_timeout)
    await wait_for_value(signal, value, timeout=timeout)
