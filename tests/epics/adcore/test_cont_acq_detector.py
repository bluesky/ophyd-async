import pytest

from ophyd_async.core import DetectorTrigger, PathProvider, TriggerInfo, init_devices
from ophyd_async.epics import adcore
from ophyd_async.testing import set_mock_value


@pytest.fixture
def cont_acq_det(ad_standard_det_factory):
    det = ad_standard_det_factory(adcore.ContAcqAreaDetector)

    # Set a few additional settings specific to cont acq detectors
    set_mock_value(det.driver.acquire, True)
    set_mock_value(det.cb_plugin.array_size_x, 10)
    set_mock_value(det.cb_plugin.array_size_y, 10)

    return det


@pytest.fixture
def cont_acq_controller(RE):
    with init_devices(mock=True):
        drv = adcore.ADBaseIO("DRV")
        cb_plugin = adcore.NDPluginCBIO("CB1")

    set_mock_value(drv.image_mode, adcore.ImageMode.CONTINUOUS)
    set_mock_value(drv.acquire_time, 0.8)
    set_mock_value(drv.acquire_period, 1.0)
    set_mock_value(drv.acquire, True)
    return adcore.ADBaseContAcqController(drv, cb_plugin)


@pytest.fixture
def one_shot_trigger_info_factory():
    def generate_one_shot_trigger_info(
        trigger_mode=DetectorTrigger.INTERNAL, livetime=0.8
    ):
        if trigger_mode != DetectorTrigger.INTERNAL:
            return TriggerInfo(
                number_of_triggers=1,
                trigger=trigger_mode,
                livetime=livetime,
                deadtime=0.001,
            )
        else:
            return TriggerInfo(
                number_of_triggers=1, trigger=trigger_mode, livetime=livetime
            )

    return generate_one_shot_trigger_info


async def test_cont_acq_controller_invalid_trigger_mode(
    cont_acq_controller: adcore.ADBaseContAcqController, one_shot_trigger_info_factory
):
    trigger_info = one_shot_trigger_info_factory(
        trigger_mode=DetectorTrigger.CONSTANT_GATE
    )
    with pytest.raises(TypeError) as e:
        await cont_acq_controller.prepare(trigger_info)
    assert (
        str(e.value)
        == "The continuous acq interface only supports internal triggering."
    )


async def test_cont_acq_controller_invalid_exp_time(
    cont_acq_controller: adcore.ADBaseContAcqController, one_shot_trigger_info_factory
):
    with pytest.raises(ValueError) as e:
        await cont_acq_controller.prepare(one_shot_trigger_info_factory(livetime=0.1))
    assert (
        str(e.value)
        == "Detector exposure time currently set to 0.8, but requested exposure is 0.1"
    )


async def test_cont_acq_controller_not_in_continuous_mode(
    cont_acq_controller: adcore.ADBaseContAcqController, one_shot_trigger_info_factory
):
    set_mock_value(cont_acq_controller.driver.image_mode, adcore.ImageMode.SINGLE)

    with pytest.raises(RuntimeError) as e:
        await cont_acq_controller.prepare(one_shot_trigger_info_factory())
    assert (
        str(e.value)
        == "Driver must be acquiring in continuous mode to use the cont acq interface"
    )


async def test_cont_acq_controller_not_acquiring(
    cont_acq_controller: adcore.ADBaseContAcqController, one_shot_trigger_info_factory
):
    set_mock_value(cont_acq_controller.driver.acquire, False)

    with pytest.raises(RuntimeError) as e:
        await cont_acq_controller.prepare(one_shot_trigger_info_factory())
    assert (
        str(e.value)
        == "Driver must be acquiring in continuous mode to use the cont acq interface"
    )


async def test_hints_from_hdf_writer(cont_acq_det: adcore.ContAcqAreaDetector):
    assert cont_acq_det.hints == {"fields": [cont_acq_det.name]}


async def test_can_read(cont_acq_det: adcore.ContAcqAreaDetector):
    # Standard detector can be used as Readable
    assert (await cont_acq_det.read()) == {}


async def test_decribe_describes_writer_dataset(
    cont_acq_det: adcore.ContAcqAreaDetector, one_shot_trigger_info: TriggerInfo
):
    assert await cont_acq_det.describe() == {}
    await cont_acq_det.stage()
    await cont_acq_det.prepare(one_shot_trigger_info)
    assert await cont_acq_det.describe() == {
        "test_adcontacqarea1": {
            "source": "mock+ca://CONTACQAREA1:HDF1:FullFileName_RBV",
            "shape": [10, 10],
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    cont_acq_det: adcore.ContAcqAreaDetector,
    static_path_provider: PathProvider,
    one_shot_trigger_info: TriggerInfo,
):
    path_info = static_path_provider()
    full_file_name = path_info.directory_path / f"{path_info.filename}.h5"

    await cont_acq_det.stage()
    await cont_acq_det.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in cont_acq_det.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "test_adcontacqarea1"
    assert stream_resource["uri"] == "file://localhost/" + str(full_file_name).lstrip(
        "/"
    )
    assert stream_resource["parameters"] == {
        "dataset": "/entry/data/data",
        "swmr": False,
        "multiplier": 1,
        "chunk_shape": (1, 10, 10),
    }
    assert docs[1][0] == "stream_datum"
    stream_datum = docs[1][1]
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


async def test_can_decribe_collect(
    cont_acq_det: adcore.ContAcqAreaDetector, one_shot_trigger_info: TriggerInfo
):
    assert (await cont_acq_det.describe_collect()) == {}
    await cont_acq_det.stage()
    await cont_acq_det.prepare(one_shot_trigger_info)
    assert (await cont_acq_det.describe_collect()) == {
        "test_adcontacqarea1": {
            "source": "mock+ca://CONTACQAREA1:HDF1:FullFileName_RBV",
            "shape": [10, 10],
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }
