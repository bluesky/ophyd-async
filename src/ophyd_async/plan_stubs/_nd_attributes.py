from collections.abc import Sequence

import bluesky.plan_stubs as bps

from ophyd_async.epics import adcore


def setup_ndattributes(
    device: adcore.NDArrayBaseIO,
    ndattributes: Sequence[adcore.NDAttributeParam | adcore.NDAttributePv],
):
    xml = adcore.ndattributes_to_xml(ndattributes)
    yield from bps.abs_set(
        device.nd_attributes_file,
        xml,
        wait=True,
    )


def setup_ndstats_sum(detector: adcore.AreaDetector, stats_name: str = "stats"):
    """Set up nd stats sum nd attribute for a detector."""
    stats = detector.get_plugin(stats_name, adcore.NDStatsIO)
    yield from (
        setup_ndattributes(
            stats,
            [
                adcore.NDAttributeParam(
                    name=f"{detector.name}-sum",
                    param="TOTAL",
                    datatype=adcore.NDAttributeDataType.DOUBLE,
                    description="Sum of the array",
                )
            ],
        )
    )
