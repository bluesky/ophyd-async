"""Generic subprocess lifecycle management for backend test/demo servers.

`ophyd_async.epics.testing`/`ophyd_async.epics.demo` and
`ophyd_async.tango.testing`/`ophyd_async.tango.demo` each know how to build the
argv for *their* kind of backend server (an EPICS IOC, a Tango device server).
Actually spawning it, waiting for readiness, and shutting it down cleanly (with a
kill fallback) is identical in shape for both, so it lives here once - see
`ophyd_async.epics.testing.start_ioc`/`ophyd_async.tango.testing.
start_tango_device_servers` for the thin, ecosystem-specific wrappers built on top
that pin the readiness/shutdown behaviour so callers only ever have to pass argv.

Callers never need to read anything back from the subprocess beyond "has it
started" - PV names / Tango TRLs are predictable directly from the prefix each
caller chooses (mirroring how a real `softIoc -d some.db -m "PREFIX:"` never tells
you its PV names either: you already know them, since the db file is fixed and only
the macro varies).
"""

import socket
import subprocess
import time
from collections.abc import Sequence


def find_free_port() -> int:
    """Find a currently-unused TCP port on localhost.

    For callers that need to tell a subprocess which port to listen on up
    front (e.g. `ophyd_async.tango.testing.start_tango_device_servers`,
    which - unlike an EPICS IOC - can't rely on a fixed macro-based address
    scheme, since a Tango TRL bakes the port straight into the URL). The
    standard "bind to port 0, read back what the OS assigned, close it"
    trick - the same one pytest/tox use. There's an unavoidable (tiny) race
    between this returning and whatever you start next actually binding that
    port - acceptable for test/demo subprocess launching, not a security
    boundary.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ManagedSubprocess:
    """A started subprocess, owning its `Popen` and able to stop it cleanly."""

    def __init__(
        self,
        subprocess_args: Sequence[str],
        ready_marker: str,
        *,
        startup_timeout: float = 15.0,
        stop_input: str | None = None,
        shutdown_timeout: float = 10.0,
    ):
        self._subprocess_args = list(subprocess_args)
        self._ready_marker = ready_marker
        self._startup_timeout = startup_timeout
        self._stop_input = stop_input
        self._shutdown_timeout = shutdown_timeout
        self._process: subprocess.Popen | None = None
        self.output = ""

    def start(self) -> None:
        self._process = subprocess.Popen(
            self._subprocess_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        assert self._process.stdout  # noqa: S101 # for type checkers
        start_time = time.monotonic()
        while self._ready_marker not in self.output:
            if time.monotonic() - start_time > self._startup_timeout:
                self.stop()
                raise TimeoutError(
                    f"Subprocess did not become ready within "
                    f"{self._startup_timeout}s:\n{self.output}"
                )
            line = self._process.stdout.readline()
            if not line:
                self.stop()
                raise RuntimeError(
                    f"Subprocess exited before becoming ready:\n{self.output}"
                )
            self.output += line

    def stop(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            stdout, _ = process.communicate(
                self._stop_input, timeout=self._shutdown_timeout
            )
            self.output += stdout or ""
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, _ = process.communicate()
            self.output += stdout or ""

    def __enter__(self) -> "ManagedSubprocess":
        self.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.stop()


def start_subprocess(
    subprocess_args: Sequence[str],
    ready_marker: str,
    *,
    startup_timeout: float = 15.0,
    stop_input: str | None = None,
    shutdown_timeout: float = 10.0,
) -> ManagedSubprocess:
    """Start a backend server subprocess.

    :param subprocess_args: Full argv to spawn,
        e.g. `[sys.executable, "-m", "epicscorelibs.ioc", ...]`.
    :param ready_marker: Substring to watch for on the subprocess's stdout
        (stderr is merged into stdout) indicating it's ready to accept
        connections. Blocks until this appears.
    :param startup_timeout: Seconds to wait for `ready_marker` before giving up.
    :param stop_input: Written to the subprocess's stdin (then stdin is closed)
        by `.stop()` to request a clean shutdown, e.g. `"exit()"` for an EPICS
        IOC shell. If `None`, stdin is just closed with nothing written first -
        the shutdown mechanism the Tango device server scripts in this repo use
        (they block reading stdin and exit on EOF).
    :param shutdown_timeout: Seconds to wait for a clean exit after requesting
        shutdown before killing.

    Returns a handle whose `.stop()` requests that clean shutdown (killing it if
    it doesn't exit in time); also usable as a context manager.
    """
    process = ManagedSubprocess(
        subprocess_args,
        ready_marker,
        startup_timeout=startup_timeout,
        stop_input=stop_input,
        shutdown_timeout=shutdown_timeout,
    )
    process.start()
    return process
