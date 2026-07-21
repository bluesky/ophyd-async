import asyncio
import os
import pprint
import shutil
import signal
import subprocess
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from bluesky.run_engine import RunEngine, TransitionError
from pytest import FixtureRequest

from ophyd_async.core import (
    FilenameProvider,
    StaticFilenameProvider,
    StaticPathProvider,
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


# Compose override giving the cam IOC a directory pytest and the IOC agree on.
SHARED_TMP_COMPOSE_FILE = str(Path(__file__).parent / "compose-shared-tmp.yaml")

# IOCs are started against the *host's* container engine, so a directory handed
# to an IOC over Channel Access must have the same absolute path for pytest and
# for the IOC. The default is the bare-host shape (CI, or running the tests
# directly on a workstation): pytest and the engine already share a filesystem,
# so one host path bound to itself needs no translation. A devcontainer does not
# share the host's filesystem and must point these at something the engine
# resolves identically for every container - it sets both itself, see
# .devcontainer/devcontainer.json. OPHYD_ASYNC_SHARED_TMP_SOURCE is a host path
# or a volume name; OPHYD_ASYNC_SHARED_TMP_DIR is the path both sides use.
os.environ.setdefault("OPHYD_ASYNC_SHARED_TMP_DIR", "/tmp/ophyd-async-shared-tmp")
os.environ.setdefault(
    "OPHYD_ASYNC_SHARED_TMP_SOURCE", os.environ["OPHYD_ASYNC_SHARED_TMP_DIR"]
)


@pytest.fixture
def shared_tmp_path(request: FixtureRequest) -> Iterator[Path]:
    """A tmp_path that IOC containers can also see, at the same absolute path.

    `tmp_path` lives under the pytest process's own /tmp, which no IOC container
    mounts, so a directory handed to an IOC over Channel Access does not resolve
    there and the IOC reports it missing. Each test gets a unique directory,
    removed afterwards, so concurrent runs sharing the volume cannot collide.
    """
    root = Path(os.environ["OPHYD_ASYNC_SHARED_TMP_DIR"]) / "pytest-shared-tmp"
    path = root / f"{request.node.name}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


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
    # Fail at collection, with a clear message, if the container engine cannot
    # be reached - rather than once per test, as an opaque fixture error.
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


@pytest.fixture
async def normal_coroutine() -> tuple[Callable[[], Any], asyncio.Event]:
    is_running = asyncio.Event()

    async def inner_coroutine():
        is_running.set()
        await asyncio.sleep(0.01)

    return inner_coroutine, is_running


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


def check_docker_sock():
    """
    Check if the Docker (or compatible container engine) socket is accessible.

    This function attempts to run `docker info` to verify that the current user
    can communicate with the container engine. Retries for up to 10 seconds before
    raising a RuntimeError with guidance on how to fix common connection issues.
    """
    deadline = time.monotonic() + 10.0
    last_output = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode == 0:
            return
        last_output = result.stdout
        time.sleep(0.5)

    message = f"""
        Cannot communicate with the container engine on the host.
        Please make sure $DOCKER_HOST points to the correct socket on the host.
        NOTE:
            For podman, $DOCKER_HOST is typically set by running
                export DOCKER_HOST="unix://$XDG_RUNTIME_DIR/podman/podman.sock"
            Also, if you are using podman please enable the socket by running
                systemctl --user enable podman --now
        docker info output:
            {last_output}"""
    raise RuntimeError(message)


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


def example_services_compose_file() -> str:
    """The compose file describing the IOCs the system tests run against.

    Raises loudly when EXAMPLE_SERVICES_PATH is unset. The fixtures below used to
    skip starting anything instead, on the grounds that the services might have
    been started by hand - but a fixture generator has to yield exactly once, so
    that branch only ever produced

        ValueError: ca_gateway did not yield a value

    which names neither the variable nor the environment, and reads like a bug in
    the test suite rather than a missing setting.
    """
    path = os.environ.get("EXAMPLE_SERVICES_PATH")
    if not path:
        raise RuntimeError(
            "EXAMPLE_SERVICES_PATH is not set, so the IOCs these tests need "
            "cannot be started.\n"
            "Set it to the example-services directory as the *host* sees it - "
            "docker compose runs against the host's container engine, so a path "
            "only this process can see will not resolve:\n"
            "    export EXAMPLE_SERVICES_PATH=<path to repo>/example-services\n"
            "A devcontainer sets this for you (see .devcontainer/"
            "devcontainer.json); if you are in one and still seeing this, the "
            "variable has not reached this process."
        )
    return f"{path}/compose.yaml"


@pytest.fixture(scope="module")
def ca_gateway(docker_composer):
    yield from docker_composer(
        ["-f", example_services_compose_file()],
        docker_services="ca-gateway",
        ready_log_line="Running as user ",
    )


@pytest.fixture(scope="module")
def bl01t_di_cam_01(ca_gateway, docker_composer):
    # Create it before compose binds it: a rootful engine would otherwise
    # create the source as root, which pytest could then not write to.
    Path(os.environ["OPHYD_ASYNC_SHARED_TMP_DIR"]).mkdir(parents=True, exist_ok=True)
    yield from docker_composer(
        [
            "-f",
            example_services_compose_file(),
            "-f",
            SHARED_TMP_COMPOSE_FILE,
        ],
        docker_services="bl01t-di-cam-01",
        # Not "iocRun: All initialization complete": the IOC configures itself
        # *after* iocInit, from the epics.PostStartupCommand in its ioc.yaml,
        # and the first thing that block does is
        # `dbpf BL01T-DI-CAM-01:DET:AcquireTime 0.1`. A test that connects
        # while that is still in flight has its own exposure overwritten with
        # 0.1 - which is what made test_prepare_is_idempotent... flake, and only
        # ever on a cold start, where the gap is wide enough to lose the race.
        # `Acquire 1` is the *last* command in that block and the commands run
        # in order, so seeing it echoed means the whole block has run. That ties
        # us to a pinned submodule's config (example-services, tag 2025.8.2): if
        # a command is ever appended after it, this goes back to being too early.
        ready_log_line="dbpf BL01T-DI-CAM-01:DET:Acquire 1",
    )
