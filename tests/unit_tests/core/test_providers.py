import itertools
import os
import sys
import uuid
from datetime import date
from pathlib import Path, PurePosixPath

import pytest
from pathlib2 import PureWindowsPath

from ophyd_async.core import (
    AutoIncrementFilenameProvider,
    AutoIncrementingPathProvider,
    StaticPathProvider,
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


def test_path_provider_fails_non_absolute_path(static_filename_provider):
    """Test that the path provider raises an error for non-absolute paths."""

    path_provider = StaticPathProvider(
        static_filename_provider, Path("non_absolute_path")
    )

    with pytest.raises(ValueError, match="directory_path must be an absolute path"):
        path_provider()


PATH_FORMATS = [
    PurePosixPath,
    PureWindowsPath,
]


@pytest.mark.parametrize(
    "write_path_format, read_path_format",
    list(itertools.product(PATH_FORMATS, PATH_FORMATS)),
)
def test_path_provider_with_different_uri(
    write_path_format, read_path_format, static_filename_provider
):
    """Test that the path provider can handle a custom URI."""

    posix_path_a = PurePosixPath("/tmp/posix_path_a")
    posix_path_b = PurePosixPath("/tmp/posix_path_b")

    windows_base_path = "C:\\Users\\test\\AppData\\Local\\Temp"
    windows_path_a = PureWindowsPath(f"{windows_base_path}\\windows_path_a")
    windows_path_b = PureWindowsPath(f"{windows_base_path}\\windows_path_b")

    write_path = posix_path_a
    if write_path_format is PureWindowsPath:
        write_path = windows_path_a

    read_path = posix_path_b
    if read_path_format is PureWindowsPath:
        read_path = windows_path_b

    path_provider = StaticPathProvider(
        static_filename_provider,
        write_path,
        directory_uri=f"file://localhost/{read_path.as_posix().lstrip('/')}/",
    )

    info = path_provider()

    if write_path_format is PureWindowsPath:
        assert str(info.directory_path) == f"{windows_base_path}\\windows_path_a"
    else:
        assert str(info.directory_path) == "/tmp/posix_path_a"

    if read_path_format is PureWindowsPath:
        assert (
            info.directory_uri
            == "file://localhost/C:/Users/test/AppData/Local/Temp/windows_path_b/"
        )
    else:
        assert info.directory_uri == "file://localhost/tmp/posix_path_b/"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix specific test")
def test_windows_path_produces_valid_path_info_on_unix(static_filename_provider):
    path = PureWindowsPath("C:\\Users\\test\\AppData\\Local\\Temp\\windows_path")
    path_provider = StaticPathProvider(static_filename_provider, path)
    info = path_provider()
    assert (
        str(info.directory_path)
        == "C:\\Users\\test\\AppData\\Local\\Temp\\windows_path"
    )
    assert (
        info.directory_uri
        == "file://localhost/C:/Users/test/AppData/Local/Temp/windows_path/"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test")
def test_posix_path_produces_valid_path_info_on_windows(static_filename_provider):
    path = PurePosixPath("/tmp/posix_path")
    path_provider = StaticPathProvider(static_filename_provider, path)
    info = path_provider()
    assert str(info.directory_path) == "/tmp/posix_path"
    assert info.directory_uri == "file://localhost/tmp/posix_path/"
