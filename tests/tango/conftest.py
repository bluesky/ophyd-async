import os
import sys

import pytest

from tango.asyncio_executor import set_global_executor


@pytest.fixture(autouse=True)
def reset_tango_asyncio():
    set_global_executor(None)


def pytest_collection_modifyitems(config, items):
    tango_dir = os.path.join("tests", "tango")
    for item in items:
        if tango_dir in str(item.fspath):
            if sys.version_info >= (3, 12):
                item.add_marker(
                    pytest.mark.skip(
                        reason="Tango is currently not supported on Python 3.12: https://github.com/bluesky/ophyd-async/issues/681"
                    )
                )
            elif "win" in sys.platform:
                item.add_marker(
                    pytest.mark.skip(
                        reason=(
                            "Tango tests are currently not supported on Windows: "
                            "https://github.com/bluesky/ophyd-async/issues/733"
                        )
                    )
                )
            else:
                item.add_marker(pytest.mark.forked)
