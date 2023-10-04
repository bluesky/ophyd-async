from ophyd_async.core import DirectoryInfo, StaticDirectoryProvider


def test_static_directory_provider():
    """NOTE: this is a dummy test.

    It should be removed once detectors actually implement directory providers.
    This will happen in a soon to be developed PR.
    """
    dir_path, filename = "some/path", "test_file"
    provider = StaticDirectoryProvider(dir_path, filename)

    assert provider() == DirectoryInfo(dir_path, filename)
