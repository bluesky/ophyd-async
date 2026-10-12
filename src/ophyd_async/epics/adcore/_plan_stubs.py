from collections.abc import Sequence

import bluesky.plan_stubs as bps
from bluesky.utils import plan

from ._detector import AreaDetector
from ._io import NDArrayBaseIO, NDStatsIO
from ._ndattribute import (
    NDAttributeDataType,
    NDAttributeParam,
    NDAttributePv,
    ndattributes_to_xml,
)


@plan
def setup_ndattributes(
    device: NDArrayBaseIO,
    ndattributes: Sequence[NDAttributeParam | NDAttributePv],
):
    xml = ndattributes_to_xml(ndattributes)
    yield from bps.abs_set(
        device.nd_attributes_file,
        xml,
        wait=True,
    )


@plan
def setup_ndstats_sum(detector: AreaDetector, stats_name: str = "stats"):
    """Set up nd stats sum nd attribute for a detector."""
    stats = detector.get_plugin(stats_name, NDStatsIO)
    yield from (
        setup_ndattributes(
            stats,
            [
                NDAttributeParam(
                    name=f"{detector.name}-sum",
                    param="TOTAL",
                    datatype=NDAttributeDataType.DOUBLE,
                    description="Sum of the array",
                )
            ],
        )
    )
