# Environment Variables

Every environment variable ophyd-async reads. The first group affects the library
at runtime; the second is read only by the test suite, and setting it has no
effect on ophyd-async itself.

## Runtime

(OPHYD_ASYNC_PRESERVE_DETECTOR_STATE)=

## `OPHYD_ASYNC_PRESERVE_DETECTOR_STATE`

Controls the implicit prepare performed by
[`StandardDetector.trigger()`](#ophyd_async.core.StandardDetector.trigger) when
[`prepare()`](#ophyd_async.core.StandardDetector.prepare) has not been called since
the last [`stage()`](#ophyd_async.core.StandardDetector.stage).

| Value | Behaviour |
|-------|-----------|
| `YES` | Calls [`DetectorTriggerLogic.default_trigger_info()`](#ophyd_async.core.DetectorTriggerLogic.default_trigger_info) to read current hardware state before the implicit prepare. Raises `RuntimeError` if `default_trigger_info()` is not implemented on the trigger logic. |
| anything else (default) | Uses a bare [`TriggerInfo()`](#ophyd_async.core.TriggerInfo), resetting detector state to defaults. |

See [ADR 0013](../explanations/decisions/0013-preserve-hardware-state-in-step-scan.md)
for rationale.

(OPHYD_ASYNC_EPICS_CA_KEEP_ALL_UPDATES)=

## `OPHYD_ASYNC_EPICS_CA_KEEP_ALL_UPDATES`

Controls how the Channel Access signal backend handles backpressure when it cannot
keep up with a PV's updates.

| Value | Behaviour |
|-------|-----------|
| `True` (default) | Buffers updates, lagging behind if the IOC pushes them faster than they can be handled. No update is dropped. |
| anything else | Drops updates that cannot be handled in time, which is `aioca`'s own default. |

The value is compared against the exact string `True`, so any other spelling —
`true`, `1`, `yes` — selects the "anything else" row and drops updates.

See [ADR 0011](../explanations/decisions/0011-buffer-updates-camonitor.md) for
rationale.

(OPHYD_ASYNC_ALLOW_RESERVED_ATTRS)=

## `OPHYD_ASYNC_ALLOW_RESERVED_ATTRS`

Disables the check that stops a [](#Device) attribute being given a name that
collides with a bluesky protocol method (`set`, `read`, `trigger`, ...).

| Value | Behaviour |
|-------|-----------|
| `YES` | Assigning to a reserved name is allowed, e.g. `device.set = AsyncMock()`. |
| anything else (default) | Assigning to a reserved name raises `NameError`. |

Intended as a quick escape for downstream test suites that mock protocol methods
this way, so they can be turned back on without editing every call site. To
override a single attribute instead, prefer
[](#ophyd_async.core.set_mock_attr), which does not disable the check globally.

## Test suite

These are read by the tests only, and are irrelevant to using ophyd-async as a
library. They are needed to run [](../how-to/contribute.md)'s system and container
tests, which start real IOCs in containers. A devcontainer sets all of them for
you; see `.devcontainer/devcontainer.json`.

(EXAMPLE_SERVICES_PATH)=

### `EXAMPLE_SERVICES_PATH`

Path to the `example-services` directory holding the compose files for those IOCs.
No default: the tests that need it raise if it is unset.

It must be the path **as the host sees it**, not as the pytest process does. Those
IOCs are started with `docker compose` against the host's container engine, so a
path that only the test process can see does not resolve.

(OPHYD_ASYNC_SHARED_TMP_DIR)=

### `OPHYD_ASYNC_SHARED_TMP_DIR`

The absolute path of a directory that resolves to the same place for both the
pytest process and inside an IOC container. Defaults to
`/tmp/ophyd-async-shared-tmp`.

A detector is told where to write over Channel Access, as a plain string, and the
IOC opens that path in *its own* filesystem — so a path that means different things
on each side makes the IOC report the directory missing. pytest's own `tmp_path`
is exactly such a path.

(OPHYD_ASYNC_SHARED_TMP_SOURCE)=

### `OPHYD_ASYNC_SHARED_TMP_SOURCE`

What gets mounted at [](#OPHYD_ASYNC_SHARED_TMP_DIR) in the IOC container: either a
host path or a named volume. Defaults to the same value as
[](#OPHYD_ASYNC_SHARED_TMP_DIR).

That default is the bare-host shape, and is what CI uses: pytest and the container
engine already share a filesystem, so one host path bound to itself needs no
translation. A devcontainer shares no filesystem with the host and must set both
variables — pointing this one at a named volume, which the engine resolves to the
same storage for every container whatever launched it.
