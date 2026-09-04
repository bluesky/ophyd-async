import pytest

from ophyd_async.core import (
    StaticPathProvider,
    TriggerInfo,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore

# ---------------------------------------------------------------------------
# AreaDetector.__init__ guards
# ---------------------------------------------------------------------------


def test_area_detector_requires_prefix_when_factories_given(
    static_path_provider: StaticPathProvider,
):
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    with pytest.raises(
        ValueError,
        match="^prefix is required when writer_factories are given$",
    ):
        adcore.AreaDetector(
            driver,
            None,
            adcore.ADWriterFactory.hdf(static_path_provider),
            name="det",
        )


def test_area_detector_rejects_duplicate_writer_names(
    static_path_provider: StaticPathProvider,
):
    driver = adcore.ADBaseIO("PREFIX:DRV:")

    with pytest.raises(
        ValueError,
        match=r"^Duplicate writer_name\(s\) in writer_factories: \['hdf'\]$",
    ):
        adcore.AreaDetector(
            driver,
            "PREFIX:",
            adcore.ADWriterFactory.hdf(static_path_provider, writer_name="hdf"),
            adcore.ADWriterFactory.hdf(static_path_provider, writer_name="hdf"),
            name="det",
        )


# ---------------------------------------------------------------------------
# AreaDetector.get_plugin guards
# ---------------------------------------------------------------------------


def test_get_plugin_by_name_missing_raises_attribute_error():
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    det = adcore.AreaDetector(driver=driver, name="det")
    with pytest.raises(AttributeError, match="^det has no plugin named 'hdf'$"):
        det.get_plugin_by_name("hdf")


def test_get_plugin_by_name_wrong_type_raises_type_error():
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    plugins = {"stats": adcore.NDStatsIO("PREFIX:STAT:")}
    det = adcore.AreaDetector(driver=driver, plugins=plugins, name="det")

    assert isinstance(
        det.get_plugin_by_name("stats", adcore.NDStatsIO), adcore.NDStatsIO
    )

    with pytest.raises(
        TypeError,
        match=r"^Expected det\.stats to be a NDPluginFileIO, got NDStatsIO$",
    ):
        det.get_plugin_by_name("stats", adcore.NDPluginFileIO)

@pytest.fixture
async def ad_with_stats_and_roi():
    async with init_devices(mock=True):
        stats = adcore.NDStatsIO("PREFIX:STAT:")
        roi = adcore.NDROIIO("PREFIX:ROI:")
        det = adcore.AreaDetector(
            adcore.ADBaseIO("PREFIX:DRV:"),
            plugins={
                "stats": stats,
                "roi": roi,
            },
            name="det",
        )
    return det, stats, roi


async def test_get_plugin_by_port_name_returns_matching_plugin(ad_with_stats_and_roi):
    det, stats, roi = ad_with_stats_and_roi
    set_mock_value(stats.port_name, "STATS_PORT")
    set_mock_value(roi.port_name, "ROI_PORT")

    assert (
        await det.get_plugin_by_port_name("STATS_PORT", adcore.NDStatsIO)
    ) is getattr(det, "stats")
    assert (await det.get_plugin_by_port_name("ROI_PORT")) is getattr(det, "roi")


async def test_get_plugin_by_port_name_missing_raises_value_error(ad_with_stats_and_roi):
    det, stats, roi = ad_with_stats_and_roi
    set_mock_value(stats.port_name, "STATS_PORT")

    with pytest.raises(ValueError, match="^No plugin found with port name 'MISSING'$"):
        await det.get_plugin_by_port_name("MISSING")


async def test_get_plugins_by_type_yields_matching_plugins(ad_with_stats_and_roi):
    det, stats, roi = ad_with_stats_and_roi

    assert list(det.get_plugins_by_type(adcore.NDStatsIO)) == [det.stats]

    all_plugins = list(det.get_plugins_by_type(adcore.NDPluginBaseIO))
    assert det.stats in all_plugins
    assert det.roi in all_plugins
    assert len(all_plugins) == 2


# ---------------------------------------------------------------------------
# get_ndarray_resource_info error paths
# ---------------------------------------------------------------------------


async def test_get_ndarray_resource_info_undefined_datatype(
    static_path_provider: StaticPathProvider,
):
    async with init_devices(mock=True):
        det = adcore.AreaDetector(
            adcore.ADBaseIO("PREFIX:DRV:"),
            "PREFIX:",
            adcore.ADWriterFactory.hdf(static_path_provider),
            name="det",
        )
    set_mock_value(det.driver.data_type, adcore.ADBaseDataType.UNDEFINED)
    set_mock_value(
        det.get_plugin_by_name("hdf", adcore.NDFileHDF5IO).file_path_exists, True
    )
    with pytest.raises(
        ValueError,
        match=r"^mock\+ca://PREFIX:DRV:DataType_RBV is blank, this is not supported$",
    ):
        await det.prepare(TriggerInfo())


async def test_get_ndarray_resource_info_unsupported_color_mode(
    static_path_provider: StaticPathProvider,
):
    async with init_devices(mock=True):
        det = adcore.AreaDetector(
            adcore.ADBaseIO("PREFIX:DRV:"),
            "PREFIX:",
            adcore.ADWriterFactory.hdf(static_path_provider),
            name="det",
        )
    set_mock_value(det.driver.color_mode, adcore.ADBaseColorMode.BAYER)
    set_mock_value(
        det.get_plugin_by_name("hdf", adcore.NDFileHDF5IO).file_path_exists, True
    )
    with pytest.raises(
        RuntimeError,
        match=r"^Unsupported ColorMode Bayer! Only Mono and RGB1 are supported\.$",
    ):
        await det.prepare(TriggerInfo())
