import os
import uuid
from datetime import date

import pytest

from ophyd_async.core import (
    AutoIncrementFilenameProvider,
    UUIDFilenameProvider,
    YMDPathProvider,
)


def test_auto_increment_filename_provider(static_path_provider_factory):
    auto_inc_fp = AutoIncrementFilenameProvider(inc_delimeter="")
    dp = static_path_provider_factory(auto_inc_fp)

    for i in range(100000):
        info = dp()
        assert int(info.filename) == i

    with pytest.raises(ValueError):
        dp()


@pytest.mark.parametrize(
    "uuid_version", [uuid.uuid1, uuid.uuid3, uuid.uuid4, uuid.uuid5]
)
def test_uuid_filename_provider(static_path_provider_factory, uuid_version):
    uuid_fp = UUIDFilenameProvider(uuid_call_func=uuid_version)
    if uuid_version in [uuid.uuid3, uuid.uuid5]:
        uuid_fp.specify_uuid_namespace(uuid.NAMESPACE_URL, "test")
    dp = static_path_provider_factory(uuid_fp)

    info = dp()

    # Try creating a UUID object w/ given version to check if it is valid uuid
    uuid.UUID(info.filename, version=int(uuid_version.__name__[-1]))


@pytest.mark.parametrize("uuid_version", [uuid.uuid3, uuid.uuid5])
def test_uuid_filename_provider_no_namespace(
    static_path_provider_factory, uuid_version
):
    uuid_fp = UUIDFilenameProvider(uuid_call_func=uuid_version)
    dp = static_path_provider_factory(uuid_fp)

    with pytest.raises(ValueError):
        dp()


def test_ymd_path_provider(static_filename_provider, tmp_path):
    ymd_path_provider = YMDPathProvider(static_filename_provider, tmp_path)
    current_date = date.today()
    date_path = os.path.join(
        str(current_date.year), str(current_date.month), str(current_date.day)
    )

    info_a = ymd_path_provider()
    assert info_a.resource_dir == date_path

    info_b = ymd_path_provider(device_name="test_device")
    assert info_b.resource_dir == os.path.join("test_device", date_path)
