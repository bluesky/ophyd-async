import os
import subprocess

import pytest


@pytest.fixture(scope="session", autouse=True)
def docker_compose_services():
    compose_file = os.path.abspath("example-services/compose.yaml")
    services = ["bl01t-di-cam-01", "ca-gateway"]
    # Start services
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "up", "-d"] + services,
        check=True,
    )
    yield
    # Stop services after tests
    subprocess.run(
        ["docker", "compose", "-f", compose_file, "down"],
        check=True,
    )
