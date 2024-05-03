import uuid

import pytest

from ophyd_async.core import (
    AutoIncrementFilenameProvider,
    UUIDFilenameProvider,
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
