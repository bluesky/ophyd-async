from enum import Enum
from math import nan
from typing import Callable, Dict, Tuple

from ophyd_async.epics.areadetector.drivers import ADBase
from ophyd_async.epics.areadetector.utils import (
    ad_r,
    ad_rw,
)


class ADAravisTriggerMode(str, Enum):
    """GigEVision GenICAM standard: on=externally triggered"""

    on = "On"
    off = "Off"


class ADAravisTriggerSource(str, Enum):
    # While not all enum elements may be physically supported by the hardware,
    # DB record templates suggest they are valid options for underlying record
    # cite: https://github.com/areaDetector/ADGenICam/tree/master/GenICamApp/Db
    # (e.g. Mako G-125B TriggerSource has Line1-4)
    freerun = "Freerun"
    fixed_rate = "FixedRate"
    software = "Software"
    action_0 = "Action0"
    action_1 = "Action1"
    # Externally triggered on GPIO N
    line_1 = "Line1"
    line_2 = "Line2"
    line_3 = "Line3"
    line_4 = "Line4"


def _reverse_lookup(model_deadtimes: Dict[float, Tuple[str, ...]]) -> Callable[[str], float]:
    def inner(pixel_format: str) -> float:
        for deadtime, pixel_formats in model_deadtimes.items():
            if pixel_format in pixel_formats:
                return deadtime
        return nan

    return inner


_deadtimes: Dict[str, Callable[[str], float]] = {
    # cite: https://cdn.alliedvision.com/fileadmin/content/documents/products/cameras/Manta/techman/Manta_TechMan.pdf retrieved 2024-04-05
    "Manta G-125": lambda _: 63e-6,
    "Manta G-145": lambda _: 106e-6,
    "Manta G-235": _reverse_lookup(
        {
            118e-6: (
                "Mono8",
                "Mono12Packed",
                "BayerRG8",
                "BayerRG12",
                "BayerRG12Packed",
                "YUV411Packed",
            ),
            256e-6: ("Mono12", "BayerRG12", "YUV422Packed"),
            390e-6: ("RGB8Packed", "BGR8Packed", "YUV444Packed"),
        }
    ),
    "Manta G-895": _reverse_lookup(
        {
            404e-6: (
                "Mono8",
                "Mono12Packed",
                "BayerRG8",
                "BayerRG12Packed",
                "YUV411Packed",
            ),
            542e-6: ("Mono12", "BayerRG12", "YUV422Packed"),
            822e-6: ("RGB8Packed", "BGR8Packed", "YUV444Packed"),
        }
    ),
    "Manta G-2460": _reverse_lookup(
        {
            979e-6: (
                "Mono8",
                "Mono12Packed",
                "BayerRG8",
                "BayerRG12Packed",
                "YUV411Packed",
            ),
            1304e-6: ("Mono12", "BayerRG12", "YUV422Packed"),
            1961e-6: ("RGB8Packed", "BGR8Packed", "YUV444Packed"),
        }
    ),
    # cite: https://cdn.alliedvision.com/fileadmin/content/documents/products/cameras/various/appnote/GigE/GigE-Cameras_AppNote_PIV-Min-Time-Between-Exposures.pdf retrieved 2024-04-05
    "Manta G-609": lambda _: 47e-6,
    # cite: https://cdn.alliedvision.com/fileadmin/content/documents/products/cameras/Mako/techman/Mako_TechMan_en.pdf retrieved 2024-04-05
    "Mako G-040": _reverse_lookup(
        {
            101e-6: (
                "Mono8",
                "Mono12Packed",
                "BayerRG8",
                "BayerRG12Packed",
                "YUV411Packed",
            ),
            140e-6: ("Mono12", "BayerRG12", "YUV422Packed"),
            217e-6: ("RGB8Packed", "BGR8Packed", "YUV444Packed"),
        }
    ),
    "Mako G-125": lambda _: 70e-6,
    # Assume 12 bits: 10 bits = 275e-6
    "Mako G-234": _reverse_lookup(
        {
            356e-6: (
                "Mono8",
                "BayerRG8",
                "BayerRG12",
                "BayerRG12Packed",
                "YUV411Packed",
                "YUV422Packed",
            ),
            # Assume 12 bits: 10 bits = 563e-6
            726e-6: ("RGB8Packed", "BRG8Packed", "YUV444Packed"),
        }
    ),
    "Mako G-507": _reverse_lookup(
        {
            270e-6: (
                "Mono8",
                "Mono12Packed",
                "BayerRG8",
                "BayerRG12Packed",
                "YUV411Packed",
            ),
            363e-6: ("Mono12", "BayerRG12", "YUV422Packed"),
            554e-6: ("RGB8Packed", "BGR8Packed", "YUV444Packed"),
        }
    ),
}


class ADAravisDriver(ADBase):
    # If instantiating a new instance, ensure it is supported in the _deadtimes dict
    """Generic Driver supporting the Manta and Mako drivers.
    Requires driver firmware up to date such that the Model_RBV is of the form "^(Mako|Manta) (model)$"
    Fetches deadtime prior to use in a Streaming scan.
    """

    def __init__(self, prefix: str, name: str = "") -> None:
        self.trigger_mode = ad_rw(ADAravisTriggerMode, prefix + "TriggerMode")
        self.trigger_source = ad_rw(ADAravisTriggerSource, prefix + "TriggerSource")
        self.model = ad_r(str, prefix + "Model")
        self.pixel_format = ad_rw(str, prefix + "PixelFormat")
        super().__init__(prefix, name=name)

    async def _fetch_deadtime(self) -> float:
        # All known in-use version B/C have same deadtime as non-B/C
        model: str = (await self.model.get_value()).removesuffix("B").removesuffix("C")
        pixel_format: str = await self.pixel_format.get_value()
        return _deadtimes.get(model, lambda _: nan)(pixel_format)
