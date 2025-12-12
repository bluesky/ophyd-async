import asyncio
import os
import pprint
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from bluesky.run_engine import RunEngine, TransitionError
from bluesky.utils import new_uid
from pytest import FixtureRequest

from ophyd_async.core import (
    DetectorTrigger,
    FilenameProvider,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    init_devices,
)
from ophyd_async.epics import adsimdetector

PANDA_RECORD = str(
    Path(__file__).parent / "unit_tests" / "fastcs" / "panda" / "db" / "panda.db"
)
INCOMPLETE_BLOCK_RECORD = str(
    Path(__file__).parent
    / "unit_tests"
    / "fastcs"
    / "panda"
    / "db"
    / "incomplete_block_panda.db"
)
INCOMPLETE_RECORD = str(
    Path(__file__).parent
    / "unit_tests"
    / "fastcs"
    / "panda"
    / "db"
    / "incomplete_panda.db"
)
EXTRA_BLOCKS_RECORD = str(
    Path(__file__).parent
    / "unit_tests"
    / "fastcs"
    / "panda"
    / "db"
    / "extra_blocks_panda.db"
)


def fixture_is_used(fixture_name, session):
    """
    Helper function to check if a fixture is used in a pytest session
    """
    for item in session.items:
        for f in item.fixturenames:
            if f == fixture_name:
                return True
    return False


def pytest_collection_modifyitems(session, config, items):
    # Raise a runtime error if docker cannot communicate to the host
    # This is needed when we want to run docker fixtures in subprocesses
    # as pytest-insubprocess doesn't report fixture errors
    if fixture_is_used("docker_composer", session):
        check_docker_sock()


# Autouse fixture that will set all EPICS networking env vars to use lo interface
# to avoid false failures caused by things like firewalls blocking EPICS traffic.
@pytest.fixture(scope="session", autouse=True)
def configure_epics_environment():
    os.environ["EPICS_CAS_INTF_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CAS_BEACON_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_CAS_AUTO_ADDR_LIST"] = "NO"
    os.environ["EPICS_CA_AUTO_BEACON_ADDR_LIST"] = "NO"

    os.environ["EPICS_PVAS_INTF_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_PVAS_BEACON_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_PVA_ADDR_LIST"] = "127.0.0.1"
    os.environ["EPICS_PVAS_AUTO_BEACON_ADDR_LIST"] = "NO"
    os.environ["EPICS_PVA_AUTO_ADDR_LIST"] = "NO"


_ALLOWED_PYTEST_TASKS = {"async_finalizer", "async_setup", "async_teardown"}


def _error_and_kill_pending_tasks(
    loop: asyncio.AbstractEventLoop, test_name: str, test_passed: bool
) -> set[asyncio.Task]:
    """Cancels pending tasks in the event loop for a test. Raises an exception if
    the test hasn't already.

    Args:
        loop: The event loop to check for pending tasks.
        test_name: The name of the test.
        test_passed: Indicates whether the test passed.

    Returns:
        set[asyncio.Task]: The set of unfinished tasks that were cancelled.

    Raises:
        RuntimeError: If there are unfinished tasks and the test didn't fail.
    """
    unfinished_tasks = {
        task
        for task in asyncio.all_tasks(loop)
        if (coro := task.get_coro()) is not None
        and hasattr(coro, "__name__")
        and coro.__name__ not in _ALLOWED_PYTEST_TASKS
        and not task.done()
    }
    for task in unfinished_tasks:
        task.cancel()

    # We only raise an exception here if the test didn't fail anyway.
    # If it did then it makes sense that there's some tasks we need to cancel,
    # but an exception will already have been raised.
    if unfinished_tasks and test_passed:
        raise RuntimeError(
            f"Not all tasks closed during test {test_name}:\n"
            f"{pprint.pformat(unfinished_tasks, width=88)}"
        )

    return unfinished_tasks


