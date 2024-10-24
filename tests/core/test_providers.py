import os
import uuid
from datetime import date

import pytest

from ophyd_async.core import (
    AutoIncrementFilenameProvider,
    AutoIncrementingPathProvider,
    UUIDFilenameProvider,
    YMDPathProvider,
)


def test_auto_increment_filename_provider(static_path_provider_factory):
    auto_inc_fp = AutoIncrementFilenameProvider(inc_delimeter="")
    dp = static_path_provider_factory(auto_inc_fp)

    # Our filenames should go from 00000 to 99999.
    # We increment by one each time, so just check if casting filename to
    # int gets us i.
    for i in range(100000):
        info = dp()
        assert int(info.filename) == i

    # Since default max digits is 5, incrementing one more time to 100000
    # will go over the limit and raise a value error
    with pytest.raises(ValueError):
        dp()


@pytest.mark.parametrize(
    "uuid_version", [uuid.uuid1, uuid.uuid3, uuid.uuid4, uuid.uuid5]
)
def test_uuid_filename_provider(static_path_provider_factory, uuid_version):
    uuid_call_args = []
    if uuid_version in [uuid.uuid3, uuid.uuid5]:
        uuid_call_args = [uuid.NAMESPACE_URL, "test"]
    uuid_fp = UUIDFilenameProvider(
        uuid_call_func=uuid_version, uuid_call_args=uuid_call_args
    )

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


def test_auto_increment_path_provider(static_filename_provider, tmp_path):
    auto_inc_path_provider = AutoIncrementingPathProvider(
        static_filename_provider, tmp_path, num_calls_per_inc=3, increment=2
    )

    for _ in range(3):
        info = auto_inc_path_provider()
        assert os.path.basename(info.directory_path) == "00000"
    info = auto_inc_path_provider()
    assert os.path.basename(info.directory_path) == "00002"


def test_ymd_path_provider(static_filename_provider, tmp_path):
    ymd_path_provider = YMDPathProvider(static_filename_provider, tmp_path)
    current_date = date.today()
    date_path = (
        f"{current_date.year:04d}/{current_date.month:02d}/{current_date.day:02d}"
    )

    info_a = ymd_path_provider()
    assert info_a.directory_path == tmp_path / date_path

    info_b = ymd_path_provider(device_name="test_device")
    assert info_b.directory_path == tmp_path / "test_device" / date_path
