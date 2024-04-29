import uuid

import pytest

from ophyd_async.core import (
    AutoIncrementFilenameProvider,
    DeviceNameFilenameProvider,
    DynamicFilenameProvider,
    UUIDFilenameProvider,
)


def test_dynamic_filename_provider(static_directory_provider_factory):
    dyn_fp = DynamicFilenameProvider(base_filename="dyn_fp_test")
    dp = static_directory_provider_factory(dyn_fp)

    info_a = dp()
    assert info_a.filename == "dyn_fp_test"

    dyn_fp.base_filename = "dyn_fp_test2"

    info_b = dp()
    assert info_b.filename == "dyn_fp_test2"

    dyn_fp.prefix = "prefix_test_"

    info_c = dp()
    assert info_c.filename == "prefix_test_dyn_fp_test2"

    dyn_fp.suffix = "_suffix_test"

    info_d = dp()
    assert info_d.filename == "prefix_test_dyn_fp_test2_suffix_test"


def test_devicename_filename_provider(static_directory_provider_factory):
    dev_name_fp = DeviceNameFilenameProvider(prefix="prefix_")
    dp = static_directory_provider_factory(dev_name_fp)

    info_a = dp(device_name="device_name_provider_test")
    assert info_a.filename == "prefix_device_name_provider_test"


def test_auto_increment_filename_provider(static_directory_provider_factory):
    auto_inc_fp = AutoIncrementFilenameProvider(inc_delimeter="")
    dp = static_directory_provider_factory(auto_inc_fp)

    for i in range(100000):
        info = dp()
        assert int(info.filename) == i

    with pytest.raises(ValueError):
        dp()


@pytest.mark.parametrize(
    "uuid_version", [uuid.uuid1, uuid.uuid3, uuid.uuid4, uuid.uuid5]
)
def test_uuid_filename_provider(static_directory_provider_factory, uuid_version):
    uuid_fp = UUIDFilenameProvider(uuid_call_func=uuid_version)
    if uuid_version in [uuid.uuid3, uuid.uuid5]:
        uuid_fp.specify_uuid_namespace(uuid.NAMESPACE_URL, "test")
    dp = static_directory_provider_factory(uuid_fp)

    info = dp()

    # Try creating a UUID object w/ given version to check if it is valid uuid
    uuid.UUID(info.filename, version=int(uuid_version.__name__[-1]))


@pytest.mark.parametrize("uuid_version", [uuid.uuid3, uuid.uuid5])
def test_uuid_filename_provider_no_namespace(
    static_directory_provider_factory, uuid_version
):
    uuid_fp = UUIDFilenameProvider(uuid_call_func=uuid_version)
    dp = static_directory_provider_factory(uuid_fp)

    with pytest.raises(ValueError):
        dp()
