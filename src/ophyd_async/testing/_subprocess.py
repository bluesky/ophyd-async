"""Generic subprocess lifecycle management for backend test/demo servers.

`ophyd_async.epics.testing`/`ophyd_async.epics.demo` and
`ophyd_async.tango.testing`/`ophyd_async.tango.demo` each know how to build the
argv for *their* kind of backend server (an EPICS IOC, a Tango device server) and
how to recognise it's ready and ask it to stop - that's a `SubprocessSpec`. Actually
spawning it, waiting for readiness, and shutting it down cleanly (with a kill
fallback) is identical in shape for both, so it lives here once.

Callers never need to read anything back from the subprocess beyond "has it
started" - PV names / Tango TRLs are predictable directly from the prefix each
caller chooses (mirroring how a real `softIoc -d some.db -m "PREFIX:"` never tells
you its PV names either: you already know them, since the db file is fixed and only
the macro varies).
"""

import subprocess
import time
from dataclasses import dataclass


@dataclass
class SubprocessSpec:
    """Describes how to start, recognise readiness in, and stop a subprocess."""

    args: list[str]
    """Full argv to spawn, e.g. `[sys.executable, "-m", "epicscorelibs.ioc", ...]`."""
    ready_marker: str
    """Substring to watch for on the subprocess's stdout (stderr is merged into
    stdout) indicating it's ready to accept connections."""
    startup_timeout: float = 15.0
    """Seconds to wait for `ready_marker` to appear before giving up."""
    stop_input: str | None = None
    """Written to the subprocess's stdin (then stdin is closed) to request a clean
    shutdown, e.g. `"exit()"` for an EPICS IOC shell. If None, stdin is just closed
    with nothing written first - the shutdown mechanism the Tango device server
    scripts in this repo use (they block reading stdin and exit on EOF)."""
    shutdown_timeout: float = 10.0
    """Seconds to wait for a clean exit after requesting shutdown before killing."""


class ManagedSubprocess:
    """A started `SubprocessSpec`, owning its `Popen` and able to stop it."""

    def __init__(self, spec: SubprocessSpec):
        self._spec = spec
        self._process: subprocess.Popen | None = None
        self.output = ""

    def start(self) -> None:
        self._process = subprocess.Popen(
            self._spec.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        assert self._process.stdout  # noqa: S101 # for type checkers
        start_time = time.monotonic()
        while self._spec.ready_marker not in self.output:
            if time.monotonic() - start_time > self._spec.startup_timeout:
                self.stop()
                raise TimeoutError(
                    f"Subprocess did not become ready within "
                    f"{self._spec.startup_timeout}s:\n{self.output}"
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
                self._spec.stop_input, timeout=self._spec.shutdown_timeout
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


def start_subprocess(spec: SubprocessSpec) -> ManagedSubprocess:
    """Start a backend server subprocess described by `spec`.

    Blocks until `spec.ready_marker` appears on its output. Returns a handle whose
    `.stop()` requests a clean shutdown (killing it if it doesn't exit in time); also
    usable as a context manager.
    """
    process = ManagedSubprocess(spec)
    process.start()
    return process
