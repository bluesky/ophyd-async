from enum import Enum

from ophyd_async.core import Device
from ophyd_async.epics.signal import epics_signal_rw

from ..utils import ad_r, ad_rw


class Callback(str, Enum):
    Enable = "Enable"
    Disable = "Disable"


class NDArrayBase(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.unique_id = ad_r(int, prefix + "UniqueId")
        self.nd_attributes_file = epics_signal_rw(str, prefix + "NDAttributesFile")
        super().__init__(name)


class NDPluginBase(NDArrayBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nd_array_port = ad_rw(str, prefix + "NDArrayPort")
        self.enable_callback = ad_rw(Callback, prefix + "EnableCallbacks")
        self.nd_array_address = ad_rw(int, prefix + "NDArrayAddress")
        super().__init__(prefix, name)


class NDPluginStats(NDPluginBase):
    """Plugin for computing statistics from an image or region of interest within an image.
    Each boolean signal enables or disables all signals in the appropriate Enum class.
    The enum signals may used in the ScalarSignals kwargs of a HDFWriter, and are also read-only
    signals on the plugin.
    """

    def __init__(self, prefix: str, name: str = "") -> None:
        self.statistics = epics_signal_rw(bool, prefix + "ComputeStatistics")
        self.statistics_background_width = epics_signal_rw(int, prefix + "BgdWidth")
        self.centroid = epics_signal_rw(bool, prefix + "ComputeCentroid")
        self.centroid_threshold = epics_signal_rw(float, prefix + "CentroidThreshold")
        # self.profiles = epics_signal_rw(bool, prefix + "ComputeProfiles")
        # self.profile_size_x = epics_signal_rw(int, prefix + "ProfileSizeX")
        # self.profile_cursor_x = epics_signal_rw(int, prefix + "CursorX")
        # self.profile_size_y = epics_signal_rw(int, prefix + "ProfileSizeY")
        # self.profile_cursor_y = epics_signal_rw(int, prefix + "CursorY")
        # self.histogram = epics_signal_rw(bool, prefix + "ComputeHistogram")
        # self.histogram_max = epics_signal_rw(float, prefix + "HistMax")
        # self.histogram_min = epics_signal_rw(float, prefix + "HistMin")
        # self.histogram_size = epics_signal_rw(int, prefix + "HistSize")
        super().__init__(prefix, name)

    class StatisticsSignal(str, Enum):
        """Scalar signals that are enabled when self.statistics is set to True"""

        MIN_VALUE = "StatsMinValue"
        MAX_VALUE = "StatsMaxValue"
        TOTAL = "StatsTotal"
        NET = "StatsNet"
        MIN_X = "StatsMinX"
        MIN_Y = "StatsMinY"
        MAX_X = "StatsMaxX"
        MAX_Y = "StatsMaxY"
        SIGMA_VALUE = "StatsSigma"
        
    class CentroidSignal(str, Enum):
        TOTAL = "CentroidTotal"
        X_VALUE = "CentroidX"
        Y_VALUE = "CentroidY"
        SIGMA_X = "SigmaX"
        SIGMA_Y = "SigmaY"
        SIGMA_XY = "SigmaXY"
        SKEW_X = "SkewX"
        SKEW_Y = "SkewX"
        KURTOSIS_X = "KurtosisX"
        KURTOSIS_Y = "KurtosisY"
        ECCENTRICITY = "Eccentricity"
        ORIENTATION = "Orientation"