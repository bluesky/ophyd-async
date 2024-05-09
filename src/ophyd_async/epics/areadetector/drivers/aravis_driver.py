from enum import Enum
from typing import Callable, Dict, Literal, Optional, Tuple

from ophyd_async.epics.areadetector.drivers import ADBase
from ophyd_async.epics.signal.signal import epics_signal_r, epics_signal_rw_rbv


class AravisTriggerMode(str, Enum):
    """GigEVision GenICAM standard: on=externally triggered"""

    on = "On"
    off = "Off"


"""A minimal set of TriggerSources that must be supported by the underlying record.
    To enable hardware triggered scanning, line_N must support each N in GPIO_NUMBER.
    To enable software triggered scanning, freerun must be supported.
    Other enumerated values may or may not be preset.
    To prevent requiring one Enum class per possible configuration, we set as this Enum
    but read from the underlying signal as a str.
    """
AravisTriggerSource = Literal["Freerun", "Line1", "Line2", "Line3", "Line4"]


def _reverse_lookup(
    model_deadtimes: Dict[float, Tuple[str, ...]],
) -> Callable[[str], float]:
    def inner(pixel_format: str, model_name: str) -> float:
        for deadtime, pixel_formats in model_deadtimes.items():
            if pixel_format in pixel_formats:
                return deadtime
        raise ValueError(
            f"Model {model_name} does not have a defined deadtime "
            f"for pixel format {pixel_format}"
        )

    return inner


_deadtimes: Dict[str, Callable[[str, str], float]] = {
    # cite: https://cdn.alliedvision.com/fileadmin/content/documents/products/cameras/Manta/techman/Manta_TechMan.pdf retrieved 2024-04-05  # noqa: E501
    "Manta G-125": lambda _, __: 63e-6,
    "Manta G-145": lambda _, __: 106e-6,
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
    # cite: https://cdn.alliedvision.com/fileadmin/content/documents/products/cameras/various/appnote/GigE/GigE-Cameras_AppNote_PIV-Min-Time-Between-Exposures.pdf retrieved 2024-04-05  # noqa: E501
    "Manta G-609": lambda _, __: 47e-6,
    # cite: https://cdn.alliedvision.com/fileadmin/content/documents/products/cameras/Mako/techman/Mako_TechMan_en.pdf retrieved 2024-04-05  # noqa: E501
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
    "Mako G-125": lambda _, __: 70e-6,
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


class AravisDriver(ADBase):
    # If instantiating a new instance, ensure it is supported in the _deadtimes dict
    """Generic Driver supporting the Manta and Mako drivers.
    Fetches deadtime prior to use in a Streaming scan.
    Requires driver firmware up to date:
    - Model_RBV must be of the form "^(Mako|Manta) (model)$"
    """

    def __init__(self, prefix: str, name: str = "") -> None:
        self.trigger_mode = epics_signal_rw_rbv(
            AravisTriggerMode, prefix + "TriggerMode"
        )
        self.trigger_source = epics_signal_rw_rbv(str, prefix + "TriggerSource")
        self.model = epics_signal_r(str, prefix + "Model_RBV")
        self.pixel_format = epics_signal_rw_rbv(str, prefix + "PixelFormat")
        self.dead_time: Optional[float] = None
        super().__init__(prefix, name=name)

    async def fetch_deadtime(self) -> None:
        # All known in-use version B/C have same deadtime as non-B/C
        model: str = (await self.model.get_value()).removesuffix("B").removesuffix("C")
        if model not in _deadtimes:
            raise ValueError(f"Model {model} does not have defined deadtimes")
        pixel_format: str = await self.pixel_format.get_value()
        self.dead_time = _deadtimes.get(model)(pixel_format, model)