@pytest.fixture(autouse=True, scope="function")
async def fail_test_on_unclosed_tasks(request: FixtureRequest):
    """Used on every test to ensure failure if there are pending tasks
    by the end of the test.
    """
    try:
        fail_count = request.session.testsfailed
        loop = asyncio.get_running_loop()

        loop.set_debug(True)

        request.addfinalizer(
            lambda: _error_and_kill_pending_tasks(
                loop, request.node.name, request.session.testsfailed == fail_count
            )
        )
    # Once https://github.com/bluesky/ophyd-async/issues/683
    # is finished we can remove this try, except.
    except RuntimeError as error:
        if str(error) != "no running event loop":
            raise error


@pytest.fixture(scope="function")
def RE(request: FixtureRequest):
    loop = asyncio.new_event_loop()
    loop.set_debug(True)
    RE = RunEngine({}, call_returns_result=True, loop=loop)
    fail_count = request.session.testsfailed

    def clean_event_loop():
        if RE.state not in ("idle", "panicked"):
            try:
                RE.halt()
            except TransitionError:
                pass

        loop.call_soon_threadsafe(loop.stop)
        RE._th.join()

        try:
            _error_and_kill_pending_tasks(
                loop, request.node.name, request.session.testsfailed == fail_count
            )
        finally:
            loop.close()

    request.addfinalizer(clean_event_loop)
    return RE


@pytest.fixture(scope="module", params=["pva"])
def panda_pva():
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "epicscorelibs.ioc",
                "-m",
                macros,
                "-d",
                PANDA_RECORD,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        for macros in [
            "INCLUDE_EXTRA_BLOCK=,INCLUDE_EXTRA_SIGNAL=",
            "EXCLUDE_WIDTH=#,IOC_NAME=PANDAQSRVIB",
            "EXCLUDE_PCAP=#,IOC_NAME=PANDAQSRVI",
        ]
    ]
    time.sleep(2)

    for p in processes:
        assert not p.poll(), p.stdout.read()

    yield processes

    for p in processes:
        p.terminate()
        p.communicate()


@pytest.fixture
async def normal_coroutine() -> Callable[[], Any]:
    async def inner_coroutine():
        await asyncio.sleep(0.01)

    return inner_coroutine


@pytest.fixture
async def failing_coroutine() -> Callable[[], Any]:
    async def inner_coroutine():
        await asyncio.sleep(0.01)
        raise ValueError()

    return inner_coroutine


@pytest.fixture
def static_filename_provider():
    return StaticFilenameProvider("ophyd_async_tests")


@pytest.fixture
def static_path_provider_factory(tmp_path: Path):
    def create_static_dir_provider_given_fp(
        fp: FilenameProvider, directory_uri: str | None = None
    ):
        return StaticPathProvider(fp, tmp_path, directory_uri=directory_uri)

    return create_static_dir_provider_given_fp


@pytest.fixture
def static_path_provider(
    static_path_provider_factory: Callable,
    static_filename_provider: FilenameProvider,
):
    return static_path_provider_factory(static_filename_provider)


@pytest.fixture
def one_shot_trigger_info(request: FixtureRequest) -> TriggerInfo:
    # If the fixture is called with a parameter, use it as the exposures_per_event
    # otherwise use 1
    param = getattr(request, "param", 1)
    return TriggerInfo(
        number_of_events=1,
        trigger=DetectorTrigger.INTERNAL,
        livetime=None,
        exposures_per_event=param if isinstance(param, int) else 1,
    )


@pytest.fixture
async def sim_detector(request: FixtureRequest):
    """Fixture that creates a simulated detector.

    Args:
        prefix (str): The PV prefix for the detector
        name (str): Name for the detector instance
        tmp_path (Path): Temporary directory for file writing
    """
    prefix = (
        request.param[0] if isinstance(request.param, list | tuple) else request.param
    )
    name = request.param[1] if isinstance(request.param, list | tuple) else "test"
    tmp_path = request.getfixturevalue("tmp_path")

    fp = StaticFilenameProvider(f"test-{new_uid()}")
    dp = StaticPathProvider(fp, tmp_path)

    async with init_devices(mock=True):
        det = adsimdetector.SimDetector(prefix, dp, name=name)

    det._config_sigs = [det.driver.acquire_time, det.driver.acquire]

    return det


