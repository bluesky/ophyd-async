from collections.abc import Sequence

import bluesky.plan_stubs as bps
from bluesky.utils import plan

from ._core_detector import AreaDetector
from ._core_io import NDArrayBaseIO, NDFileHDFIO
from ._utils import (
    NDAttributeDataType,
    NDAttributeParam,
    NDAttributePv,
    ndattributes_to_xml,
)


@plan
def setup_ndattributes(
    device: NDArrayBaseIO, ndattributes: Sequence[NDAttributeParam | NDAttributePv]
):
    xml = ndattributes_to_xml(ndattributes)
    yield from bps.abs_set(
        device.nd_attributes_file,
        xml,
        wait=True,
    )


@plan
def setup_ndstats_sum(detector: AreaDetector):
    """Set up nd stats sum nd attribute for a detector."""
    hdf = getattr(detector, "fileio", None)
    if not isinstance(hdf, NDFileHDFIO):
        msg = (
            f"Expected {detector.name} to have 'fileio' attribute that is an "
            f"NDFileHDFIO, got {hdf}"
        )
        raise TypeError(msg)
    yield from (
        setup_ndattributes(
            hdf,
            [
                NDAttributeParam(
                    name=f"{detector.name}-sum",
                    param="NDPluginStatsTotal",
                    datatype=NDAttributeDataType.DOUBLE,
                    description="Sum of the array",
                )
            ],
        )
    )
