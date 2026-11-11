import pytest

from ophyd_async.core import (
    Device,
    StaticPathProvider,
    TriggerInfo,
    get_mock,
    init_devices,
    set_mock_value,
    soft_signal_rw,
)
from ophyd_async.epics import adcore


@pytest.mark.parametrize(
    "factory",
    [
        adcore.ADWriterFactory.hdf,
        adcore.ADWriterFactory.jpeg,
        adcore.ADWriterFactory.tiff,
    ],
)
@pytest.mark.parametrize("hinted", [True, False])
def test_writer_image_hints(static_path_provider: StaticPathProvider, factory, hinted):
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    stats = adcore.NDStatsIO("PREFIX:STAT:")
    det = adcore.AreaDetector(
        driver,
        "PREFIX:",
        factory(static_path_provider, datakey_suffix="-image", hinted=hinted),
        plugins={"stats": stats},
        name="det",
    )
    assert det.hints == {"fields": ["det-image"] if hinted else []}
    det.add_detector_logics(adcore.PluginSignalDataLogic(driver, stats.total))
    assert det.hints == {
        "fields": (["det-image"] if hinted else []) + ["det-stats-total"]
    }


@pytest.mark.parametrize(
    "factory",
    [
        adcore.ADWriterFactory.hdf,
        adcore.ADWriterFactory.jpeg,
        adcore.ADWriterFactory.tiff,
    ],
)
def test_writer_image_hints_enabled_by_default(
    static_path_provider: StaticPathProvider, factory
):
    det = adcore.AreaDetector(
        adcore.ADBaseIO("PREFIX:DRV:"),
        "PREFIX:",
        factory(static_path_provider),
        name="det",
    )
    assert det.hints == {"fields": ["det"]}


class DetectorRig(Device):
    def __init__(self, det: adcore.AreaDetector) -> None:
        self.det = det
        self.flag = soft_signal_rw(int)
        super().__init__("rig")


async def test_init_devices_mock_area_detector_mocks_plugins_too(
    static_path_provider: StaticPathProvider,
):
    async with init_devices(mock={adcore.AreaDetector: True}):
        rig = DetectorRig(
            adcore.AreaDetector(
                adcore.ADBaseIO("PREFIX:DRV:"),
                "PREFIX:",
                adcore.ADWriterFactory.hdf(static_path_provider),
                plugins={"stats": adcore.NDStatsIO("PREFIX:STAT:")},
            )
        )

    # The plugins are mocked with the detector, the rest of the rig is real
    set_mock_value(rig.det.get_plugin("stats", adcore.NDStatsIO).total, 3.0)
    with pytest.raises(RuntimeError, match="not connected in mock mode"):
        set_mock_value(rig.flag, 1)
    # Calls on the mocks are nested under the real parent's mock
    await rig.det.driver.acquire_time.set(0.5)
    get_mock(rig).det.driver.acquire_time.put.assert_called_once_with(0.5)


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


def test_get_plugin_missing_raises_attribute_error():
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    det = adcore.AreaDetector(driver=driver, name="det")
    with pytest.raises(AttributeError, match="^det has no plugin named 'hdf'$"):
        det.get_plugin("hdf")


def test_get_plugin_wrong_type_raises_type_error():
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    plugins = {"stats": adcore.NDStatsIO("PREFIX:STAT:")}
    det = adcore.AreaDetector(driver=driver, plugins=plugins, name="det")

    assert isinstance(det.get_plugin("stats", adcore.NDStatsIO), adcore.NDStatsIO)

    with pytest.raises(
        TypeError,
        match=r"^Expected det\.stats to be a NDPluginFileIO, got NDStatsIO$",
    ):
        det.get_plugin("stats", adcore.NDPluginFileIO)


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
    set_mock_value(det.get_plugin("hdf", adcore.NDFileHDF5IO).file_path_exists, True)
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
    set_mock_value(det.get_plugin("hdf", adcore.NDFileHDF5IO).file_path_exists, True)
    with pytest.raises(
        RuntimeError,
        match=r"^Unsupported ColorMode Bayer! Only Mono and RGB1 are supported\.$",
    ):
        await det.prepare(TriggerInfo())