def check_docker_sock():
    """
    Check if the Docker (or compatible container engine) socket is accessible.

    This function attempts to run `docker info` to verify that the current user
    can communicate with the container engine. If the command fails, it raises
    a RuntimeError with guidance on how to fix common connection issues.
    """
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as err:
        message = """
            Cannot communicate with the container engine on the host.
            Please make sure $DOCKER_HOST points to the correct socket on the host.
            NOTE:
                If you are using podman, please enable the socket by running
                systemctl --user enable podman --now"""
        raise RuntimeError(message) from err


@pytest.fixture(scope="module")
def docker_composer():
    def inner_docker_composer(
        docker_args: list[str] | None = None,
        docker_services: list[str] | str | None = None,
        ready_log_line: str | None = None,
        start_timeout: float | None = None,
        stop_timeout: float | None = None,
        wait_time: float | None = None,
    ):
        """
        Run a docker compose based service, optionally do the following:
        - wait a fixed time for the service to become ready
        - wait for the service to become ready by monitoring the STDOUT
        - run specific service(s)
        - raise for timeout
        E.g.:
            # run docker compose up and tear down after yielding
            docker_composer()
            # same as above but with additional args passed to docker
            docker_composer(docker_args=["-f", "./compose.yaml"])
            # run and wait for line in STDOUT before yielding
            docker_composer(ready_log_line="Listening on port ", start_timeout=10.0)
            # wait a fixed time for the service to become ready
            docker_composer(wait_time=1.0)
            # run specific sercices
            docker_composer(docker_services=["svc1","svc2"])
        """

        if docker_args is None:
            docker_args = []

        if docker_services is None:
            docker_services = []
        elif type(docker_services) is str:
            docker_services = [docker_services]

        # start docker compose as a background process
        process = subprocess.Popen(
            ["docker", "compose", *docker_args, "up", *docker_services],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            preexec_fn=os.setsid,  # To kill the whole group later
        )

        start_time = time.time()
        if ready_log_line is not None:
            try:
                assert process.stdout is not None
                for line in process.stdout:
                    print(line, end="")
                    if ready_log_line in line:
                        break
                    if (
                        start_timeout is not None
                        and time.time() - start_time > start_timeout
                    ):
                        raise TimeoutError(
                            f"docker compose with args {docker_args} timed out"
                        )
            except Exception:
                process.terminate()
                raise

        if wait_time is not None:
            time.sleep(wait_time)

        yield  # at this point service is expected to have started

        try:
            subprocess.run(
                ["docker", "compose", *docker_args, "down", *docker_services]
            )
        except subprocess.CalledProcessError as e:
            print(f"Failed to bring down docker services: {e}")

        # Terminate background process group
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass  # Already exited

        # Close stdout to avoid ResourceWarning
        if process.stdout:
            process.stdout.close()

        # Ensure process has exited
        process.wait(timeout=stop_timeout)

    yield inner_docker_composer


@pytest.fixture(scope="module")
def ca_gateway(docker_composer):
    example_services_path = os.environ.get("EXAMPLE_SERVICES_PATH", None)
    if example_services_path is not None:  # user may start services manually
        yield from docker_composer(
            ["-f", f"{example_services_path}/compose.yaml"],
            docker_services="ca-gateway",
            ready_log_line="Running as user ",
        )


@pytest.fixture(scope="module")
def bl01t_di_cam_01(ca_gateway, docker_composer):
    example_services_path = os.environ.get("EXAMPLE_SERVICES_PATH", None)
    if example_services_path is not None:  # user may start services manually
        yield from docker_composer(
            ["-f", f"{example_services_path}/compose.yaml"],
            docker_services="bl01t-di-cam-01",
            ready_log_line="iocRun: All initialization complete",
        )
