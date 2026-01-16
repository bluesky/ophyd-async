import pytest

from ophyd_async.epics import adcore


def test_get_plugin_type_checking():
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    plugins = {
        "stats": adcore.NDStatsIO("PREFIX:STAT:"),
    }
    det = adcore.AreaDetector(driver=driver, plugins=plugins, name="det")

    # Correct type
    stats_plugin = det.get_plugin("stats", adcore.NDStatsIO)
    assert isinstance(stats_plugin, adcore.NDStatsIO)

    # Incorrect type
    with pytest.raises(
        TypeError, match=r"Expected det\.stats to be a .*NDPluginFileIO.*"
    ):
        det.get_plugin("stats", adcore.NDPluginFileIO)
