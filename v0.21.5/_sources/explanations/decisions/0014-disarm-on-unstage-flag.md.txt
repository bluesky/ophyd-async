# 14. Pass `on_unstage` to `DetectorArmLogic.disarm`

Date: 2026-04-15

## Status

Accepted

## Context

`StandardDetector._disarm_and_stop()` is called from both `stage()` (to reset
the detector before a new scan) and `unstage()` (to clean up after a scan
ends). Both call sites previously invoked `disarm()` identically, giving
implementations no way to distinguish between them.

This matters when a beamline embeds shutter logic inside a detector's arm
logic. For example, a detector may need a shutter to stay open between
exposures during a scan, but the shutter must always be closed at the end.
Closing the shutter inside `disarm()` without this context would close it at
`stage()` too — potentially closing a shutter that should remain open.

## Decision

`DetectorArmLogic.disarm` now accepts `on_unstage: bool = False`. The flag is
`False` when called from `stage()` (setup before a scan) and `True` when
called from `unstage()` (teardown after a scan). All existing implementations
default to `False` and ignore the flag, preserving backward compatibility.

## Consequences

Implementations that need end-of-scan cleanup (such as closing a shutter) can
branch on `on_unstage`. Existing `DetectorArmLogic` subclasses must be updated
to add the `on_unstage: bool` parameter; the change is mechanical and the flag
can be ignored by implementations that do not need it.
