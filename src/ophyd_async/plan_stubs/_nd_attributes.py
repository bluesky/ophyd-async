from collections.abc import Sequence

import bluesky.plan_stubs as bps

from ophyd_async.epics.adcore import (
    AreaDetector,
    NDArrayBaseIO,
    NDAttributeDataType,
    NDAttributeParam,
    NDAttributePv,
    NDFileHDFIO,
    ndattributes_to_xml,
)


def setup_ndattributes(
    device: NDArrayBaseIO, ndattributes: Sequence[NDAttributeParam | NDAttributePv]
):
    xml = ndattributes_to_xml(ndattributes)
    yield from bps.abs_set(
        device.nd_attributes_file,
        xml,
        wait=True,
    )


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
